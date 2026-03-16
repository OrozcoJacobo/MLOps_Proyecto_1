"""
DAG 2: data_processing
========================
Responsabilidad: Transformar datos de raw → processed → ready.

Transformaciones (basadas en el notebook de preprocesamiento):
  1. raw_to_processed:
     - Elimina registros con nulos en features críticas
     - Filtra anomalías: Slope > 90 grados
     - Convierte wilderness_area de one-hot → categórico (Rawah, Neota, Commanche, Cache)
     - Convierte soil_type de one-hot → código categórico (C2702, C7745, etc.)
     - Convierte Cover_Type de rango 1-7 → 0-6
  2. processed_to_ready:
     - Split 70% train / 15% val / 15% test
     - Re-aplica one-hot encoding para dejar features listas para el modelo
"""

from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.utils.dates import days_ago
from datetime import timedelta
import logging
import os

DATA_DB_CONN = os.getenv("DATA_DB_CONN", "postgresql+psycopg2://mlops:mlops123@postgresql-data/mlops_db")

default_args = {
    "owner": "mlops-team",
    "depends_on_past": False,
    "retries": 2,
    "retry_delay": timedelta(minutes=2),
    "email_on_failure": False,
}

# ── Dominios (del notebook de preprocesamiento) ───────────────────────────────

WILDERNESS_AREA_NAMES = ["Rawah", "Neota", "Commanche", "Cache"]

SOIL_TYPE_CODES = [
    "C2702", "C2703", "C2704", "C2705", "C2706", "C2717",
    "C3501", "C3502", "C4201", "C4703", "C4704", "C4744",
    "C4758", "C5101", "C5151", "C6101", "C6102", "C6731",
    "C7101", "C7102", "C7103", "C7201", "C7202", "C7700",
    "C7701", "C7702", "C7709", "C7710", "C7745", "C7746",
    "C7755", "C7756", "C7757", "C7790", "C8703", "C8707",
    "C8708", "C8771", "C8772", "C8776",
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def get_db_connection():
    import psycopg2
    from urllib.parse import urlparse
    url = urlparse(DATA_DB_CONN.replace("postgresql+psycopg2://", "postgresql://"))
    return psycopg2.connect(
        host=url.hostname,
        port=url.port or 5432,
        database=url.path.lstrip("/"),
        user=url.username,
        password=url.password,
    )


def ohe_to_index(values):
    """
    Convierte una lista de valores one-hot a su índice (0-based).
    Retorna None si no hay ningún 1.
    """
    for i, v in enumerate(values):
        if int(v) == 1:
            return i
    return None


# ── Task 1: RAW → PROCESSED ───────────────────────────────────────────────────

def raw_to_processed(**context):
    """
    Lee registros no procesados de raw.forest_cover y los transforma:
    - Elimina registros con nulos en features críticas
    - Filtra Slope > 90 (anomalías)
    - Convierte wilderness_area one-hot → string categórico
    - Convierte soil_type one-hot → código categórico
    - Convierte Cover_Type 1-7 → 0-6
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # Construir lista de columnas one-hot para el SELECT
        wa_cols = ", ".join([f"r.wilderness_area_{i}" for i in range(1, 5)])
        st_cols = ", ".join([f"r.soil_type_{i}" for i in range(1, 41)])

        cursor.execute(f"""
            SELECT r.id,
                   r.elevation, r.aspect, r.slope,
                   r.horizontal_distance_to_hydrology,
                   r.vertical_distance_to_hydrology,
                   r.horizontal_distance_to_roadways,
                   r.hillshade_9am, r.hillshade_noon, r.hillshade_3pm,
                   r.horizontal_distance_to_fire_points,
                   {wa_cols},
                   {st_cols},
                   r.cover_type
            FROM raw.forest_cover r
            LEFT JOIN processed.forest_cover p ON p.raw_id = r.id
            WHERE p.id IS NULL
              AND r.cover_type IS NOT NULL
              AND r.elevation IS NOT NULL
              AND r.slope IS NOT NULL
        """)
        raw_records = cursor.fetchall()

        if not raw_records:
            logging.info("No new raw records to process")
            context["ti"].xcom_push(key="processed_count", value=0)
            return

        logging.info(f"Found {len(raw_records)} raw records to process")

        processed_rows = []
        skipped = 0

        for rec in raw_records:
            raw_id = rec[0]
            elevation = rec[1]
            aspect    = rec[2]
            slope     = rec[3]
            hdh       = rec[4]   # horizontal_distance_to_hydrology
            vdh       = rec[5]   # vertical_distance_to_hydrology
            hdr       = rec[6]   # horizontal_distance_to_roadways
            hs9       = rec[7]   # hillshade_9am
            hsn       = rec[8]   # hillshade_noon
            hs3       = rec[9]   # hillshade_3pm
            hdfp      = rec[10]  # horizontal_distance_to_fire_points
            wa_ohe    = rec[11:15]   # wilderness_area_1 a _4
            st_ohe    = rec[15:55]   # soil_type_1 a _40
            cover_type = rec[55]

            # ── Limpieza: eliminar nulos en features críticas ──────────────
            if any(v is None for v in [elevation, aspect, slope, hdh, vdh, hdr,
                                        hs9, hsn, hs3, hdfp]):
                skipped += 1
                continue

            # ── Filtrar anomalías: Slope > 90 grados ──────────────────────
            if float(slope) > 90:
                skipped += 1
                continue

            # ── Convertir wilderness_area: one-hot → categórico ───────────
            wa_idx = ohe_to_index(wa_ohe)
            if wa_idx is None:
                skipped += 1
                continue
            wilderness_area = WILDERNESS_AREA_NAMES[wa_idx]

            # ── Convertir soil_type: one-hot → código categórico ──────────
            st_idx = ohe_to_index(st_ohe)
            if st_idx is None:
                skipped += 1
                continue
            soil_type = SOIL_TYPE_CODES[st_idx]

            # ── Convertir Cover_Type: 1-7 → 0-6 ──────────────────────────
            cover_type_normalized = int(cover_type) - 1

            row = (
                raw_id,
                float(elevation),
                float(aspect),
                float(slope),
                float(hdh),
                float(vdh),
                float(hdr),
                float(hs9),
                float(hsn),
                float(hs3),
                float(hdfp),
                wilderness_area,
                soil_type,
                cover_type_normalized,
            )
            processed_rows.append(row)

        if not processed_rows:
            logging.info(f"All {skipped} records were skipped (nulls or anomalies)")
            context["ti"].xcom_push(key="processed_count", value=0)
            return

        insert_sql = """
            INSERT INTO processed.forest_cover (
                raw_id,
                elevation, aspect, slope,
                horizontal_distance_to_hydrology, vertical_distance_to_hydrology,
                horizontal_distance_to_roadways,
                hillshade_9am, hillshade_noon, hillshade_3pm,
                horizontal_distance_to_fire_points,
                wilderness_area, soil_type,
                cover_type
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """

        cursor.executemany(insert_sql, processed_rows)
        conn.commit()
        logging.info(f"Inserted {len(processed_rows)} records into processed.forest_cover "
                     f"(skipped {skipped})")
        context["ti"].xcom_push(key="processed_count", value=len(processed_rows))

    except Exception as e:
        conn.rollback()
        logging.error(f"Error in raw_to_processed: {e}")
        raise
    finally:
        cursor.close()
        conn.close()


# ── Task 2: PROCESSED → READY ─────────────────────────────────────────────────

def processed_to_ready(**context):
    """
    Lee registros de processed que no están en ready.
    Re-aplica one-hot encoding de wilderness_area y soil_type,
    hace split 70/15/15 y guarda features como array.
    """
    import random
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            SELECT p.id,
                   p.elevation, p.aspect, p.slope,
                   p.horizontal_distance_to_hydrology,
                   p.vertical_distance_to_hydrology,
                   p.horizontal_distance_to_roadways,
                   p.hillshade_9am, p.hillshade_noon, p.hillshade_3pm,
                   p.horizontal_distance_to_fire_points,
                   p.wilderness_area, p.soil_type,
                   p.cover_type
            FROM processed.forest_cover p
            LEFT JOIN ready.forest_cover r ON r.processed_id = p.id
            WHERE r.id IS NULL
        """)
        records = cursor.fetchall()

        if not records:
            logging.info("No new processed records for ready stage")
            return

        logging.info(f"Preparing {len(records)} records for training")

        # Split 70% train / 15% val / 15% test
        random.shuffle(records)
        n = len(records)
        n_train = int(n * 0.70)
        n_val   = int(n * 0.15)

        splits = (
            ["train"] * n_train +
            ["val"]   * n_val +
            ["test"]  * (n - n_train - n_val)
        )

        ready_rows = []
        for i, rec in enumerate(records):
            proc_id    = rec[0]
            numerics   = [float(v) for v in rec[1:11]]   # 10 features numéricas
            wa_str     = rec[11]                          # "Rawah", "Neota", etc.
            st_str     = rec[12]                          # "C7745", etc.
            cover_type = int(rec[13])

            # Re-aplicar one-hot wilderness_area (4 columnas)
            wa_ohe = [1 if wa_str == name else 0 for name in WILDERNESS_AREA_NAMES]

            # Re-aplicar one-hot soil_type (40 columnas)
            st_ohe = [1 if st_str == code else 0 for code in SOIL_TYPE_CODES]

            features = numerics + wa_ohe + st_ohe  # 10 + 4 + 40 = 54 features

            ready_rows.append((proc_id, splits[i], features, cover_type))

        cursor.executemany(
            "INSERT INTO ready.forest_cover (processed_id, split_set, features, cover_type) "
            "VALUES (%s, %s, %s, %s)",
            ready_rows,
        )
        conn.commit()
        logging.info(f"Inserted {len(ready_rows)} records into ready.forest_cover")

    except Exception as e:
        conn.rollback()
        logging.error(f"Error in processed_to_ready: {e}")
        raise
    finally:
        cursor.close()
        conn.close()


# ── DAG Definition ─────────────────────────────────────────────────────────────

with DAG(
    dag_id="2_data_processing",
    description="Transform data from raw → processed → ready for training",
    default_args=default_args,
    start_date=days_ago(1),
    schedule_interval="*/10 * * * *",  # Cada 10 minutos
    catchup=False,
    max_active_runs=1,
    tags=["data-processing", "mlops"],
) as dag:

    task_raw_to_processed = PythonOperator(
        task_id="raw_to_processed",
        python_callable=raw_to_processed,
    )

    task_processed_to_ready = PythonOperator(
        task_id="processed_to_ready",
        python_callable=processed_to_ready,
    )

    task_raw_to_processed >> task_processed_to_ready