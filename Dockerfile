FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    WARDROBE_MEDIA_ROOT=/app/.wardrobe_media

WORKDIR /app

COPY backend/requirements.txt /tmp/requirements.txt

RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY backend/app /app/backend/app
COPY backend/migrations /app/backend/migrations

COPY frontend/index.html /app/frontend/index.html
COPY frontend/css /app/frontend/css
COPY frontend/js /app/frontend/js
COPY frontend/assets /app/frontend/assets

WORKDIR /app/backend

CMD ["sh", "-c", "exec uvicorn app.web:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1 --no-access-log"]
