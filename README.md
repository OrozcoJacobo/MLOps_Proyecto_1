# 🌲 MLOps Project - Forest Cover Type Classification

**Pontificia Universidad Javeriana | MLOps 2026**  
**Grupo 8**

---

## 📐 Arquitectura

```
Data API (localhost:80)
        │
        ▼
   ┌─────────────────────────────────────────────────┐
   │              Apache Airflow (8080)              │
   │   DAG 1: data_collection  (cada 5 min)         │
   │   DAG 2: data_processing  (cada 10 min)        │
   │   DAG 3: model_training   (cada 2 horas)       │
   └──────────────┬──────────────────────┬───────────┘
                  │                      │
                  ▼                      ▼
   ┌──────────────────────┐   ┌───────────────────┐
   │  PostgreSQL Data     │   │      MinIO        │
   │  (puerto 5433)       │   │  (puerto 9001)    │
   │  schema: raw         │   │  bucket:          │
   │  schema: processed   │   │  mlops-models     │
   │  schema: ready       │   │                   │
   └──────────────────────┘   └────────┬──────────┘
                                        │
                                        ▼
                              ┌──────────────────────┐
                              │  Inference API       │
                              │  FastAPI (8000)      │
                              │  POST /predict       │
                              │  POST /predict/batch │
                              │  GET  /model/info    │
                              │  POST /model/reload  │
                              └──────────────────────┘
```

---

## 🚀 Inicio Rápido

### 1. Pre-requisitos
- Data API en `http://localhost:80`
- Clonar repositorio (no aplica si se realiza por asistente de VS Code):
```bash
git clone https://github.com/OrozcoJacobo/MLOps_Proyecto_1.git
```
Ingresar al directorio inicial del repo donde se encuentra todo el proyecto, si se usa VS Code esto no aplica porque al clonar el repo a través del asistente ya queda la ruta establecida en la terminal.
```bash
cd MLOps_Proyecto_1 
``` 

### 1.1 Subir API Data
La API para la obtención de datos se usó de forma local, debido a los inconvenientes con el acceso a la VPN; por lo tanto, se agregan los archivos a este repositorio con el fin de que haga parte directamente del proyecto.

¡IMPORTANTE!
El dataset usado (.csv) no se encuentra dentro del repo compartido, tampoco es posible descargarlo del sitio web porque el archivo está corrupto, por tal motivo se tuvo que usar la opción de acceso a través de código conectándose al repo dado en las indicaciones de la página. 

Si el contenedor de la API ya se encuentra creado, es necesario removerlo y crear uno nuevo.

```bash
cd api\ data
docker-compose build
docker-compose up -d
``` 

Probar API

```bash
curl -X 'GET' \
  'http://localhost/data?group_number=8' \
  -H 'accept: application/json'
```

Restaurar generación de datos para iniciar de cero cuando se ejecuten los dags de airflow. 

```bash
curl -X 'GET' \
  'http://localhost/restart_data_generation?group_number=8' \
  -H 'accept: application/json'
```
### 2. Preparar directorios para airflow

```bash

cd mlops-project

# Crear directorios necesarios
mkdir -p airflow/logs airflow/dags airflow/plugins
chmod -R 777 airflow/logs

# Configurar UID (Mac/Linux)
echo "AIRFLOW_UID=$(id -u)" >> .env
```

### 3. Construir y levantar servicios

```bash
docker-compose build
docker-compose up -d
```

> ⚠️ **Primera vez:** El proceso tarda ~3-5 minutos. Airflow inicializa la base de datos y crea el usuario admin automáticamente.

### 4. Verificar servicios

```bash
docker-compose ps
```

---

## 🌐 Interfaces

| Servicio | URL | Credenciales |
|----------|-----|-------------|
| **Airflow** | http://localhost:8080 | admin / admin |
| **MinIO Console** | http://localhost:9001 | minioadmin / minioadmin123 |
| **Inference API Docs** | http://localhost:8000/docs | — |
| **Jupyter Lab** | http://localhost:8888 | ver token en logs |

Para obtener el token de Jupyter:
```bash
docker logs jupyter 2>&1 | grep "token=" | tail -1
```

---

## 📊 Flujo de Datos

### DAG 1: `1_data_collection` (cada 5 min)
```
fetch_data → save_to_raw → restart_data_generation
```
- Hace exactamente **1 petición GET** por ejecución a `GET /data?group_number=8`
- Si la API responde `400` (batch agotado), salta el guardado y llama a `/restart_data_generation` para que el siguiente run pueda recolectar datos
- Guarda en `raw.forest_cover` con el formato original de la API (arrays posicionales de 55 columnas)

### DAG 2: `2_data_processing` (cada 10 min)
```
raw_to_processed → processed_to_ready
```
- **raw → processed:**
  - Elimina registros con nulos en features críticas
  - Filtra anomalías: `Slope > 90°`
  - Convierte `wilderness_area` de one-hot → categórico (`Rawah`, `Neota`, `Commanche`, `Cache`)
  - Convierte `soil_type` de one-hot → código categórico (`C7745`, `C2703`, etc.)
  - Convierte `Cover_Type` de rango 1-7 → **0-6**
- **processed → ready:**
  - Re-aplica one-hot encoding para dejar 54 features listas para el modelo
  - Split estratificado: **70% train / 15% val / 15% test**

### DAG 3: `3_model_training` (cada 2 horas)
```
check_data_availability → train_model → upload_to_minio
```
- Requiere mínimo **100 muestras** de entrenamiento (si no hay suficientes, el DAG termina limpiamente sin error)
- Entrena **Random Forest** y **Gradient Boosting** en paralelo
- Escalado selectivo: `StandardScaler` solo sobre las 10 features numéricas (no sobre las binarias one-hot)
- Selecciona el mejor modelo por `validation accuracy`
- Guarda en MinIO: `mlops-models/models/{algorithm}/{version}/model_package.joblib`
- Registra métricas en `public.model_registry` y marca el nuevo modelo como activo

---

## 🗄️ Base de Datos

### Esquemas PostgreSQL

| Schema | Tabla | Descripción |
|--------|-------|-------------|
| `raw` | `forest_cover` | Datos crudos de la API con one-hot de wilderness y soil |
| `processed` | `forest_cover` | Datos limpios con categorías string y Cover_Type 0-6 |
| `ready` | `forest_cover` | Features array de 54 columnas con split asignado |
| `public` | `model_registry` | Registro de modelos entrenados con métricas |

### Tipos de Cobertura Forestal (Cover_Type 0-6)

| ID | Tipo |
|----|------|
| 0 | Spruce/Fir |
| 1 | Lodgepole Pine |
| 2 | Ponderosa Pine |
| 3 | Cottonwood/Willow |
| 4 | Aspen |
| 5 | Douglas-fir |
| 6 | Krummholz |

---

## 🔮 Inference API

### Recargar modelo desde MinIO
```bash
curl -X POST http://localhost:8000/model/reload
```

### Predecir una muestra
```bash
curl -X POST http://localhost:8000/predict \
  -H "Content-Type: application/json" \
  -d '{
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
    "soil_type": "C7745"
  }'
```

**Respuesta:**
```json
{
  "cover_type": 4,
  "cover_type_label": "Aspen",
  "probability": 0.87,
  "probabilities": {"Spruce/Fir": 0.02, "Aspen": 0.87, ...},
  "model_algorithm": "random_forest",
  "predicted_at": "2026-03-16T10:00:00"
}
```

### Valores válidos
```bash
curl http://localhost:8000/wilderness-areas   # Rawah, Neota, Commanche, Cache
curl http://localhost:8000/soil-types         # C2702, C2703, ..., C8776
curl http://localhost:8000/cover-types        # Mapa 0-6
curl http://localhost:8000/model/info         # Info del modelo activo
```

---

## 📁 Estructura del Proyecto

```
mlops-project/
├── docker-compose.yml
├── .env
├── README.md
│
├── airflow/
│   ├── Dockerfile                          # Imagen personalizada con dependencias
│   ├── dags/
│   │   ├── dag_01_data_collection.py       # Recolección (cada 5 min)
│   │   ├── dag_02_data_processing.py       # Procesamiento (cada 10 min)
│   │   └── dag_03_model_training.py        # Entrenamiento (cada 2 h)
│   ├── logs/
│   ├── plugins/
│   └── config/
│
├── inference-api/
│   ├── main.py                             # FastAPI app
│   ├── pyproject.toml                      # Dependencias (uv)
│   └── Dockerfile
│
├── postgres/
│   └── init/
│       └── 01_init.sql                     # Esquemas raw, processed, ready
│
└── jupyter/
    └── mlops_pipeline_exploration.ipynb    # Notebook de exploración
```

---

## 🛑 Detener Servicios

```bash
docker-compose down        # Detiene contenedores (conserva datos)
docker-compose down -v     # Detiene y elimina volúmenes (borra todos los datos)
```

---

## ⚠️ Notas Importantes

1. **Una petición por ejecución de DAG** — el DAG 1 hace exactamente 1 petición por run, cumpliendo el requisito del proyecto.
2. **Reinicio automático de batch** — cuando la API responde `400`, el DAG llama automáticamente a `/restart_data_generation` para que el siguiente run tenga datos disponibles.
3. **Cover_Type 0-6** — el modelo predice en rango 0-6 (el dataset original usa 1-7; la transformación se aplica en el DAG 2).
4. **Modelo activo** — solo un modelo tiene `is_active=TRUE` en `model_registry`; la API siempre carga ese. Usar `POST /model/reload` después de un nuevo entrenamiento si la API ya estaba corriendo.
5. **Mínimo de datos** — el DAG 3 requiere al menos 100 muestras en `ready.forest_cover` para entrenar. Si no hay suficientes, el DAG termina en verde (skipped) sin error.

---

## 🐛 Problemas Encontrados y Soluciones

### Problema 1: Imagen de PostgreSQL incorrecta

**Síntoma:** Al ejecutar `docker-compose up -d` fallaba inmediatamente con:
```
pull access denied for postgresql, repository does not exist or may require 'docker login'
```

**Causa:** En el `docker-compose.yml` se usó `image: postgresql:15` como nombre de la imagen. La imagen oficial de PostgreSQL en Docker Hub se llama `postgres`, no `postgresql`. Docker intentaba buscar un repositorio inexistente.

**Solución:** Cambiar el nombre de la imagen en todos los servicios de PostgreSQL del `docker-compose.yml`:
```yaml
# Antes
image: postgresql:15

# Después
image: postgres:15
```

---

### Problema 2: Airflow no iniciaba — base de datos no inicializada

**Síntoma:** Los contenedores `airflow-webserver` y `airflow-scheduler` quedaban en estado `Restarting` indefinidamente con el error:
```
ERROR: You need to initialize the database. Please run `airflow db init`.
Make sure the command is run using Airflow version 2.8.1.
```

**Causa:** Había dos problemas simultáneos. Primero, el webserver y el scheduler arrancaban antes de que `airflow-init` completara la migración de la base de datos, porque el `depends_on` con `service_completed_successfully` no funcionaba correctamente en Docker Compose V2 en Mac — los servicios dependientes simplemente no se creaban. Segundo, el comando `airflow db migrate` usado en el init no es equivalente a `airflow db init` para una instalación fresca; el webserver de la versión 2.8.1 requiere específicamente `airflow db init` para la primera inicialización.

**Solución:** Reestructurar la secuencia de inicio en dos servicios separados con `restart: "no"` para que no se reinicien en bucle, y usar `airflow db init` en lugar de `airflow db migrate`:
```yaml
airflow-init:
  command: ["db", "init"]
  restart: "no"

airflow-create-user:
  command: [users, create, --username, admin, ...]
  restart: "no"
  depends_on:
    airflow-init:
      condition: service_completed_successfully

airflow-webserver:
  depends_on:
    airflow-create-user:
      condition: service_completed_successfully
```

---

### Problema 3: scikit-learn==1.4.2 incompatible con Python 3.8

**Síntoma:** Los contenedores de Airflow fallaban al instalar dependencias con:
```
ERROR: Could not find a version that satisfies the requirement scikit-learn==1.4.2
ERROR: Ignored the following versions that require a different python version:
1.4.0 Requires-Python >=3.9; 1.4.2 Requires-Python >=3.9
```

**Causa:** La imagen oficial `apache/airflow:2.8.1` está construida sobre Python 3.8. Las versiones de scikit-learn >= 1.4.0 requieren Python >= 3.9, por lo que no existe ninguna versión de scikit-learn==1.4.2 compatible con el entorno de Airflow. Adicionalmente, `_PIP_ADDITIONAL_REQUIREMENTS` es un mecanismo inestable que instala paquetes en cada arranque del contenedor, lo que causaba que los contenedores fallaran y se reiniciaran en bucle.

**Solución:** Dos cambios simultáneos. Primero, bajar las versiones de los paquetes a las compatibles con Python 3.8:
```
scikit-learn==1.3.2   # última versión compatible con Python 3.8
numpy==1.24.4         # última versión compatible con Python 3.8
minio==7.2.7          # versión compatible con Python 3.8
joblib==1.3.2
```
Segundo, reemplazar `_PIP_ADDITIONAL_REQUIREMENTS` por un `Dockerfile` personalizado para Airflow que preinstala los paquetes durante el build y no en cada arranque:
```dockerfile
FROM apache/airflow:2.8.1
USER root
RUN apt-get update && apt-get install -y gcc libpq-dev
USER airflow
RUN pip install --no-cache-dir scikit-learn==1.3.2 numpy==1.24.4 ...
```

---

### Problema 4: DAGs no aparecían en Airflow

**Síntoma:** La interfaz web de Airflow en `http://localhost:8080` mostraba "No results" en la lista de DAGs, aunque los servicios estaban corriendo correctamente.

**Causa:** El directorio `./airflow/dags/` en la máquina local estaba vacío. Airflow monta ese directorio como volumen dentro del contenedor en `/opt/airflow/dags/`. Si la carpeta local no contiene archivos `.py`, el scheduler no tiene DAGs que cargar. La confusión surgió porque se asumía que los DAGs se generarían automáticamente.

**Solución:** Copiar los tres archivos de DAGs al directorio `airflow/dags/` del proyecto en la máquina local. El scheduler de Airflow escanea esa carpeta continuamente y detecta los archivos nuevos en aproximadamente 30 segundos, sin necesidad de reiniciar ningún contenedor.

---

### Problema 5: DAG 1 fallaba con error 400

**Síntoma:** El DAG 1 fallaba en la tarea `fetch_data` con:
```
requests.exceptions.HTTPError: 400 Client Error: Bad Request for url:
http://host.docker.internal:80/data?group_number=8
```

**Causa:** La Data API devuelve HTTP 400 con el mensaje `{"detail": "Ya se recolectó toda la información mínima necesaria"}` cuando el batch actual ya fue agotado por peticiones previas de otros grupos. El código del DAG llamaba `response.raise_for_status()` sin verificar primero el código de estado, por lo que interpretaba este 400 como un error fatal y lanzaba una excepción, marcando la tarea como fallida.

**Solución:** Manejar el código 400 explícitamente antes de llamar `raise_for_status()`, tratándolo como una condición normal de negocio y no como un error. Adicionalmente, se agregó una tercera tarea `restart_data_generation` que llama al endpoint `/restart_data_generation?group_number=8` cuando no hay datos disponibles, para que el siguiente run del DAG pueda recolectar datos del batch nuevo:
```python
if response.status_code == 400:
    context["ti"].xcom_push(key="raw_data", value=None)
    return "No data available — skipping."
```

---

### Problema 6: Datos raw guardados con NULLs en todas las columnas

**Síntoma:** Los registros en `raw.forest_cover` se creaban correctamente pero con `elevation`, `aspect`, `slope` y todas las demás features en `NULL`. Solo `batch_number` y `group_number` tenían valores.

**Causa:** El DAG intentaba acceder a los datos como diccionarios con claves (`r.get("elevation")`, `r.get("soil_type")`), pero la API devuelve los datos en formato de arrays posicionales sin nombres de columna, dentro de una estructura anidada:
```json
{"group_number": 8, "batch_number": 4, "data": [["2596", "51", "3", ...]]}
```
Cada elemento de `data` es una lista de 55 valores donde la posición determina la columna. Al intentar `.get("elevation")` sobre una lista, retornaba `None` para todas las columnas.

**Solución:** Actualizar `save_to_raw_db` para parsear el formato correcto: extraer `batch_number` y `records` del diccionario raíz, y mapear cada posición del array a su columna correspondiente por índice:
```python
batch_number = raw_data.get("batch_number")
records = raw_data.get("data", [])
# Mapeo posicional:
# r[0]=elevation, r[1]=aspect, ..., r[10..13]=wilderness_area_1..4
# r[14..53]=soil_type_1..40, r[54]=cover_type
```
También fue necesario actualizar la tabla `raw.forest_cover` para tener `wilderness_area_1..4` y `soil_type_1..40` como columnas separadas, reflejando el formato one-hot real de la API.

---

### Problema 7: Credenciales de MinIO incorrectas en el DAG 3

**Síntoma:** La tarea `upload_to_minio` del DAG 3 fallaba con:
```
minio.error.S3Error: S3 operation failed; code: InvalidAccessKeyId,
message: The Access Key Id you provided does not exist in our records.
```

**Causa:** El `docker-compose.yml` del proyecto definía las credenciales de MinIO como `MINIO_ROOT_USER=minio_admin` y `MINIO_ROOT_PASSWORD=minio_admin_password`. Sin embargo, los DAGs usaban las credenciales por defecto `minioadmin/minioadmin123` a través de variables de entorno que nunca se pasaron al bloque `x-airflow-common`. El contenedor del scheduler no tenía las variables `MINIO_*` definidas, como se confirmó con:
```bash
docker exec airflow-scheduler env | grep MINIO
# No retornaba nada
```

**Solución:** Unificar las credenciales en `docker-compose.yml` usando `minioadmin/minioadmin123` en todos los servicios, y agregar explícitamente las variables de entorno de MinIO al bloque `x-airflow-common` para que todos los contenedores de Airflow las reciban:
```yaml
x-airflow-common:
  environment:
    MINIO_ENDPOINT: minio:9000
    MINIO_ACCESS_KEY: minioadmin
    MINIO_SECRET_KEY: minioadmin123
    MINIO_BUCKET: mlops-models
```

---

### Problema 8: DAG 3 fallaba al inicio del sistema por falta de datos

**Síntoma:** Al levantar el sistema por primera vez, el DAG 3 fallaba repetidamente en `check_data_availability` con:
```
ValueError: Insufficient training data: 0 samples (minimum required: 100)
```
El DAG quedaba en rojo en la interfaz de Airflow.

**Causa:** El DAG 3 tiene una frecuencia de ejecución de cada 2 horas. Al iniciarse el sistema por primera vez, Airflow intentaba ejecutar runs atrasados del DAG antes de que los DAGs 1 y 2 tuvieran tiempo de recolectar y procesar al menos 100 muestras. La tarea `check_data_availability` lanzaba un `ValueError` que marcaba la tarea y el DAG completo como fallido, generando alertas innecesarias.

**Solución:** Reemplazar `PythonOperator` por `ShortCircuitOperator` en la tarea `check_data_availability`. Con este operador, retornar `False` no marca el DAG como fallido sino que marca las tareas siguientes como `Skipped` y el DAG termina en verde. Retornar `True` permite que el pipeline continúe normalmente:
```python
from airflow.operators.python import ShortCircuitOperator

def check_data_availability(**context):
    if train_count < MIN_TRAINING_SAMPLES:
        logging.info(f"Not enough data yet ({train_count}/100). Skipping.")
        return False  # DAG termina en verde, no en rojo
    return True

task_check = ShortCircuitOperator(
    task_id="check_data_availability",
    python_callable=check_data_availability,
)
```

---

### Problema 9: Módulos faltantes en la Inference API

**Síntoma:** Al llamar `POST /model/reload` la API respondía:
```json
{"detail": "No module named 'dill'"}
```
En un intento anterior también había fallado con `No module named 'minio'`.

**Causa:** La imagen de la Inference API no tenía instalados `minio` ni `dill`. El paquete `dill` es una dependencia de `joblib` que se activa cuando los modelos contienen objetos complejos serializados. Aunque `joblib` estaba instalado, `dill` no se instala automáticamente como dependencia directa y debe declararse explícitamente.

**Solución:** Agregar ambos paquetes al `pyproject.toml` de la Inference API y reconstruir la imagen:
```toml
dependencies = [
    ...
    "minio==7.2.7",
    "dill==0.3.8",
]
```
```bash
docker-compose up -d --build inference-api
```

---

### Problema 10: numpy==1.24.4 incompatible con Python 3.12

**Síntoma:** Al construir la imagen de la Inference API fallaba con:
```
Failed to build numpy==1.24.4
ModuleNotFoundError: No module named 'distutils'
hint: distutils was removed from the standard library in Python 3.12.
```

**Causa:** El `Dockerfile` de la Inference API usaba `FROM python:3.12-slim` como imagen base, pero las versiones de los paquetes definidas en `pyproject.toml` (especialmente `numpy==1.24.4`) dependían de `distutils`, un módulo que existía en Python 3.8-3.11 pero fue removido definitivamente en Python 3.12. La combinación de imagen base moderna con versiones antiguas de paquetes era incompatible.

**Solución:** Cambiar la imagen base del `Dockerfile` de la Inference API a `python:3.11-slim`, que mantiene soporte para `distutils` y es compatible con todas las versiones de paquetes declaradas:
```dockerfile
# Antes
FROM python:3.12-slim

# Después
FROM python:3.11-slim
```

---

## 🔧 Comandos Clave de Referencia

### Docker Compose

```bash
# Construir imágenes
docker-compose build
docker-compose build --no-cache                    # Forzar rebuild sin caché
docker-compose up -d --build inference-api         # Reconstruir solo un servicio

# Gestión de servicios
docker-compose up -d                               # Levantar todos los servicios
docker-compose down                                # Detener (conserva volúmenes)
docker-compose down -v                             # Detener y eliminar volúmenes
docker-compose ps                                  # Ver estado de contenedores

# Logs
docker-compose logs --tail=50 airflow-webserver    # Logs del webserver
docker-compose logs --tail=50 airflow-scheduler    # Logs del scheduler
docker-compose logs --tail=50 inference-api        # Logs de la API
docker logs jupyter 2>&1 | grep "token=" | tail -1 # Token de acceso a Jupyter

# Variables de entorno
docker exec airflow-scheduler env | grep MINIO     # Verificar variables MinIO en Airflow
```

### PostgreSQL

```bash
# Conectarse a la base de datos
docker exec -it postgres-data psql -U mlops -d mlops_db
```

Una vez dentro del cliente `psql`:

```sql
-- Estado general del pipeline
SELECT COUNT(*) FROM raw.forest_cover;
SELECT COUNT(*) FROM processed.forest_cover;
SELECT COUNT(*) FROM ready.forest_cover;

-- Registros por batch recolectado
SELECT batch_number, COUNT(*) AS registros, MIN(fetched_at) AS primera_vez
FROM raw.forest_cover
GROUP BY batch_number
ORDER BY batch_number;

-- Distribución de splits train/val/test
SELECT split_set, COUNT(*) AS total
FROM ready.forest_cover
GROUP BY split_set
ORDER BY split_set;

-- Distribución de clases (Cover_Type 0-6)
SELECT cover_type, COUNT(*) AS total
FROM processed.forest_cover
GROUP BY cover_type
ORDER BY cover_type;

-- Distribución de wilderness_area
SELECT wilderness_area, COUNT(*) AS total
FROM processed.forest_cover
GROUP BY wilderness_area
ORDER BY total DESC;

-- Registro de modelos entrenados
SELECT model_version, algorithm,
       ROUND(accuracy::numeric, 4) AS accuracy,
       ROUND(f1_score::numeric, 4)  AS f1_score,
       train_samples, is_active, trained_at
FROM public.model_registry
ORDER BY trained_at DESC;

-- Salir del cliente
\q
```

### Data API

```bash
# Obtener datos del batch actual
curl "http://localhost:80/data?group_number=8"

# Reiniciar generación de datos del grupo
curl "http://localhost:80/restart_data_generation?group_number=8"

# Ver número de columnas y filas del batch actual
curl "http://localhost:80/data?group_number=8" | python3 -c \
  "import json,sys; d=json.load(sys.stdin); print('Columnas:', len(d['data'][0])); print('Filas:', len(d['data']))"

# Documentación Swagger de la Data API
open http://localhost:80/docs
```

### Inference API

```bash
# Health check
curl http://localhost:8000/health

# Info del modelo activo
curl http://localhost:8000/model/info

# Recargar modelo desde MinIO (necesario después de un nuevo entrenamiento)
curl -X POST http://localhost:8000/model/reload

# Valores de referencia
curl http://localhost:8000/wilderness-areas    # Rawah, Neota, Commanche, Cache
curl http://localhost:8000/soil-types         # C2702, C2703, ..., C8776
curl http://localhost:8000/cover-types        # Mapa 0-6

# Predicción individual
curl -X POST http://localhost:8000/predict \
  -H "Content-Type: application/json" \
  -d '{
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
    "soil_type": "C7745"
  }'
```

---

## 💡 Lecciones Aprendidas

**Compatibilidad de versiones** — siempre verificar la versión de Python de la imagen base antes de definir versiones de paquetes. `apache/airflow:2.8.1` usa Python 3.8, lo que limita scikit-learn a máximo 1.3.2 y numpy a 1.24.4. Para la Inference API, `python:3.11-slim` es el balance correcto.

**Airflow en Docker** — `_PIP_ADDITIONAL_REQUIREMENTS` es inestable para producción; siempre preferir un Dockerfile personalizado. `airflow db init` es necesario para instalaciones frescas; `airflow db migrate` es solo para actualizaciones de versión. `ShortCircuitOperator` es más apropiado que lanzar excepciones cuando se quiere saltar tareas sin marcar el DAG como fallido.

**Formato de APIs externas** — nunca asumir el formato de respuesta de una API externa. Verificar siempre con `curl` antes de codificar el parser. En este caso la API devolvía arrays posicionales, no diccionarios, y el código 400 era una señal de negocio válida, no un error técnico.

**Buenas prácticas aplicadas** — usar `joblib` en lugar de `pickle` para modelos de scikit-learn. Aplicar escalado selectivo con `StandardScaler` solo sobre features numéricas, no sobre binarias one-hot. Normalizar `Cover_Type` a rango 0-6 siguiendo el notebook de preprocesamiento oficial. Fijar versiones específicas de herramientas (como `uv:0.6.6`) para builds reproducibles.