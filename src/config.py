from dataclasses import dataclass
import os


@dataclass(frozen=True)
class PostgresConfig:
    """
    Configuration parameters required to connect to the PostgreSQL database.

    Attributes
    ----------
    host : str
        Host where the PostgreSQL service is running.
    port : int
        Port where PostgreSQL is exposed.
    database : str
        Name of the database containing the training data.
    user : str
        Database user used for authentication.
    password : str
        Password associated with the database user.
    """

    host: str = os.getenv("POSTGRES_HOST", "localhost")
    port: int = int(os.getenv("POSTGRES_PORT", 5432))
    database: str = os.getenv("POSTGRES_DB", "mlops_db")
    user: str = os.getenv("POSTGRES_USER", "mlops_user")
    password: str = os.getenv("POSTGRES_PASSWORD", "mlops_password")


@dataclass(frozen=True)
class MinioConfig:
    """
    Configuration parameters required to connect to the MinIO object storage.

    Attributes
    ----------
    endpoint : str
        Address of the MinIO server including port.
    access_key : str
        Access key used to authenticate with MinIO.
    secret_key : str
        Secret key used for authentication.
    bucket_name : str
        Name of the bucket where trained models will be stored.
    secure : bool
        Whether to use HTTPS when connecting to MinIO.
    """

    endpoint: str = os.getenv("MINIO_ENDPOINT", "localhost:9000")
    access_key: str = os.getenv("MINIO_ACCESS_KEY", "minio_admin")
    secret_key: str = os.getenv("MINIO_SECRET_KEY", "minio_admin_password")
    bucket_name: str = os.getenv("MINIO_BUCKET", "models")
    secure: bool = os.getenv("MINIO_SECURE", "false").lower() == "true"


postgres_config = PostgresConfig()
minio_config = MinioConfig()