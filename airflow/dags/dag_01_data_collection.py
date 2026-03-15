"""
DAG 1: data_collection
=======================
Responsabilidad: Hacer UNA petición a la Data API y guardar los datos
en el esquema RAW de PostgreSQL.

Una sola petición por ejecución del DAG.
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
GROUP_NUMBER = int(os.getenv("GROUP_NUMBER", "8"))
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
    Hace una petición a la Data API y guarda la respuesta en XCom.
    """
    url = f"{DATA_API_URL}/data"
    params = {"group_number": GROUP_NUMBER}

    logging.info(f"Fetching data from {url} with group_number={GROUP_NUMBER}")

    try:
        response = requests.get(url, params=params, timeout=30, headers={"accept": "application/json"})
        response.raise_for_status()
        data = response.json()
        logging.info(f"Received {len(data) if isinstance(data, list) else 1} records")
        # Guardar en XCom para siguiente tarea
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
        raise ValueError("No data received from XCom")

    # Normalizar: si es dict (una sola fila), convertir a lista
    if isinstance(raw_data, dict):
        records = [raw_data]
    elif isinstance(raw_data, list):
        records = raw_data
    else:
        raise ValueError(f"Unexpected data format: {type(raw_data)}")

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

        # Mapeo flexible de columnas — la API puede devolver nombres distintos
        insert_query = """
            INSERT INTO raw.forest_cover (
                batch_number, group_number, fetched_at,
                elevation, aspect, slope,
                horizontal_distance_to_hydrology, vertical_distance_to_hydrology,
                horizontal_distance_to_roadways,
                hillshade_9am, hillshade_noon, hillshade_3pm,
                horizontal_distance_to_fire_points,
                wilderness_area, soil_type, cover_type, raw_json
            ) VALUES %s
        """

        rows = []
        for record in records:
            # Normalizar nombres de columnas (minúsculas, sin espacios)
            r = {k.lower().replace(" ", "_"): v for k, v in record.items()}

            row = (
                r.get("batch_number", r.get("batch", None)),
                GROUP_NUMBER,
                fetch_timestamp,
                _safe_float(r.get("elevation")),
                _safe_float(r.get("aspect")),
                _safe_float(r.get("slope")),
                _safe_float(r.get("horizontal_distance_to_hydrology")),
                _safe_float(r.get("vertical_distance_to_hydrology")),
                _safe_float(r.get("horizontal_distance_to_roadways")),
                _safe_float(r.get("hillshade_9am")),
                _safe_float(r.get("hillshade_noon")),
                _safe_float(r.get("hillshade_3pm")),
                _safe_float(r.get("horizontal_distance_to_fire_points")),
                str(r.get("wilderness_area", "")),
                _safe_int(r.get("soil_type")),
                _safe_int(r.get("cover_type")),
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
