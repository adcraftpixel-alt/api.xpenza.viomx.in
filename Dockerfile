FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

EXPOSE 8000

# Schema is managed at app startup (create_all + idempotent schema patches in
# app.main), NOT alembic — running alembic here crash-loops the container
# because prod was bootstrapped with create_all (empty alembic_version).
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
