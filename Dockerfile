FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DATA_DIR=/data \
    LANG=C.UTF-8

RUN apt-get update \
 && apt-get install -y --no-install-recommends libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 \
      fonts-dejavu-core fonts-liberation2 fonts-crosextra-carlito curl \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --system --create-home --home-dir /app jobforge

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY --chown=jobforge:jobforge . .
RUN SECRET_KEY=build-only python manage.py collectstatic --noinput -v 0 \
 && mkdir -p /data && chown jobforge:jobforge /data /app/staticfiles

USER jobforge
VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD curl -fsS http://127.0.0.1:8000/health/ || exit 1
ENTRYPOINT ["/app/scripts/docker-entrypoint.sh"]
CMD ["gunicorn", "jobforge.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--threads", "2", "--timeout", "120", "--access-logfile", "-"]
