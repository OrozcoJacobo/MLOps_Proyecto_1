FROM apache/airflow:2.8.1

USER root
RUN apt-get update && apt-get install -y gcc libpq-dev && rm -rf /var/lib/apt/lists/*

USER airflow
RUN pip install --no-cache-dir \    
    scikit-learn==1.3.2 \
    numpy==1.24.4 \
    psycopg2-binary==2.9.9 \
    requests==2.31.0 \
    joblib==1.3.2