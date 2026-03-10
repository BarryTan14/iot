#!/bin/bash
set -e

# Railway uses PORT=8080 by default if not set
PORT="${PORT:-8080}"
echo "=== Starting on port $PORT ==="

echo "=== Running migrations ==="
python manage.py migrate --noinput

echo "=== Collecting static files ==="
python manage.py collectstatic --noinput || true

echo "=== Starting Daphne (ASGI for WebSockets) ==="
exec daphne -b 0.0.0.0 -p "$PORT" evicted.asgi:application
