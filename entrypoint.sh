#!/bin/sh
set -eu

# Demo-friendly default: ensure the DB schema exists.
# On Cloud Run + SQLite this creates tables inside the instance filesystem.
if [ "${MIGRATE_ON_STARTUP:-true}" = "true" ]; then
  echo "Running migrations..."
  python manage.py migrate --noinput
fi

# Optional: warm-up staticfiles manifest checks (no-op if already collected)
# python manage.py collectstatic --noinput

exec gunicorn bloodbankmanagement.wsgi:application \
  --bind 0.0.0.0:${PORT:-8080} \
  --log-file - \
  --timeout ${GUNICORN_TIMEOUT:-120}
