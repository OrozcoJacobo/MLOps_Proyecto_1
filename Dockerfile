FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml .
COPY uv.lock .

RUN pip install uv
RUN uv pip install --system .

COPY src ./src

EXPOSE 8000

CMD ["uvicorn", "src.inference_service:app", "--host", "0.0.0.0", "--port", "8000"]