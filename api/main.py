"""
API - FastAPI
========================
Realiza predicciones usando el modelo más reciente almacenado en MinIO.

"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any, Literal
import os
import io
import logging
import numpy as np
from datetime import datetime

# ── Configuración ─────────────────────────────────────────────────────────────
MINIO_ENDPOINT   = os.getenv("MINIO_ENDPOINT",   "minio:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minioadmin123")
MINIO_BUCKET     = os.getenv("MINIO_BUCKET",     "models")
DATA_DB_CONN     = os.getenv("DATA_DB_CONN",     "postgresql+psycopg2://mlops:mlops123@postgresql-data/mlops_db")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── Dominios (deben coincidir exactamente con DAG 2 y DAG 3) ─────────────────
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

# Cover_Type 0-6 (original 1-7 menos 1, aplicado en DAG 2)
COVER_TYPE_LABELS = {
    0: "Spruce/Fir",
    1: "Lodgepole Pine",
    2: "Ponderosa Pine",
    3: "Cottonwood/Willow",
    4: "Aspen",
    5: "Douglas-fir",
    6: "Krummholz",
}

NUM_NUMERIC = 10  # Primeras 10 features son numéricas, el resto binarias

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="Forest Cover Type - Inference API",
    description="""
    API de inferencia para el modelo de clasificación de tipo de cobertura forestal.

    ## Endpoints principales
    - `POST /predict` - Predice el tipo de cobertura para una muestra
    - `POST /predict/batch` - Predice para múltiples muestras
    - `GET /model/info` - Información del modelo activo
    - `POST /model/reload` - Recarga el modelo desde MinIO
    - `GET /cover-types` - Mapa de tipos de cobertura
    - `GET /wilderness-areas` - Valores válidos de wilderness_area
    - `GET /soil-types` - Valores válidos de soil_type
    """,
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Estado global del modelo ──────────────────────────────────────────────────
model_state = {
    "model":       None,
    "scaler":      None,
    "algorithm":   None,
    "metrics":     None,
    "minio_path":  None,
    "loaded_at":   None,
    "num_numeric": NUM_NUMERIC,
}


# ── Schemas ───────────────────────────────────────────────────────────────────

class ForestSample(BaseModel):
    elevation: float = Field(..., description="Elevation in meters", example=2596.0)
    aspect: float = Field(..., description="Aspect in degrees azimuth", example=51.0)
    slope: float = Field(..., description="Slope in degrees (max 90)", ge=0, le=90, example=3.0)
    horizontal_distance_to_hydrology: float = Field(..., example=258.0)
    vertical_distance_to_hydrology: float = Field(..., example=0.0)
    horizontal_distance_to_roadways: float = Field(..., example=510.0)
    hillshade_9am: float = Field(..., ge=0, le=255, example=221.0)
    hillshade_noon: float = Field(..., ge=0, le=255, example=232.0)
    hillshade_3pm: float = Field(..., ge=0, le=255, example=148.0)
    horizontal_distance_to_fire_points: float = Field(..., example=6279.0)
    wilderness_area: str = Field(
        ...,
        description="Wilderness area name: Rawah, Neota, Commanche or Cache",
        example="Rawah"
    )
    soil_type: str = Field(
        ...,
        description="Soil type code (e.g. C7745, C2703)",
        example="C7745"
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "elevation": 2596.0,
                "aspect": 51.0,
                "slope": 3.0,
                "horizontal_distance_to_hydrology": 258.0,
                "vertical_distance_to_hydrology": 0.0,
                "horizontal_distance_to_roadways": 510.0,
                "hillshade_9am": 221.0,
                "hillshade_noon": 232.0,
                "hillshade_3pm": 148.0,
                "horizontal_distance_to_fire_points": 6279.0,
                "wilderness_area": "Rawah",
                "soil_type": "C7745",
            }
        }
    }


class PredictionResponse(BaseModel):
    cover_type: int
    cover_type_label: str
    probability: Optional[float] = None
    probabilities: Optional[Dict[str, float]] = None
    model_algorithm: str
    predicted_at: str


class BatchPredictionRequest(BaseModel):
    samples: List[ForestSample]


class BatchPredictionResponse(BaseModel):
    predictions: List[PredictionResponse]
    total: int


class ModelInfo(BaseModel):
    algorithm: str
    minio_path: str
    metrics: Dict[str, Any]
    loaded_at: str
    status: str


# ── Funciones auxiliares ──────────────────────────────────────────────────────

def load_model_from_minio():
    """Carga el modelo activo desde MinIO consultando public.model_registry."""
    from minio import Minio
    import joblib
    import psycopg2
    from urllib.parse import urlparse

    url = urlparse(DATA_DB_CONN.replace("postgresql+psycopg2://", "postgresql://"))
    conn = psycopg2.connect(
        host=url.hostname,
        port=url.port or 5432,
        database=url.path.lstrip("/"),
        user=url.username,
        password=url.password,
    )
    cursor = conn.cursor()

    try:
        cursor.execute("""
            SELECT minio_path, algorithm, accuracy, f1_score, hyperparameters
            FROM public.model_registry
            WHERE is_active = TRUE
            ORDER BY trained_at DESC
            LIMIT 1
        """)
        row = cursor.fetchone()
        if not row:
            raise ValueError("No active model found in registry")

        minio_full_path, algorithm, accuracy, f1, hyperparams = row
        parts = minio_full_path.split("/", 1)
        bucket      = parts[0]
        object_name = parts[1]

    finally:
        cursor.close()
        conn.close()

    client = Minio(
        MINIO_ENDPOINT,
        access_key=MINIO_ACCESS_KEY,
        secret_key=MINIO_SECRET_KEY,
        secure=False,
    )

    response    = client.get_object(bucket, object_name)
    model_bytes = response.read()
    package     = joblib.load(io.BytesIO(model_bytes))

    model_state["model"]       = package["model"]
    model_state["scaler"]      = package["scaler"]
    model_state["algorithm"]   = package.get("algorithm", algorithm)
    model_state["metrics"]     = package.get("metrics", {"accuracy": accuracy, "f1": f1})
    model_state["minio_path"]  = minio_full_path
    model_state["loaded_at"]   = datetime.now().isoformat()
    model_state["num_numeric"] = package.get("num_numeric", NUM_NUMERIC)

    logger.info(f"Model loaded: {algorithm} from {minio_full_path}")


def sample_to_features(sample: ForestSample) -> np.ndarray:
    """
    Convierte un ForestSample a vector de 54 features:
    - [0-9]  : 10 features numéricas
    - [10-13]: wilderness_area one-hot (4 columnas)
    - [14-53]: soil_type one-hot (40 columnas)
    """
    # Validar wilderness_area
    if sample.wilderness_area not in WILDERNESS_AREA_NAMES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid wilderness_area '{sample.wilderness_area}'. "
                   f"Valid values: {WILDERNESS_AREA_NAMES}"
        )

    # Validar soil_type
    if sample.soil_type not in SOIL_TYPE_CODES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid soil_type '{sample.soil_type}'. "
                   f"Valid values: {SOIL_TYPE_CODES}"
        )

    numeric = [
        sample.elevation,
        sample.aspect,
        sample.slope,
        sample.horizontal_distance_to_hydrology,
        sample.vertical_distance_to_hydrology,
        sample.horizontal_distance_to_roadways,
        sample.hillshade_9am,
        sample.hillshade_noon,
        sample.hillshade_3pm,
        sample.horizontal_distance_to_fire_points,
    ]

    wa_ohe = [1 if sample.wilderness_area == name else 0 for name in WILDERNESS_AREA_NAMES]
    st_ohe = [1 if sample.soil_type == code else 0 for code in SOIL_TYPE_CODES]

    return np.array(numeric + wa_ohe + st_ohe, dtype=float)


def predict_single(sample: ForestSample) -> PredictionResponse:
    if model_state["model"] is None:
        raise HTTPException(status_code=503, detail="Model not loaded. Call /model/reload first.")

    features    = sample_to_features(sample).reshape(1, -1)
    num_numeric = model_state["num_numeric"]

    # Escalado selectivo: solo las features numéricas
    features_scaled = features.copy()
    features_scaled[:, :num_numeric] = model_state["scaler"].transform(
        features[:, :num_numeric]
    )

    prediction = int(model_state["model"].predict(features_scaled)[0])
    label      = COVER_TYPE_LABELS.get(prediction, f"Unknown ({prediction})")

    probabilities = None
    probability   = None
    if hasattr(model_state["model"], "predict_proba"):
        proba   = model_state["model"].predict_proba(features_scaled)[0]
        classes = model_state["model"].classes_
        probabilities = {
            COVER_TYPE_LABELS.get(int(c), str(c)): round(float(p), 4)
            for c, p in zip(classes, proba)
        }
        probability = round(float(proba[list(classes).index(prediction)]), 4)

    return PredictionResponse(
        cover_type=prediction,
        cover_type_label=label,
        probability=probability,
        probabilities=probabilities,
        model_algorithm=model_state["algorithm"] or "unknown",
        predicted_at=datetime.now().isoformat(),
    )


# ── Eventos de inicio ─────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup_event():
    try:
        load_model_from_minio()
        logger.info("Model loaded successfully at startup")
    except Exception as e:
        logger.warning(f"Could not load model at startup: {e}. Use /model/reload when ready.")


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/", tags=["Health"])
def root():
    return {
        "service": "Forest Cover Type Inference API",
        "status": "running",
        "model_loaded": model_state["model"] is not None,
        "docs": "/docs",
    }


@app.get("/health", tags=["Health"])
def health():
    return {
        "status": "healthy",
        "model_loaded": model_state["model"] is not None,
        "timestamp": datetime.now().isoformat(),
    }


@app.get("/model/info", response_model=ModelInfo, tags=["Model"])
def get_model_info():
    if model_state["model"] is None:
        raise HTTPException(status_code=404, detail="No model loaded")
    return ModelInfo(
        algorithm=model_state["algorithm"],
        minio_path=model_state["minio_path"],
        metrics=model_state["metrics"] or {},
        loaded_at=model_state["loaded_at"],
        status="active",
    )


@app.post("/model/reload", tags=["Model"])
def reload_model():
    """Recarga el modelo activo desde MinIO."""
    try:
        load_model_from_minio()
        return {
            "status": "success",
            "algorithm": model_state["algorithm"],
            "loaded_at": model_state["loaded_at"],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/predict", response_model=PredictionResponse, tags=["Inference"])
def predict(sample: ForestSample):
    """
    Predice el tipo de cobertura forestal para una muestra.
    Retorna el tipo (0-6) con su etiqueta y probabilidades por clase.
    """
    try:
        return predict_single(sample)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Prediction error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/predict/batch", response_model=BatchPredictionResponse, tags=["Inference"])
def predict_batch(request: BatchPredictionRequest):
    """Predice para múltiples muestras. Máximo 1000 por petición."""
    if len(request.samples) > 1000:
        raise HTTPException(status_code=400, detail="Maximum 1000 samples per batch")
    try:
        predictions = [predict_single(sample) for sample in request.samples]
        return BatchPredictionResponse(predictions=predictions, total=len(predictions))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Batch prediction error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/cover-types", tags=["Reference"])
def get_cover_types():
    """Retorna el mapa de tipos de cobertura forestal (0-6)."""
    return {"cover_types": COVER_TYPE_LABELS}


@app.get("/wilderness-areas", tags=["Reference"])
def get_wilderness_areas():
    """Retorna los valores válidos de wilderness_area."""
    return {"wilderness_areas": WILDERNESS_AREA_NAMES}


@app.get("/soil-types", tags=["Reference"])
def get_soil_types():
    """Retorna los valores válidos de soil_type."""
    return {"soil_types": SOIL_TYPE_CODES}