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

# Copy startup script that handles Alembic migration initialization
COPY start.sh .
RUN chmod +x start.sh

# Apply DB migrations before starting so the schema always matches the code.
# The startup script stamps the initial revision if needed, then runs upgrade head.
CMD ["./start.sh"]

