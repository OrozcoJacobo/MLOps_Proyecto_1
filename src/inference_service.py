from io import BytesIO
from typing import Any

import joblib
import pandas as pd
from fastapi import FastAPI, HTTPException
from minio import Minio
from pydantic import BaseModel

from src.config import minio_config


app = FastAPI(title="Inference API", version="1.0.0")


minio_client = Minio(
    minio_config.endpoint,
    access_key=minio_config.access_key,
    secret_key=minio_config.secret_key,
    secure=minio_config.secure,
)


active_model_name: str | None = None
active_model: Any | None = None


class PredictionInput(BaseModel):
    """
    Input schema required to generate a prediction.

    Attributes
    ----------
    elevation : float
        Elevation in meters.
    aspect : float
        Aspect in degrees azimuth.
    slope : float
        Slope in degrees.
    horizontal_distance_to_hydrology : float
        Horizontal distance to nearest surface water feature.
    vertical_distance_to_hydrology : float
        Vertical distance to nearest surface water feature.
    horizontal_distance_to_roadways : float
        Horizontal distance to nearest roadway.
    hillshade_9am : float
        Hillshade index at 9am.
    hillshade_noon : float
        Hillshade index at noon.
    hillshade_3pm : float
        Hillshade index at 3pm.
    horizontal_distance_to_fire_points : float
        Horizontal distance to nearest fire ignition point.
    wilderness_area : str
        Wilderness area category.
    soil_type : str
        Soil type category.
    """

    elevation: float
    aspect: float
    slope: float
    horizontal_distance_to_hydrology: float
    vertical_distance_to_hydrology: float
    horizontal_distance_to_roadways: float
    hillshade_9am: float
    hillshade_noon: float
    hillshade_3pm: float
    horizontal_distance_to_fire_points: float
    wilderness_area: str
    soil_type: str


class ModelSelectionInput(BaseModel):
    """
    Input schema used to select the active model.

    Attributes
    ----------
    model_name : str
        Name of the model to load from MinIO, without the `.joblib` extension.
    """

    model_name: str


def list_available_models() -> list[str]:
    """
    Return the list of available models stored in MinIO.

    Returns
    -------
    list[str]
        Sorted list of model names without the `.joblib` extension.
    """
    objects = minio_client.list_objects(minio_config.bucket_name)
    models = []

    for obj in objects:
        if obj.object_name.endswith(".joblib"):
            models.append(obj.object_name.replace(".joblib", ""))

    return sorted(models)


def download_model_from_minio(model_name: str) -> Any:
    """
    Download and deserialize a model artifact from MinIO.

    Parameters
    ----------
    model_name : str
        Name of the model without the `.joblib` extension.

    Returns
    -------
    Any
        Deserialized model object loaded with joblib.
    """
    object_name = f"{model_name}.joblib"
    response = None

    try:
        response = minio_client.get_object(minio_config.bucket_name, object_name)
        model_bytes = response.read()
        model = joblib.load(BytesIO(model_bytes))
        return model
    finally:
        if response is not None:
            response.close()
            response.release_conn()


@app.get("/models")
def get_models() -> dict:
    """
    List the models currently available in MinIO.

    Returns
    -------
    dict
        Dictionary containing the list of available model names.
    """
    models = list_available_models()
    return {"models": models}


@app.post("/select-model")
def select_model(payload: ModelSelectionInput) -> dict:
    """
    Select one model from MinIO and keep it in memory.

    Parameters
    ----------
    payload : ModelSelectionInput
        Request body containing the model name to activate.

    Returns
    -------
    dict
        Confirmation message and the active model name.

    Raises
    ------
    HTTPException
        If the requested model does not exist in MinIO.
    """
    global active_model_name, active_model

    available_models = list_available_models()

    if payload.model_name not in available_models:
        raise HTTPException(
            status_code=404,
            detail=f"Model '{payload.model_name}' not found in MinIO.",
        )

    active_model = download_model_from_minio(payload.model_name)
    active_model_name = payload.model_name

    return {
        "message": "Active model set successfully.",
        "active_model": active_model_name,
    }


@app.get("/active-model")
def get_active_model() -> dict:
    """
    Return the currently active model.

    Returns
    -------
    dict
        Dictionary containing the active model name.
    """
    return {"active_model": active_model_name}


@app.post("/predict")
def predict(data: PredictionInput) -> dict:
    """
    Generate a prediction using the currently active model.

    Parameters
    ----------
    data : PredictionInput
        Input feature values required by the model.

    Returns
    -------
    dict
        Prediction result and the name of the active model.

    Raises
    ------
    HTTPException
        If no model has been selected yet.
    """
    global active_model_name, active_model

    if active_model is None or active_model_name is None:
        raise HTTPException(
            status_code=400,
            detail="No active model selected. Use /select-model first.",
        )

    input_df = pd.DataFrame([data.model_dump()])
    prediction = active_model.predict(input_df)

    return {
        "active_model": active_model_name,
        "prediction": int(prediction[0]),
    }


@app.get("/health")
def health() -> dict:
    """
    Return a simple health check response.

    Returns
    -------
    dict
        Status dictionary used to verify the API is running.
    """
    return {"status": "ok"}