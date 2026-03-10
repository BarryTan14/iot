web: python manage.py migrate --noinput && python manage.py collectstatic --noinput 2>/dev/null || true; daphne -b 0.0.0.0 -p $PORT evicted.asgi:application
