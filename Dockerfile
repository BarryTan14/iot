FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project
COPY . .

EXPOSE 8080

# Single CMD - do not set a custom "Start Command" in Railway (it overrides this)
CMD sh -c "python manage.py migrate --noinput && python manage.py collectstatic --noinput || true && exec gunicorn evicted.wsgi --bind 0.0.0.0:\${PORT:-8080} --workers 1 --timeout 120 --access-logfile - --error-logfile -"
