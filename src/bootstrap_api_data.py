import requests
from sqlalchemy import create_engine, text

from src.config import postgres_config


API_URL = "http://10.43.101.94:8080/data"
GROUP_NUMBER = 8
TABLE_NAME = "training_data"


def get_postgres_engine():
    """
    Create a SQLAlchemy engine for connecting to PostgreSQL.

    Returns
    -------
    sqlalchemy.engine.Engine
        Engine object configured using the database settings defined
        in the project configuration.
    """
    connection_url = (
        f"postgresql+psycopg2://{postgres_config.user}:"
        f"{postgres_config.password}@{postgres_config.host}:"
        f"{postgres_config.port}/{postgres_config.database}"
    )
    return create_engine(connection_url)


def fetch_api_data(group_number: int) -> dict:
    """
    Fetch a batch of data from the external API.

    Parameters
    ----------
    group_number : int
        Identifier of the student group assigned to the request.

    Returns
    -------
    dict
        JSON response from the API containing:
        - group_number
        - batch_number
        - data (list of rows)

    Raises
    ------
    requests.HTTPError
        If the API request fails.
    """
    response = requests.get(API_URL, params={"group_number": group_number}, timeout=30)
    response.raise_for_status()
    return response.json()


def create_training_table(engine) -> None:
    """
    Create the training data table if it does not already exist.

    Parameters
    ----------
    engine : sqlalchemy.engine.Engine
        SQLAlchemy engine used to execute the SQL command.

    Notes
    -----
    The schema is based on the structure returned by the external API.
    Additional metadata fields such as `group_number`, `batch_number`,
    and `inserted_at` are included for traceability.
    """
    create_table_sql = f"""
    CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
        id SERIAL PRIMARY KEY,
        elevation INT NOT NULL,
        aspect INT NOT NULL,
        slope INT NOT NULL,
        horizontal_distance_to_hydrology INT NOT NULL,
        vertical_distance_to_hydrology INT NOT NULL,
        horizontal_distance_to_roadways INT NOT NULL,
        hillshade_9am INT NOT NULL,
        hillshade_noon INT NOT NULL,
        hillshade_3pm INT NOT NULL,
        horizontal_distance_to_fire_points INT NOT NULL,
        wilderness_area TEXT NOT NULL,
        soil_type TEXT NOT NULL,
        cover_type INT NOT NULL,
        group_number INT NOT NULL,
        batch_number INT NOT NULL,
        inserted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """

    with engine.begin() as connection:
        connection.execute(text(create_table_sql))


def insert_rows(engine, payload: dict) -> None:
    """
    Insert rows retrieved from the API into PostgreSQL.

    Parameters
    ----------
    engine : sqlalchemy.engine.Engine
        Engine used to connect to the database.
    payload : dict
        JSON payload returned by the external API containing the dataset.

    Notes
    -----
    The API returns rows as lists of strings. This function converts
    numeric values into integers before inserting them into the database.
    """
    rows = payload["data"]
    group_number = payload["group_number"]
    batch_number = payload["batch_number"]

    insert_sql = text(f"""
        INSERT INTO {TABLE_NAME} (
            elevation,
            aspect,
            slope,
            horizontal_distance_to_hydrology,
            vertical_distance_to_hydrology,
            horizontal_distance_to_roadways,
            hillshade_9am,
            hillshade_noon,
            hillshade_3pm,
            horizontal_distance_to_fire_points,
            wilderness_area,
            soil_type,
            cover_type,
            group_number,
            batch_number
        )
        VALUES (
            :elevation,
            :aspect,
            :slope,
            :horizontal_distance_to_hydrology,
            :vertical_distance_to_hydrology,
            :horizontal_distance_to_roadways,
            :hillshade_9am,
            :hillshade_noon,
            :hillshade_3pm,
            :horizontal_distance_to_fire_points,
            :wilderness_area,
            :soil_type,
            :cover_type,
            :group_number,
            :batch_number
        );
    """)

    parsed_rows = []
    for row in rows:
        parsed_rows.append(
            {
                "elevation": int(row[0]),
                "aspect": int(row[1]),
                "slope": int(row[2]),
                "horizontal_distance_to_hydrology": int(row[3]),
                "vertical_distance_to_hydrology": int(row[4]),
                "horizontal_distance_to_roadways": int(row[5]),
                "hillshade_9am": int(row[6]),
                "hillshade_noon": int(row[7]),
                "hillshade_3pm": int(row[8]),
                "horizontal_distance_to_fire_points": int(row[9]),
                "wilderness_area": row[10],
                "soil_type": row[11],
                "cover_type": int(row[12]),
                "group_number": group_number,
                "batch_number": batch_number,
            }
        )

    with engine.begin() as connection:
        connection.execute(insert_sql, parsed_rows)

    print(f"Inserted {len(parsed_rows)} rows into '{TABLE_NAME}'.")


def main():
    """
    Bootstrap the PostgreSQL database with real data from the external API.

    Workflow
    --------
    1. Fetch data from the API.
    2. Ensure the training table exists.
    3. Insert the received rows into PostgreSQL.

    This script is intended for development purposes to populate the
    database before the Airflow ingestion pipeline is implemented.
    """
    print("Fetching data from external API...")
    payload = fetch_api_data(GROUP_NUMBER)

    print(
        f"Received batch {payload['batch_number']} "
        f"for group {payload['group_number']} "
        f"with {len(payload['data'])} rows."
    )

    engine = get_postgres_engine()

    print("Creating table if it does not exist...")
    create_training_table(engine)

    print("Inserting rows into PostgreSQL...")
    insert_rows(engine, payload)

    print("Bootstrap completed successfully.")


if __name__ == "__main__":
    main()