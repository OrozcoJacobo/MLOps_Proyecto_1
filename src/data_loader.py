import pandas as pd
from sqlalchemy import create_engine, text

from src.config import postgres_config


def get_postgres_engine():
    """
    Create a SQLAlchemy engine for connecting to PostgreSQL.

    Returns
    -------
    sqlalchemy.engine.Engine
        Engine object used to establish connections with the database.

    Notes
    -----
    The connection parameters are retrieved from the centralized
    configuration defined in `PostgresConfig`.
    """
    connection_url = (
        f"postgresql+psycopg2://{postgres_config.user}:"
        f"{postgres_config.password}@{postgres_config.host}:"
        f"{postgres_config.port}/{postgres_config.database}"
    )
    return create_engine(connection_url)


def test_connection() -> None:
    """
    Test the PostgreSQL connection.

    This function executes a simple SQL query (`SELECT 1`) to verify that
    the database connection is working correctly.

    Prints
    ------
    Confirmation message indicating whether the connection succeeded.
    """
    engine = get_postgres_engine()

    with engine.connect() as connection:
        result = connection.execute(text("SELECT 1 AS test_value;"))
        row = result.fetchone()
        print("Database connection successful.")
        print(f"Test query result: {row.test_value}")


def load_table(table_name: str) -> pd.DataFrame:
    """
    Load a full table from PostgreSQL into a pandas DataFrame.

    Parameters
    ----------
    table_name : str
        Name of the table to query.

    Returns
    -------
    pandas.DataFrame
        DataFrame containing all rows from the requested table.

    Notes
    -----
    This function is used by the training pipeline to retrieve the
    dataset stored in PostgreSQL before performing preprocessing
    and model training.
    """
    engine = get_postgres_engine()
    query = f"SELECT * FROM {table_name};"
    df = pd.read_sql(query, engine)
    return df


if __name__ == "__main__":
    test_connection()