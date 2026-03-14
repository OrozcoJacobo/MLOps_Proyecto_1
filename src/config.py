from dataclasses import dataclass


@dataclass(frozen=True)
class PostgresConfig:
    host: str = "localhost"
    port: int = 5432
    database: str = "mlops_db"
    user: str = "mlops_user"
    password: str = "mlops_password"


@dataclass(frozen=True)
class MinioConfig:
    endpoint: str = "localhost:9000"
    access_key: str = "minio_admin"
    secret_key: str = "minio_admin_password"
    bucket_name: str = "models"
    secure: bool = False


postgres_config = PostgresConfig()
minio_config = MinioConfig()