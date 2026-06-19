#!/bin/bash
set -e

echo "==> Exporting environment variables for cron..."
# Export all environment variables except a few sensitive or system ones
printenv | grep -v -E "no_proxy|LS_COLORS|PATH" > /etc/environment || true

echo "==> Running database migrations..."
python manage.py migrate --noinput

echo "==> Collecting static files..."
python manage.py collectstatic --noinput 2>/dev/null || true

echo "==> Starting Cron Daemon..."
cron

echo "==> Starting Gunicorn..."
exec gunicorn reminderbot.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers 2 \
    --timeout 120 \
    --access-logfile - \
    --error-logfile -
