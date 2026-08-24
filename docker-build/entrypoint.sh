#!/bin/sh
set -e

echo "PostgreSQL is up - running migrations"
alembic upgrade head

echo "Starting application"
exec "$@"