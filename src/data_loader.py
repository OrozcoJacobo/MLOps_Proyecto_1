import pandas as pd
from sqlalchemy import create_engine, text

from src.config import postgres_config


def get_postgres_engine():
    connection_url = (
        f"postgresql+psycopg2://{postgres_config.user}:"
        f"{postgres_config.password}@{postgres_config.host}:"
        f"{postgres_config.port}/{postgres_config.database}"
    )
    return create_engine(connection_url)


def test_connection() -> None:
    engine = get_postgres_engine()

    with engine.connect() as connection:
        result = connection.execute(text("SELECT 1 AS test_value;"))
        row = result.fetchone()
        print("Database connection successful.")
        print(f"Test query result: {row.test_value}")


def load_table(table_name: str) -> pd.DataFrame:
    engine = get_postgres_engine()
    query = f"SELECT * FROM {table_name};"
    df = pd.read_sql(query, engine)
    return df


if __name__ == "__main__":
    test_connection()