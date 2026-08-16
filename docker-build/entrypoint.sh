#!/bin/sh



echo "PostgreSQL is up - running migrations"
alembic upgrade head

echo "Starting application"
exec uvicorn src.main:app --host 0.0.0.0 --port 8000
