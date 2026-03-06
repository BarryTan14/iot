#!/bin/bash
set -e

echo "=== Starting deployment ==="
echo "PORT=${PORT:-8000}"

echo "=== Running migrations ==="
python manage.py migrate --noinput

echo "=== Collecting static files ==="
python manage.py collectstatic --noinput || true

echo "=== Starting Gunicorn on 0.0.0.0:${PORT:-8000} ==="
exec gunicorn evicted.wsgi --bind "0.0.0.0:${PORT:-8000}" --workers 1 --timeout 120 --access-logfile - --error-logfile -
