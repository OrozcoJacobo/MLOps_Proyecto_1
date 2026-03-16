from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Query
from typing import Optional, List
from pydantic import BaseModel, Field
import random
import json
import time
import os

MIN_UPDATE_TIME = 60 ## Aca pueden cambiar el tiempo minimo para cambiar bloque de información

# ---------------------------
# Metadatos y documentación
# ---------------------------

APP_DESCRIPTION = (
    """
    API para suministrar datos del Proyecto 2 (Extracción de datos y entrenamiento de modelos).

    - Origen de datos externo: http://10.43.100.103:80
    - Los datos cambian cada 5 minutos (configurable con MIN_UPDATE_TIME).
    - El dataset completo se divide en 10 lotes (batches). Cada request al endpoint /data
      devuelve una porción aleatoria del batch vigente para el grupo solicitado.
    - Para obtener una muestra mínima útil, recolecta al menos una porción de cada uno de los 10 batches.
    - Uso sugerido: orquestar la recolección con Airflow y entrenar/registrar modelos con MLflow.

    Código y guía para desplegar/pruebas (incluyendo cómo reducir el tiempo entre cambios de batch):
    https://github.com/CristianDiazAlvarez/MLOPS_PUJ/tree/main/Niveles/2/P2

    Diagrama ilustrativo del flujo de batches (GitHub):
    https://raw.githubusercontent.com/CristianDiazAlvarez/MLOPS_PUJ/refs/heads/main/Niveles/2/P2/images/p2_data.png
    
    Orden de las columnas:
    # Elevation, Aspect, Slope,
    # Horizontal_Distance_To_Hydrology, Vertical_Distance_To_Hydrology,
    # Horizontal_Distance_To_Roadways,
    # Hillshade_9am, Hillshade_Noon, Hillshade_3pm,
    # Horizontal_Distance_To_Fire_Points,
    # Wilderness_Area, Soil_Type, Cover_Type
    """
)

tags_metadata = [
    {"name": "info", "description": "Información general del servicio."},
    {"name": "data", "description": "Obtención de porciones de datos por grupo y batch."},
    {"name": "admin", "description": "Operaciones de control para reiniciar conteos por grupo."},
]

# ---------------------------
# Estado global
# ---------------------------
data = []
batch_size = 0
timestamps = {}

# ---------------------------
# Lifespan: carga de datos al arrancar
# ---------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    global data, batch_size, timestamps

    print("[startup] Descargando dataset Covertype desde UCI ML Repository...")
    try:
        from ucimlrepo import fetch_ucirepo
        covertype = fetch_ucirepo(id=31)
        X = covertype.data.features
        y = covertype.data.targets

        # Combinar features + target y convertir a listas de strings (mismo formato que el CSV original)
        df = X.copy()
        df[y.columns[0]] = y.values
        data = df.astype(str).values.tolist()
        print(f"[startup] Dataset cargado: {len(data)} filas, {len(data[0])} columnas.")
    except Exception as e:
        print(f"[startup] ERROR al cargar el dataset: {e}")
        raise RuntimeError(f"No se pudo cargar el dataset: {e}")

    batch_size = len(data) // 10

    # Cargar timestamps persistidos si existen
    if os.path.isfile('/data/timestamps.json'):
        with open('/data/timestamps.json', "r") as f:
            timestamps = json.load(f)
        print("[startup] Timestamps cargados desde /data/timestamps.json")
    else:
        timestamps = {str(g): [0, -1] for g in range(1, 11)}
        print("[startup] Timestamps inicializados.")

    yield  # La app corre aquí

    print("[shutdown] Cerrando API.")


# ---------------------------
# App
# ---------------------------
app = FastAPI(
    title="Proyecto 2 - Data API",
    version="1.0.0",
    description=APP_DESCRIPTION,
    lifespan=lifespan,
    contact={
        "name": "Curso MLOps PUJ",
        "url": "https://github.com/CristianDiazAlvarez/MLOPS_PUJ",
    },
    license_info={
        "name": "MIT",
        "url": "https://opensource.org/licenses/MIT",
    },
    openapi_tags=tags_metadata,
)

# ---------------------------
# Modelos
# ---------------------------
class BatchResponse(BaseModel):
    group_number: int = Field(..., ge=1, le=10, description="Número de grupo solicitado (1-10)")
    batch_number: int = Field(..., description="Índice del batch servido para el grupo")
    data: List[List[str]] = Field(..., description="Filas del dataset para la porción solicitada")


# ---------------------------
# Helpers
# ---------------------------
def get_batch_data(batch_number: int):
    start_index = batch_number * batch_size
    end_index = start_index + batch_size
    return random.sample(data[start_index:end_index], batch_size // 10)


def save_timestamps():
    os.makedirs('/data', exist_ok=True)
    with open('/data/timestamps.json', 'w') as f:
        f.write(json.dumps(timestamps))


# ---------------------------
# Endpoints
# ---------------------------
@app.get("/", tags=["info"], summary="Estado del servicio")
async def root():
    return {"Proyecto 2": "Extracción de datos, entrenamiento de modelos."}


@app.get(
    "/data",
    tags=["data"],
    summary="Obtener porción aleatoria del batch vigente",
    description=(
        "Devuelve filas aleatorias del batch actual para el grupo indicado. "
        "El batch cambia cada 5 minutos (MIN_UPDATE_TIME). Para una muestra mínima, "
        "extrae al menos una porción de cada uno de los 10 batches."
    ),
    response_model=BatchResponse,
)
async def read_data(
    group_number: int = Query(..., ge=1, le=10, description="Número de grupo asignado (1-10).", example=1)
):
    global timestamps

    if timestamps[str(group_number)][1] >= 10:
        raise HTTPException(status_code=400, detail="Ya se recolectó toda la información mínima necesaria")

    current_time = time.time()
    last_update_time = timestamps[str(group_number)][0]

    if current_time - last_update_time > MIN_UPDATE_TIME:
        timestamps[str(group_number)][0] = current_time
        timestamps[str(group_number)][1] += 2 if timestamps[str(group_number)][1] == -1 else 1

    random_data = get_batch_data(timestamps[str(group_number)][1])
    save_timestamps()

    return {
        "group_number": group_number,
        "batch_number": timestamps[str(group_number)][1],
        "data": random_data,
    }


@app.get(
    "/restart_data_generation",
    tags=["admin"],
    summary="Reiniciar la generación para un grupo",
    description=(
        "Reinicia el temporizador y el conteo de batch para el grupo indicado. "
        "Útil para pruebas locales o para volver a comenzar la recolección de datos."
    ),
)
async def restart_data(
    group_number: int = Query(..., ge=1, le=10, description="Número de grupo a reiniciar (1-10).", example=1)
):
    timestamps[str(group_number)][0] = 0
    timestamps[str(group_number)][1] = -1
    save_timestamps()
    return {"ok": True}