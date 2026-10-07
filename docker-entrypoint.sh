#!/bin/sh
# Bring the database up to date and load the fuel dataset before serving.
# Both steps are idempotent, so this is safe on every container start.
set -e

echo "Applying migrations..."
python manage.py migrate --noinput

echo "Importing fuel prices..."
python manage.py import_fuel_prices "${FUEL_PRICES_CSV:-data/fuel-prices-for-be-assessment.csv}"

echo "Starting server on :8000"
exec gunicorn config.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers "${GUNICORN_WORKERS:-3}" \
    --timeout 60 \
    --access-logfile -
