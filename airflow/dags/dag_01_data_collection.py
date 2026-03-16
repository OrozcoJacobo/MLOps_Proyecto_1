"""
DAG 1: data_collection
=======================
Responsabilidad: Hacer UNA petición a la Data API y guardar los datos
en el esquema RAW de PostgreSQL.

Restricción del proyecto: Una sola petición por ejecución del DAG.
Programado cada 5 minutos para capturar todos los batches.
"""

from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.utils.dates import days_ago
from datetime import datetime, timedelta
import requests
import json
import logging
import os

# ── Configuración ─────────────────────────────────────────────────────────────
DATA_API_URL = os.getenv("DATA_API_URL", "http://host.docker.internal:80")
GROUP_NUMBER = int(os.getenv("GROUP_NUMBER", "2"))
DATA_DB_CONN = os.getenv("DATA_DB_CONN", "postgresql+psycopg2://mlops:mlops123@postgres-data/mlops_db")

default_args = {
    "owner": "mlops-team",
    "depends_on_past": False,
    "retries": 3,
    "retry_delay": timedelta(minutes=1),
    "email_on_failure": False,
}

# ── Funciones ─────────────────────────────────────────────────────────────────

def fetch_data_from_api(**context):
    """
    Hace UNA petición a la Data API y guarda la respuesta en XCom.
    """
    url = f"{DATA_API_URL}/data"
    params = {"group_number": GROUP_NUMBER}

    logging.info(f"Fetching data from {url} with group_number={GROUP_NUMBER}")

    try:
        response = requests.get(url, params=params, timeout=30, headers={"accept": "application/json"})

        # La API devuelve 400 cuando ya se recolectó la muestra mínima del batch actual
        if response.status_code == 400:
            message = response.json().get("detail", "")
            logging.info(f"API response 400: {message} — skipping this run.")
            context["ti"].xcom_push(key="raw_data", value=None)
            return "No data available for this batch — skipping."

        response.raise_for_status()
        data = response.json()
        logging.info(f"Received {len(data) if isinstance(data, list) else 1} records")
        context["ti"].xcom_push(key="raw_data", value=data)
        context["ti"].xcom_push(key="fetch_timestamp", value=datetime.now().isoformat())
        return f"Fetched {len(data) if isinstance(data, list) else 1} records"
    except requests.exceptions.RequestException as e:
        logging.error(f"Error fetching data: {e}")
        raise


def save_to_raw_db(**context):
    """
    Toma los datos del XCom y los guarda en raw.forest_cover de PostgreSQL.
    """
    import psycopg2
    from psycopg2.extras import Json, execute_values
    from urllib.parse import urlparse

    raw_data = context["ti"].xcom_pull(key="raw_data", task_ids="fetch_data")
    fetch_timestamp = context["ti"].xcom_pull(key="fetch_timestamp", task_ids="fetch_data")

    if raw_data is None:
        logging.info("No data to save — batch was already collected. Skipping.")
        return "Skipped — no data."

    # La API devuelve: {"group_number": X, "batch_number": Y, "data": [[val0, val1, ...], ...]}
    # Formato de cada fila (55 columnas):
    # [0-9]   : elevation, aspect, slope, h_dist_hydrology, v_dist_hydrology,
    #            h_dist_roadways, hillshade_9am, hillshade_noon, hillshade_3pm, h_dist_fire
    # [10-13] : wilderness_area_1 a wilderness_area_4 (one-hot)
    # [14-53] : soil_type_1 a soil_type_40 (one-hot)
    # [54]    : cover_type

    if isinstance(raw_data, dict):
        batch_number = raw_data.get("batch_number")
        records = raw_data.get("data", [])
    else:
        batch_number = None
        records = raw_data

    logging.info(f"Saving {len(records)} records to raw.forest_cover")

    # Parsear URL de conexión
    url = urlparse(DATA_DB_CONN.replace("postgresql+psycopg2://", "postgresql://"))
    conn = psycopg2.connect(
        host=url.hostname,
        port=url.port or 5432,
        database=url.path.lstrip("/"),
        user=url.username,
        password=url.password,
    )

    try:
        cursor = conn.cursor()

        wa_cols = ", ".join([f"wilderness_area_{i}" for i in range(1, 5)])
        st_cols = ", ".join([f"soil_type_{i}" for i in range(1, 41)])

        insert_query = f"""
            INSERT INTO raw.forest_cover (
                batch_number, group_number, fetched_at,
                elevation, aspect, slope,
                horizontal_distance_to_hydrology, vertical_distance_to_hydrology,
                horizontal_distance_to_roadways,
                hillshade_9am, hillshade_noon, hillshade_3pm,
                horizontal_distance_to_fire_points,
                {wa_cols},
                {st_cols},
                cover_type, raw_json
            ) VALUES %s
        """

        rows = []
        for record in records:
            r = [str(v) for v in record]  # normalizar a string por si acaso
            row = (
                batch_number,
                GROUP_NUMBER,
                fetch_timestamp,
                _safe_float(r[0]),   # elevation
                _safe_float(r[1]),   # aspect
                _safe_float(r[2]),   # slope
                _safe_float(r[3]),   # horizontal_distance_to_hydrology
                _safe_float(r[4]),   # vertical_distance_to_hydrology
                _safe_float(r[5]),   # horizontal_distance_to_roadways
                _safe_float(r[6]),   # hillshade_9am
                _safe_float(r[7]),   # hillshade_noon
                _safe_float(r[8]),   # hillshade_3pm
                _safe_float(r[9]),   # horizontal_distance_to_fire_points
                _safe_int(r[10]),    # wilderness_area_1
                _safe_int(r[11]),    # wilderness_area_2
                _safe_int(r[12]),    # wilderness_area_3
                _safe_int(r[13]),    # wilderness_area_4
                *[_safe_int(r[i]) for i in range(14, 54)],  # soil_type_1 a soil_type_40
                _safe_int(r[54]),    # cover_type
                Json(record),
            )
            rows.append(row)

        execute_values(cursor, insert_query, rows)
        conn.commit()
        logging.info(f"Successfully saved {len(rows)} records to raw.forest_cover")

    except Exception as e:
        conn.rollback()
        logging.error(f"Error saving to database: {e}")
        raise
    finally:
        cursor.close()
        conn.close()


def _safe_float(value):
    try:
        return float(value) if value is not None else None
    except (ValueError, TypeError):
        return None


def _safe_int(value):
    try:
        return int(value) if value is not None else None
    except (ValueError, TypeError):
        return None


# ── DAG Definition ────────────────────────────────────────────────────────────

with DAG(
    dag_id="1_data_collection",
    description="Collect one batch of forest cover data from the external API",
    default_args=default_args,
    start_date=days_ago(1),
    schedule_interval="*/5 * * * *",  # Cada 5 minutos
    catchup=False,
    max_active_runs=1,
    tags=["data-ingestion", "mlops"],
) as dag:

    fetch_task = PythonOperator(
        task_id="fetch_data",
        python_callable=fetch_data_from_api,
        doc_md="""
        ### Fetch Data
        Makes a single GET request to `http://host.docker.internal:80/data?group_number=8`
        and stores the result in XCom.
        """,
    )

    save_task = PythonOperator(
        task_id="save_to_raw",
        python_callable=save_to_raw_db,
        doc_md="""
        ### Save to RAW
        Takes data from XCom and inserts it into `raw.forest_cover` table in PostgreSQL.
        """,
    )

    fetch_task >> save_task