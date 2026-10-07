FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=config.settings

WORKDIR /app

# Dependencies are installed before the source is copied so a code change does
# not invalidate the dependency layer.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN chmod +x docker-entrypoint.sh && \
    adduser --disabled-password --gecos "" --uid 10001 appuser && \
    mkdir -p /app/state && chown -R appuser /app/state
USER appuser

EXPOSE 8000
ENTRYPOINT ["./docker-entrypoint.sh"]
