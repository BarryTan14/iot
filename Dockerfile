FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project
COPY . .

EXPOSE 8080

# Single CMD - do not set a custom "Start Command" in Railway (it overrides this)
CMD sh -c "python manage.py migrate --noinput && python manage.py collectstatic --noinput || true && exec daphne -b 0.0.0.0 -p \${PORT:-8080} config.asgi:application"
