"""
DAG 3: model_training
======================
Objetivo: Entrenar un modelo de clasificación con los datos
de ready.forest_cover y guardarlo en MinIO.

- Evalúa Random Forest y Gradient Boosting
- Escala solo las 10 features numéricas (no las binarias one-hot)
- Guarda el mejor modelo en MinIO
- Registra métricas en public.model_registry
- Cover_Type en rango 0-6
"""

from airflow import DAG
from airflow.operators.python import PythonOperator, ShortCircuitOperator
from airflow.utils.dates import days_ago
from datetime import timedelta
import json
import logging
import os

DATA_DB_CONN   = os.getenv("DATA_DB_CONN",   "postgresql+psycopg2://mlops:mlops123@postgresql-data/mlops_db")
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "minio:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minioadmin123")
MINIO_BUCKET   = os.getenv("MINIO_BUCKET",   "models")

MIN_TRAINING_SAMPLES = 100

default_args = {
    "owner": "mlops-team",
    "depends_on_past": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
    "email_on_failure": False,
}


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


# ── Task 1: Verificar datos suficientes ───────────────────────────────────────

def check_data_availability(**context):
    """
    Verifica si hay suficientes datos para entrenar.
    Retorna True para continuar o False para saltar las tareas siguientes
    sin marcar el DAG como fallido (ShortCircuit).
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT COUNT(*) FROM ready.forest_cover WHERE split_set = 'train'")
        train_count = cursor.fetchone()[0]
        logging.info(f"Training samples available: {train_count}")

        if train_count < MIN_TRAINING_SAMPLES:
            logging.info(
                f"Not enough data yet ({train_count}/{MIN_TRAINING_SAMPLES}). "
                f"Skipping training — will retry on next scheduled run."
            )
            return False

        context["ti"].xcom_push(key="train_count", value=train_count)
        return True
    finally:
        cursor.close()
        conn.close()


# ── Task 2: Entrenar modelo ───────────────────────────────────────────────────

def train_model(**context):
    """
    Carga datos de ready, entrena Random Forest y Gradient Boosting,
    selecciona el mejor por validation accuracy y lo guarda localmente.

    Escalado selectivo:
      - Solo las primeras 10 features numéricas se escalan con StandardScaler
      - Las 44 features binarias (one-hot) se mantienen sin escalar
    """
    import numpy as np
    import joblib
    from datetime import datetime
    from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
    from sklearn.metrics import accuracy_score, f1_score
    from sklearn.preprocessing import StandardScaler

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # ── Cargar splits ─────────────────────────────────────────────────────
        cursor.execute("SELECT features, cover_type FROM ready.forest_cover WHERE split_set = 'train'")
        train_data = cursor.fetchall()

        cursor.execute("SELECT features, cover_type FROM ready.forest_cover WHERE split_set = 'val'")
        val_data = cursor.fetchall()

        cursor.execute("SELECT features, cover_type FROM ready.forest_cover WHERE split_set = 'test'")
        test_data = cursor.fetchall()

        X_train = np.array([row[0] for row in train_data])
        y_train = np.array([row[1] for row in train_data])

        X_val  = np.array([row[0] for row in val_data])  if val_data  else X_train[:10]
        y_val  = np.array([row[1] for row in val_data])  if val_data  else y_train[:10]

        X_test = np.array([row[0] for row in test_data]) if test_data else X_train[:10]
        y_test = np.array([row[1] for row in test_data]) if test_data else y_train[:10]

        logging.info(f"Train: {X_train.shape}, Val: {X_val.shape}, Test: {X_test.shape}")

        # ── Escalado selectivo: solo las 10 features numéricas ────────────────
        # Índices 0-9  → numéricas (elevation, aspect, slope, ...)
        # Índices 10-53 → binarias one-hot (wilderness_area_*, soil_type_*)
        NUM_NUMERIC = 10

        scaler = StandardScaler()
        X_train_s = X_train.copy()
        X_val_s   = X_val.copy()
        X_test_s  = X_test.copy()

        X_train_s[:, :NUM_NUMERIC] = scaler.fit_transform(X_train[:, :NUM_NUMERIC])
        X_val_s[:,   :NUM_NUMERIC] = scaler.transform(X_val[:,   :NUM_NUMERIC])
        X_test_s[:,  :NUM_NUMERIC] = scaler.transform(X_test[:,  :NUM_NUMERIC])

        # ── Candidatos de modelos ─────────────────────────────────────────────
        candidates = {
            "random_forest": RandomForestClassifier(
                n_estimators=200,
                max_depth=20,
                min_samples_split=5,
                n_jobs=-1,
                random_state=42,
            ),
            "gradient_boosting": GradientBoostingClassifier(
                n_estimators=100,
                max_depth=5,
                learning_rate=0.1,
                random_state=42,
            ),
        }

        best_model    = None
        best_name     = None
        best_val_acc  = -1
        best_metrics  = {}

        for name, model in candidates.items():
            logging.info(f"Training {name}...")
            model.fit(X_train_s, y_train)

            val_pred = model.predict(X_val_s)
            val_acc  = accuracy_score(y_val, val_pred)
            val_f1   = f1_score(y_val, val_pred, average="weighted", zero_division=0)

            logging.info(f"  {name}: val_acc={val_acc:.4f}, val_f1={val_f1:.4f}")

            if val_acc > best_val_acc:
                best_val_acc = val_acc
                best_model   = model
                best_name    = name
                best_metrics = {
                    "val_accuracy": val_acc,
                    "val_f1":       val_f1,
                }

        # ── Evaluar en test ───────────────────────────────────────────────────
        test_pred = best_model.predict(X_test_s)
        test_acc  = accuracy_score(y_test, test_pred)
        test_f1   = f1_score(y_test, test_pred, average="weighted", zero_division=0)
        best_metrics["test_accuracy"] = test_acc
        best_metrics["test_f1"]       = test_f1

        logging.info(f"Best model: {best_name} | test_acc={test_acc:.4f}, test_f1={test_f1:.4f}")

        # ── Guardar modelo + scaler ───────────────────────────────────────────
        model_package = {
            "model":         best_model,
            "scaler":        scaler,
            "algorithm":     best_name,
            "metrics":       best_metrics,
            "train_samples": len(X_train),
            "trained_at":    datetime.now().isoformat(),
            "feature_count": X_train.shape[1],
            "num_numeric":   NUM_NUMERIC,   # para que la API sepa qué escalar
        }

        model_path = "/tmp/model_package.joblib"
        joblib.dump(model_package, model_path, compress=3)

        context["ti"].xcom_push(key="model_path",     value=model_path)
        context["ti"].xcom_push(key="algorithm",      value=best_name)
        context["ti"].xcom_push(key="metrics",        value=best_metrics)
        context["ti"].xcom_push(key="train_samples",  value=int(len(X_train)))

        logging.info("Model saved to /tmp/model_package.joblib")

    finally:
        cursor.close()
        conn.close()


# ── Task 3: Subir modelo a MinIO ──────────────────────────────────────────────

def upload_model_to_minio(**context):
    """
    Sube el modelo entrenado a MinIO y registra en public.model_registry.
    Marca el nuevo modelo como activo y desactiva el anterior.
    """
    from datetime import datetime
    from minio import Minio

    model_path   = context["ti"].xcom_pull(key="model_path",    task_ids="train_model")
    algorithm    = context["ti"].xcom_pull(key="algorithm",     task_ids="train_model")
    metrics      = context["ti"].xcom_pull(key="metrics",       task_ids="train_model")
    train_samples = context["ti"].xcom_pull(key="train_samples", task_ids="train_model")

    timestamp          = datetime.now().strftime("%Y%m%d_%H%M%S")
    model_version      = f"v_{timestamp}"
    minio_object_name  = f"models/{algorithm}/{model_version}/model_package.joblib"
    full_minio_path    = f"{MINIO_BUCKET}/{minio_object_name}"

    # ── Subir a MinIO ─────────────────────────────────────────────────────────
    client = Minio(
        MINIO_ENDPOINT,
        access_key=MINIO_ACCESS_KEY,
        secret_key=MINIO_SECRET_KEY,
        secure=False,
    )

    if not client.bucket_exists(MINIO_BUCKET):
        client.make_bucket(MINIO_BUCKET)

    client.fput_object(
        MINIO_BUCKET,
        minio_object_name,
        model_path,
        content_type="application/octet-stream",
    )
    logging.info(f"Model uploaded to MinIO: {full_minio_path}")

    # ── Registrar en PostgreSQL ───────────────────────────────────────────────
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE public.model_registry SET is_active = FALSE")

        cursor.execute("""
            INSERT INTO public.model_registry (
                model_name, model_version, minio_path, algorithm,
                accuracy, f1_score, train_samples, is_active, hyperparameters
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (
            f"forest_cover_{algorithm}",
            model_version,
            full_minio_path,
            algorithm,
            metrics.get("test_accuracy"),
            metrics.get("test_f1"),
            train_samples,
            True,
            json.dumps(metrics),
        ))
        model_id = cursor.fetchone()[0]
        conn.commit()
        logging.info(f"Model registered in DB with id={model_id}")
        context["ti"].xcom_push(key="minio_path", value=full_minio_path)

    except Exception as e:
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()


# ── DAG Definition ─────────────────────────────────────────────────────────────

with DAG(
    dag_id="3_model_training",
    description="Train classification model and upload to MinIO",
    default_args=default_args,
    start_date=days_ago(1),
    schedule_interval="0 */2 * * *",  # Cada 2 horas
    catchup=False,
    max_active_runs=1,
    tags=["training", "mlops"],
) as dag:

    task_check = ShortCircuitOperator(
        task_id="check_data_availability",
        python_callable=check_data_availability,
    )

    task_train = PythonOperator(
        task_id="train_model",
        python_callable=train_model,
    )

    task_upload = PythonOperator(
        task_id="upload_to_minio",
        python_callable=upload_model_to_minio,
    )

    task_check >> task_train >> task_upload