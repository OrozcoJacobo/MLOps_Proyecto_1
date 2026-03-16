# MLOps Proyecto 1

**Pontificia Universidad Javeriana**  
**Grupo 8**
- Jacobo Orozco
- Javier Chaparro

---

## Arquitectura

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

## Inicio 

### 1. Prerrequisitos
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

### IMPORTANTE
El dataset usado (.csv) no se encuentra dentro del repo compartido, tampoco es posible descargarlo del sitio web porque el archivo está corrupto, por tal motivo se tuvo que usar la opción de acceso a través de código conectándose al repo dado en las indicaciones de la página. 

Si el contenedor de la API ya se encuentra creado, es necesario removerlo y crear uno nuevo. De lo contrario ejecutar los siguientes comandos para acceder al directorio de la data API, crear la imagen y el contenedor correspondiente.

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
# Crear directorios necesarios y otorgar permisos (el directorio plugins es opcional)
mkdir -p airflow/logs airflow/dags airflow/plugins
chmod -R 777 airflow/logs
```
### 3. Construir imagen y levantar servicios

```bash
docker-compose build
docker-compose up -d
```
![alt text](</images/Screenshot 2026-03-16 at 12.56.35 PM.png>)
![alt text](</images/Screenshot 2026-03-16 at 1.00.12 PM.png>)

### 4. Verificar servicios

Es importante que todos los servicios estén en "Up" en status.

```bash
docker-compose ps
```
![alt text](</images/Screenshot 2026-03-16 at 1.03.07 PM.png>)

---

## Interfaces

| Servicio | URL | Credenciales |
|----------|-----|-------------|
| **Airflow** | http://localhost:8080 | admin / admin |
| **MinIO Console** | http://localhost:9001 | minioadmin / minioadmin123 |
| **Inference API Docs** | http://localhost:8000/docs | — |
| **Jupyter Lab** | http://localhost:8888 | ver token en logs |

Para obtener el token de Jupyter y poder acceder a través de la URL: 
```bash
docker logs jupyter 2>&1 | grep "token=" | tail -1
```
Ejemplo:

![alt text](</images/Screenshot 2026-03-16 at 1.08.05 PM.png>)

---

## Flujo de Datos

### IMPORTANTE

Si el DAG 1 falla se debe eliminar el archivo "timestamps.json" del directorio api data/data. El repositorio se entrega con ese directorio vacío para que la data api genere nuevamente el archivo, sin embargo, si se presenta el error se deben ejecutar los siguientes comandos:

```bash
rm "api data/data/timestamps.json"
docker restart fastapi
```

### DAG 1: `1_data_collection` (cada 5 min)
```
fetch_data → save_to_raw → restart_data_generation
```
- Hace exactamente una petición GET por ejecución a `GET /data?group_number=8`
- Si la API responde `400` (batch agotado), omite el guardado y ejecuta a `/restart_data_generation` para que en la siguiente ejecución pueda recolectar datos
- Guarda en `raw.forest_cover` con el formato original de la API (arrays posicionales de 55 columnas)

Se observan los 3 DAG disponibles...

![alt text](</images/Screenshot 2026-03-16 at 3.59.30 PM.png>)

Ejecución DAG 1 exitosa

![alt text](</images/Screenshot 2026-03-16 at 4.01.08 PM.png>)

Datos recibidos 

![alt text](</images/Screenshot 2026-03-16 at 4.02.14 PM.png>)

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
  - Aplica nuevamente one-hot encoding para dejar 54 features listas para el modelo
  - Estratificación de clases: **70% train / 15% val / 15% test**

Ejecución DAG 2 exitosa

![alt text](</images/Screenshot 2026-03-16 at 4.14.58 PM.png>)

Tablas en BD posterior a la primera ejecución DAG 1 y 2 (recolección y procesamiento).

![alt text](</images/Screenshot 2026-03-16 at 4.08.39 PM.png>)

### DAG 3: `3_model_training` (cada 2 horas)
```
check_data_availability → train_model → upload_to_minio
```
- Requiere mínimo 100 muestras de entrenamiento (si no hay suficientes omite steps 2 y 3, el DAG termina sin error)
- Entrena dos modelos en paralelo: Random Forest y Gradient Boosting
- Escalado selectivo: `StandardScaler` solo sobre las 10 features numéricas (no sobre las binarias one-hot)
- Selecciona el mejor modelo teniendo en cuenta su accuracy `validation accuracy`
- Guarda en MinIO: `mlops-models/models/{algorithm}/{version}/model_package.joblib`
- Registra métricas en `public.model_registry` y marca el nuevo modelo como activo

Ejecución DAG 3 exitosa

![alt text](</images/Screenshot 2026-03-16 at 4.16.52 PM.png>)

## Diez ejecuciones de los DAG

![alt text](</images/Screenshot 2026-03-16 at 4.11.58 PM.png>)

---

## Base de Datos

### Esquemas PostgreSQL

| Schema | Tabla | Descripción |
|--------|-------|-------------|
| `raw` | `forest_cover` | Datos crudos de la API con one-hot de wilderness y soil |
| `processed` | `forest_cover` | Datos limpios con categorías string y Cover_Type 0-6 |
| `ready` | `forest_cover` | Features array de 54 columnas con split asignado |
| `public` | `model_registry` | Registro de modelos entrenados con métricas |

Los schemas y las tablas son creadas a partir del archivo: 01_init.sql

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

## Consulta de las tres tablas en la BD posterior a las diez ejecuciones

![alt text](</images/Screenshot 2026-03-16 at 4.13.13 PM.png>)

## Verificación de métricas almacenadas en la BD

![alt text](</images/Screenshot 2026-03-16 at 5.08.43 PM.png>)

---

## Modelos almacenados en MinIO

Los modelos quedan almacenados en el directorio "models"

![alt text](</images/Screenshot 2026-03-16 at 4.31.42 PM.png>)

Cada directorio tiene almacenadas distintas versiones de los modelos, según el número de ejecuciones de los DAG.  

![alt text](</images/Screenshot 2026-03-16 at 4.33.34 PM.png>)

El último .joblib va a ser utilizado por la API de inferencia.

![alt text](</images/Screenshot 2026-03-16 at 4.35.57 PM.png>)

## API de Inferencia

![alt text](</images/Screenshot 2026-03-16 at 4.44.02 PM.png>)

### Recargar modelo desde MinIO
```bash
curl -X POST http://localhost:8000/model/reload
```

![alt text](</images/Screenshot 2026-03-16 at 4.45.14 PM.png>)

### Predicción
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
**Ejemplo de Respuesta:**
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

**Ejecución y respuesta real usando el modelo gradient boosting**
![alt text](</images/Screenshot 2026-03-16 at 4.46.58 PM.png>)


### Métodos para verificar valores válidos
```bash
curl http://localhost:8000/wilderness-areas   # Rawah, Neota, Commanche, Cache
curl http://localhost:8000/soil-types         # C2702, C2703, ..., C8776
curl http://localhost:8000/cover-types        # Mapa 0-6
curl http://localhost:8000/model/info         # Info del modelo activo
```

---

---

## Jupyter

Se crea un notebook para la exploración completa del pipeline.

![alt text](</images/Screenshot 2026-03-16 at 5.18.41 PM.png>)

---

## Estructura del Proyecto

```
mlops-project/
├── docker-compose.yml
├── README.md
│
├── airflow/
│   ├── Dockerfile                          # Imagen personalizada con dependencias
│   ├── dags/
│   │   ├── dag_01_data_collection.py       # Recolección (cada 5 min)
│   │   ├── dag_02_data_processing.py       # Procesamiento (cada 10 min)
│   │   └── dag_03_model_training.py        # Entrenamiento (cada 2 h)
│   ├── logs/
│   └── config/
│
├── api/
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

## Detener Servicios

```bash
docker-compose down        # Detiene contenedores (conserva datos)
docker-compose down -v     # Detiene y elimina volúmenes (borra todos los datos)
```

---

## Notas Importantes

1. **Una petición por ejecución de DAG** — el DAG 1 hace exactamente 1 petición por run.
2. **Reinicio automático de batch** — cuando la API responde `400`, el DAG ejecuta automáticamente el método `/restart_data_generation` para que la siguiente ejecución tenga datos disponibles. Se podrán obtener datos más de diez veces...
3. **Cover_Type 0-6** — el modelo predice en rango 0-6 (el dataset original usa 1-7 y la transformación se aplica en el DAG 2).
4. **Modelo activo** — solo un modelo tiene el valor `is_active=TRUE` en el atributo `model_registry` y la API siempre carga ese. Se debe usar `POST /model/reload` después de un nuevo entrenamiento si la API ya estaba en ejecución.
5. **Mínimo de datos** — el DAG 3 requiere al menos 100 muestras almacenadas en la tabla `ready.forest_cover` para entrenar. Si no hay suficientes, el DAG termina sin error, pero no realiza entrenamiento, simplemente omite los siguientes steps.

---

## Problemas encontrados y soluciones

### Problema 1: Airflow no iniciaba — base de datos no inicializada

**Descripción:** Los contenedores `airflow-webserver` y `airflow-scheduler` quedaban en estado `Restarting` indefinidamente con el error:
```
ERROR: You need to initialize the database. Please run `airflow db init`.
Make sure the command is run using Airflow version 2.8.1.
```

**Causa:** Había dos problemas simultáneos. Primero, el webserver y el scheduler arrancaban antes de que `airflow-init` completara la migración de la base de datos, porque el `depends_on` con `service_completed_successfully` no funcionaba correctamente y los servicios dependientes simplemente no se creaban. Segundo, el comando `airflow db migrate` usado en el init no es equivalente a `airflow db init` para una instalación fresca; el webserver de la versión 2.8.1 requiere específicamente `airflow db init` para la primera inicialización.

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

### Problema 2: scikit-learn==1.4.2 incompatible con Python 3.8

**Descripción:** Los contenedores de Airflow fallaban al instalar dependencias con:
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

### Problema 3: DAG 1 fallaba con error 400

**Descripción:** El DAG 1 fallaba en el step `fetch_data` con:
```
requests.exceptions.HTTPError: 400 Client Error: Bad Request for url:
http://host.docker.internal:80/data?group_number=8
```

**Causa:** La Data API devuelve HTTP 400 con el mensaje `{"detail": "Ya se recolectó toda la información mínima necesaria"}` cuando el batch actual ya fue agotado por peticiones previas. El código del DAG llamaba `response.raise_for_status()` sin verificar primero el código de estado, por lo que interpretaba este 400 como un error fatal y lanzaba una excepción, marcando la tarea como fallida.

**Solución:** Manejar el código 400 explícitamente antes de llamar `raise_for_status()`, tratándolo como una condición normal de negocio y no como un error. Adicionalmente, se agregó una tercera tarea `restart_data_generation` que llama al endpoint `/restart_data_generation?group_number=8` cuando no hay datos disponibles, para que el siguiente run del DAG pueda recolectar datos del batch nuevo:
```python
if response.status_code == 400:
    context["ti"].xcom_push(key="raw_data", value=None)
    return "No data available — skipping."
```

---

### Problema 4: Datos raw guardados con NULLs en todas las columnas

**Descripción:** Los registros en `raw.forest_cover` se creaban correctamente pero con `elevation`, `aspect`, `slope` y todas las demás features en `NULL`. Solo `batch_number` y `group_number` tenían valores.

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

### Problema 5: DAG 3 fallaba al inicio del sistema por falta de datos

**Descripción:** Al ejecutar el sistema por primera vez, el DAG 3 fallaba repetidamente en `check_data_availability` con:
```
ValueError: Insufficient training data: 0 samples (minimum required: 100)
```
El DAG quedaba en rojo en la interfaz de Airflow.

**Causa:** El DAG 3 tiene una frecuencia de ejecución de cada 2 horas. Al iniciarse el sistema por primera vez, Airflow intentaba ejecutar runs atrasados del DAG antes de que los DAGs 1 y 2 tuvieran tiempo de recolectar y procesar al menos 100 muestras. La tarea `check_data_availability` lanzaba un `ValueError` que marcaba la tarea y el DAG completo como fallido, generando alertas innecesarias.

**Solución:** Reemplazar `PythonOperator` por `ShortCircuitOperator` en la tarea `check_data_availability`. Con este operador, retornar `False` no marca el DAG como fallido sino que marca las tareas siguientes como `Skipped` y el DAG termina exitosamente. Retornar `True` permite que el pipeline continúe normalmente:
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

### Problema 6: Módulos faltantes en la Inference API

**Descripción:** Al llamar `POST /model/reload` la API respondía:
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

### Problema 7: numpy==1.24.4 incompatible con Python 3.12

**Descripción:** Al construir la imagen de la Inference API fallaba con:
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

## Comandos Clave de Referencia

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

### API de Inferencia

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