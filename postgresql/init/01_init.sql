-- ============================================================
-- Inicialización de la base de datos MLOps
-- Tres esquemas: raw, processed, ready
-- ============================================================

-- Esquema RAW: datos tal como llegan de la API
CREATE SCHEMA IF NOT EXISTS raw;

-- Esquema PROCESSED: datos limpios y transformados
CREATE SCHEMA IF NOT EXISTS processed;

-- Esquema READY: datos listos para entrenamiento
CREATE SCHEMA IF NOT EXISTS ready;

-- ─── Tabla RAW ───────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS raw.forest_cover (
    id                              SERIAL PRIMARY KEY,
    batch_number                    INTEGER,
    group_number                    INTEGER,
    fetched_at                      TIMESTAMP DEFAULT NOW(),
    -- Features numéricas
    elevation                       FLOAT,
    aspect                          FLOAT,
    slope                           FLOAT,
    horizontal_distance_to_hydrology FLOAT,
    vertical_distance_to_hydrology  FLOAT,
    horizontal_distance_to_roadways FLOAT,
    hillshade_9am                   FLOAT,
    hillshade_noon                  FLOAT,
    hillshade_3pm                   FLOAT,
    horizontal_distance_to_fire_points FLOAT,
    -- Wilderness areas (raw puede venir como string o número)
    wilderness_area                 VARCHAR(50),
    -- Soil type (raw puede venir como número)
    soil_type                       INTEGER,
    -- Target
    cover_type                      INTEGER,
    -- Datos originales en JSON por si acaso
    raw_json                        JSONB
);

-- ─── Tabla PROCESSED ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS processed.forest_cover (
    id                              SERIAL PRIMARY KEY,
    raw_id                          INTEGER REFERENCES raw.forest_cover(id),
    processed_at                    TIMESTAMP DEFAULT NOW(),
    -- Features numéricas (limpias y normalizadas)
    elevation                       FLOAT NOT NULL,
    aspect                          FLOAT NOT NULL,
    slope                           FLOAT NOT NULL,
    horizontal_distance_to_hydrology FLOAT NOT NULL,
    vertical_distance_to_hydrology  FLOAT NOT NULL,
    horizontal_distance_to_roadways FLOAT NOT NULL,
    hillshade_9am                   FLOAT NOT NULL,
    hillshade_noon                  FLOAT NOT NULL,
    hillshade_3pm                   FLOAT NOT NULL,
    horizontal_distance_to_fire_points FLOAT NOT NULL,
    -- Wilderness areas (one-hot encoded: 4 columnas)
    wilderness_area_1               INTEGER DEFAULT 0,
    wilderness_area_2               INTEGER DEFAULT 0,
    wilderness_area_3               INTEGER DEFAULT 0,
    wilderness_area_4               INTEGER DEFAULT 0,
    -- Soil type (one-hot encoded: 40 columnas)
    soil_type_1                     INTEGER DEFAULT 0,
    soil_type_2                     INTEGER DEFAULT 0,
    soil_type_3                     INTEGER DEFAULT 0,
    soil_type_4                     INTEGER DEFAULT 0,
    soil_type_5                     INTEGER DEFAULT 0,
    soil_type_6                     INTEGER DEFAULT 0,
    soil_type_7                     INTEGER DEFAULT 0,
    soil_type_8                     INTEGER DEFAULT 0,
    soil_type_9                     INTEGER DEFAULT 0,
    soil_type_10                    INTEGER DEFAULT 0,
    soil_type_11                    INTEGER DEFAULT 0,
    soil_type_12                    INTEGER DEFAULT 0,
    soil_type_13                    INTEGER DEFAULT 0,
    soil_type_14                    INTEGER DEFAULT 0,
    soil_type_15                    INTEGER DEFAULT 0,
    soil_type_16                    INTEGER DEFAULT 0,
    soil_type_17                    INTEGER DEFAULT 0,
    soil_type_18                    INTEGER DEFAULT 0,
    soil_type_19                    INTEGER DEFAULT 0,
    soil_type_20                    INTEGER DEFAULT 0,
    soil_type_21                    INTEGER DEFAULT 0,
    soil_type_22                    INTEGER DEFAULT 0,
    soil_type_23                    INTEGER DEFAULT 0,
    soil_type_24                    INTEGER DEFAULT 0,
    soil_type_25                    INTEGER DEFAULT 0,
    soil_type_26                    INTEGER DEFAULT 0,
    soil_type_27                    INTEGER DEFAULT 0,
    soil_type_28                    INTEGER DEFAULT 0,
    soil_type_29                    INTEGER DEFAULT 0,
    soil_type_30                    INTEGER DEFAULT 0,
    soil_type_31                    INTEGER DEFAULT 0,
    soil_type_32                    INTEGER DEFAULT 0,
    soil_type_33                    INTEGER DEFAULT 0,
    soil_type_34                    INTEGER DEFAULT 0,
    soil_type_35                    INTEGER DEFAULT 0,
    soil_type_36                    INTEGER DEFAULT 0,
    soil_type_37                    INTEGER DEFAULT 0,
    soil_type_38                    INTEGER DEFAULT 0,
    soil_type_39                    INTEGER DEFAULT 0,
    soil_type_40                    INTEGER DEFAULT 0,
    -- Target
    cover_type                      INTEGER NOT NULL
);

-- ─── Tabla READY ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ready.forest_cover (
    id                              SERIAL PRIMARY KEY,
    processed_id                    INTEGER REFERENCES processed.forest_cover(id),
    prepared_at                     TIMESTAMP DEFAULT NOW(),
    split_set                       VARCHAR(10) NOT NULL, -- 'train', 'val', 'test'
    -- Todas las features como un arreglo de floats
    features                        FLOAT[] NOT NULL,
    cover_type                      INTEGER NOT NULL
);

-- ─── Tabla de registro de modelos ────────────────────────────
CREATE TABLE IF NOT EXISTS public.model_registry (
    id                  SERIAL PRIMARY KEY,
    model_name          VARCHAR(100) NOT NULL,
    model_version       VARCHAR(50) NOT NULL,
    minio_path          VARCHAR(255) NOT NULL,
    algorithm           VARCHAR(100),
    accuracy            FLOAT,
    f1_score            FLOAT,
    train_samples       INTEGER,
    trained_at          TIMESTAMP DEFAULT NOW(),
    is_active           BOOLEAN DEFAULT FALSE,
    hyperparameters     JSONB
);

-- ─── Índices ─────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_raw_batch ON raw.forest_cover(batch_number);
CREATE INDEX IF NOT EXISTS idx_raw_fetched ON raw.forest_cover(fetched_at);
CREATE INDEX IF NOT EXISTS idx_processed_cover ON processed.forest_cover(cover_type);
CREATE INDEX IF NOT EXISTS idx_ready_split ON ready.forest_cover(split_set);
CREATE INDEX IF NOT EXISTS idx_model_active ON public.model_registry(is_active);

-- Mensaje de confirmación
DO $$ BEGIN
    RAISE NOTICE 'MLOps database initialized successfully with schemas: raw, processed, ready';
END $$;
