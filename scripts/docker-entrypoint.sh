#!/bin/sh
set -e
python manage.py migrate --noinput -v 0
python manage.py jobforge_admin --if-none --username "${JOBFORGE_ADMIN_USER:-admin}" \
  --email "${JOBFORGE_ADMIN_EMAIL:-}" --password "${JOBFORGE_ADMIN_PASSWORD:-}"
if [ "${JOBFORGE_DEMO:-0}" = "1" ]; then python manage.py jobforge_demo || true; fi
exec "$@"
