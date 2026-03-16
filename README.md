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
                              │  GET  /              │
                              │  POST /predict       │
                              │  POST /predict/batch │
                              │  GET  /model/info    │
                              └──────────────────────┘
```

## 🚀 Inicio Rápido

### 1. Pre-requisitos
- Docker Desktop instalado y corriendo
- Data API corriendo en `http://localhost:80`
- Git

### 2. Clonar y preparar

```bash
git clone <repo-url>
cd mlops-project

# Crear directorios con permisos correctos
mkdir -p airflow/logs airflow/dags airflow/plugins
chmod -R 777 airflow/logs
```

### 3. Configurar variables de entorno

```bash
# En Mac/Linux
echo "AIRFLOW_UID=$(id -u)" >> .env

Esto no es necesario...
```

### 4. Levantar todos los servicios

```bash
Se debe activar primero el servicio postgres-airflow para que el servicio airflow-init funcione correctamente. Si no se activa, este genera un error y los sercicios airflow-webserver y airflow-scheduler se quedan en bucle porque no pueden iniciar.  
docker-compose up -d postgres-airflow
docker compose ps  

Una vez se verifique que el servicio postgres-airflow esté en estado "healthy", activar el servicio airflow-init.

docker-compose run --rm airflow-init

docker-compose up -d
```

> ⚠️ **Primera vez:** El proceso tarda ~3-5 minutos. Airflow inicializa la DB y crea el usuario admin.

### 5. Verificar servicios

```bash
docker-compose ps
```

---

## 🌐 Interfaces Gráficas

| Servicio | URL | Credenciales |
|----------|-----|-------------|
| **Airflow** | http://localhost:8080 | admin / admin |
| **MinIO Console** | http://localhost:9001 | minioadmin / minioadmin123 |
| **Inference API** | http://localhost:8000 | — |
| **API Docs (Swagger)** | http://localhost:8000/docs | — |
| **Jupyter Lab** | http://localhost:8888 | token en logs |

---

## 📊 Flujo de Datos

### DAG 1: `1_data_collection` (cada 5 min)
```
Data API → fetch_data → save_to_raw → raw.forest_cover (PostgreSQL)
```
- Una única petición GET por ejecución
- Guarda datos sin procesar en esquema `raw`

### DAG 2: `2_data_processing` (cada 10 min)  
```
raw.forest_cover → raw_to_processed → processed.forest_cover
                 → processed_to_ready → ready.forest_cover
```
- One-hot encoding de `wilderness_area` (→ 4 columnas)
- One-hot encoding de `soil_type` (→ 40 columnas)
- Split 70% train / 15% val / 15% test

### DAG 3: `3_model_training` (cada 2 horas)
```
ready.forest_cover → train_model → upload_to_minio → model_registry
```
- Entrena Random Forest y Gradient Boosting
- Selecciona el mejor por validation accuracy
- Guarda en MinIO: `mlops-models/models/{algorithm}/{version}/model_package.pkl`

---

## 🔮 Inference API

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
    "wilderness_area": 1,
    "soil_type": 29
  }'
```

**Respuesta:**
```json
{
  "cover_type": 5,
  "cover_type_label": "Aspen",
  "probability": 0.87,
  "probabilities": {"Spruce/Fir": 0.02, "Aspen": 0.87, ...},
  "model_algorithm": "random_forest",
  "predicted_at": "2026-03-11T10:00:00"
}
```

### Recargar modelo desde MinIO

```bash
curl -X POST http://localhost:8000/model/reload
```

### Info del modelo activo

```bash
curl http://localhost:8000/model/info
```

---

## 🛑 Detener servicios

```bash
docker-compose down          # Detiene y elimina contenedores
docker-compose down -v       # También elimina volúmenes (borra datos)
```

---

## 📁 Estructura del proyecto

```
mlops-project/
├── docker-compose.yml          # Orquestación de servicios
├── .env                        # Variables de entorno
├── README.md
│
├── airflow/
│   ├── dags/
│   │   ├── dag_01_data_collection.py   # Recolección (cada 5 min)
│   │   ├── dag_02_data_processing.py   # Procesamiento (cada 10 min)
│   │   └── dag_03_model_training.py    # Entrenamiento (cada 2 h)
│   ├── logs/
│   ├── plugins/
│   └── config/
│
├── inference-api/
│   ├── main.py                 # FastAPI app
│   ├── requirements.txt
│   └── Dockerfile
│
├── postgres/
│   └── init/
│       └── 01_init.sql         # Esquemas: raw, processed, ready
│
└── jupyter/                    # Notebooks de exploración
```

---

## 🗂 Tipos de Cobertura Forestal

| ID | Tipo |
|----|------|
| 1 | Spruce/Fir |
| 2 | Lodgepole Pine |
| 3 | Ponderosa Pine |
| 4 | Cottonwood/Willow |
| 5 | Aspen |
| 6 | Douglas-fir |
| 7 | Krummholz |

---

## ⚠️ Notas Importantes

1. **Una petición por ejecución de DAG**: El DAG 1 hace exactamente 1 petición a la API por run.
2. **Rotación de batches**: La Data API rota el batch cada 5 minutos, por eso el DAG 1 está programado cada 5 min.
3. **Mínimo de datos para entrenar**: El DAG 3 requiere al menos 100 muestras de entrenamiento antes de ejecutar.
4. **Modelo activo**: Solo un modelo está marcado como `is_active=TRUE` en el registry; la API siempre usa ese.
