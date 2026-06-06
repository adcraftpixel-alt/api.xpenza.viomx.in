#!/bin/bash
set -e

# If alembic_version table is empty or missing, stamp the initial schema
# revision so Alembic knows the base tables already exist in the database.
# This handles the one-time migration from create_all() to Alembic-managed schema.
CURRENT=$(alembic current 2>/dev/null | grep -oP '^[a-f0-9]+' || true)

if [ -z "$CURRENT" ]; then
 echo "No Alembic revision found — stamping initial schema (f0e9ed121c40)..."
 alembic stamp f0e9ed121c40
fi

# Now apply any pending migrations (incremental only)
echo "Running alembic upgrade head..."
alembic upgrade head

# Start the application
exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}

