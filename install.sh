#!/usr/bin/env bash
# =============================================================================
#  JobForge – Forge your workflow
#  Ein-Zeilen-Installer für Debian 12/13 und Ubuntu 22.04/24.04
#
#  curl -fsSL https://raw.githubusercontent.com/__GITHUB_OWNER__/JobForge/main/install.sh | sudo bash
#
#  Mit Domain + HTTPS (Let's Encrypt):
#  curl -fsSL https://raw.githubusercontent.com/__GITHUB_OWNER__/JobForge/main/install.sh \
#    | sudo bash -s -- --domain jobforge.example.com --email admin@example.com
#
#  Erneutes Ausführen aktualisiert eine bestehende Installation (Daten bleiben erhalten).
#  Lizenz: AGPL-3.0-or-later
# =============================================================================
set -Eeuo pipefail

REPO_URL="${JOBFORGE_REPO:-https://github.com/__GITHUB_OWNER__/JobForge.git}"
BRANCH="${JOBFORGE_BRANCH:-main}"
DOMAIN="${JOBFORGE_DOMAIN:-}"
EMAIL="${JOBFORGE_EMAIL:-}"
PORT="${JOBFORGE_PORT:-8000}"
DB="${JOBFORGE_DB:-postgres}"           # postgres | sqlite
WITH_NGINX="${JOBFORGE_NGINX:-1}"
ADMIN_USER="${JOBFORGE_ADMIN_USER:-admin}"
ADMIN_EMAIL="${JOBFORGE_ADMIN_EMAIL:-}"
DEMO="${JOBFORGE_DEMO:-0}"
UPDATE_ONLY=0

PREFIX=/opt/jobforge
APP_DIR="$PREFIX/app"
VENV="$PREFIX/venv"
DATA_DIR=/var/lib/jobforge
CONF_DIR=/etc/jobforge
ENV_FILE="$CONF_DIR/jobforge.env"
BACKUP_DIR=/var/backups/jobforge
SERVICE_USER=jobforge

c_info="\033[1;34m"; c_ok="\033[1;32m"; c_warn="\033[1;33m"; c_err="\033[1;31m"; c_off="\033[0m"
info() { echo -e "${c_info}==>${c_off} $*"; }
ok()   { echo -e "${c_ok}✔${c_off} $*"; }
warn() { echo -e "${c_warn}!${c_off} $*"; }
die()  { echo -e "${c_err}✘ $*${c_off}" >&2; exit 1; }
trap 'die "Installation in Zeile $LINENO abgebrochen. Details siehe Ausgabe oben."' ERR

usage() {
  cat <<EOF
JobForge Installer

Optionen:
  --domain NAME        Domain (z. B. jobforge.example.com) – aktiviert nginx-vHost
  --email ADRESSE      E-Mail für Let's Encrypt (mit --domain: HTTPS wird eingerichtet)
  --sqlite             SQLite statt PostgreSQL verwenden
  --no-nginx           Kein nginx einrichten (Gunicorn lauscht auf 127.0.0.1:PORT)
  --port PORT          Interner Gunicorn-Port (Standard 8000)
  --repo URL           Git-Repository (Standard: $REPO_URL)
  --branch NAME        Git-Branch (Standard: $BRANCH)
  --admin-user NAME    Benutzername des ersten Administrators (Standard: admin)
  --admin-email MAIL   E-Mail des Administrators
  --demo               Beispieldaten anlegen
  --update             Nur aktualisieren (Code, Abhängigkeiten, Migrationen)
  -h, --help           Diese Hilfe
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --domain) DOMAIN="$2"; shift 2 ;;
    --email) EMAIL="$2"; shift 2 ;;
    --sqlite) DB=sqlite; shift ;;
    --no-nginx) WITH_NGINX=0; shift ;;
    --port) PORT="$2"; shift 2 ;;
    --repo) REPO_URL="$2"; shift 2 ;;
    --branch) BRANCH="$2"; shift 2 ;;
    --admin-user) ADMIN_USER="$2"; shift 2 ;;
    --admin-email) ADMIN_EMAIL="$2"; shift 2 ;;
    --demo) DEMO=1; shift ;;
    --update) UPDATE_ONLY=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "Unbekannte Option: $1 (siehe --help)" ;;
  esac
done

[[ $EUID -eq 0 ]] || die "Bitte als root ausführen (z. B. mit sudo)."
[[ -r /etc/os-release ]] || die "Unbekanntes Betriebssystem."
# shellcheck disable=SC1091
. /etc/os-release
case "${ID:-}:${ID_LIKE:-}" in
  debian:*|ubuntu:*|*:*debian*) ;;
  *) die "Nicht unterstütztes System: ${PRETTY_NAME:-unbekannt}. Unterstützt werden Debian und Ubuntu." ;;
esac
[[ "$REPO_URL" == *"__GITHUB_OWNER__"* ]] && die "Repository-URL ist nicht gesetzt. Bitte --repo angeben."

as_app() { runuser -u "$SERVICE_USER" -- "$@"; }
manage() { as_app env JOBFORGE_ENV_FILE="$ENV_FILE" "$VENV/bin/python" "$APP_DIR/manage.py" "$@"; }
rand() { head -c 64 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c "${1:-50}"; }
set_env() {  # set_env KEY VALUE – setzt/ersetzt eine Zeile in der env-Datei
  local key="$1" value="$2"
  if grep -q "^${key}=" "$ENV_FILE"; then
    sed -i "s|^${key}=.*|${key}=${value}|" "$ENV_FILE"
  else
    echo "${key}=${value}" >> "$ENV_FILE"
  fi
}

echo -e "\n${c_ok}  ⚒  JobForge – Forge your workflow${c_off}\n"
info "System: ${PRETTY_NAME}"

# --- Pakete ------------------------------------------------------------------
if [[ $UPDATE_ONLY -eq 0 ]]; then
  info "Installiere Systempakete …"
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq
  PKGS=(git curl ca-certificates python3 python3-venv python3-pip
        libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b libharfbuzz-subset0 libffi8 shared-mime-info
        fonts-dejavu-core fonts-liberation2)
  [[ "$DB" == "postgres" ]] && PKGS+=(postgresql postgresql-client)
  [[ "$DB" == "sqlite" ]] && PKGS+=(sqlite3)
  [[ "$WITH_NGINX" == "1" ]] && PKGS+=(nginx)
  [[ -n "$DOMAIN" && -n "$EMAIL" && "$WITH_NGINX" == "1" ]] && PKGS+=(certbot python3-certbot-nginx)
  # Paketnamen unterscheiden sich je nach Version leicht – fehlende optionale Pakete überspringen
  AVAILABLE=()
  for p in "${PKGS[@]}"; do
    if apt-cache show "$p" >/dev/null 2>&1; then AVAILABLE+=("$p"); else warn "Paket $p nicht verfügbar – übersprungen"; fi
  done
  apt-get install -y -qq --no-install-recommends "${AVAILABLE[@]}" >/dev/null
  ok "Systempakete installiert"
fi

# --- Benutzer & Verzeichnisse ----------------------------------------------------
if ! id "$SERVICE_USER" >/dev/null 2>&1; then
  useradd --system --home-dir "$PREFIX" --shell /usr/sbin/nologin "$SERVICE_USER"
fi
install -d -o "$SERVICE_USER" -g "$SERVICE_USER" -m 755 "$PREFIX"
install -d -o "$SERVICE_USER" -g "$SERVICE_USER" -m 750 "$DATA_DIR" "$DATA_DIR/media"
install -d -o root -g "$SERVICE_USER" -m 750 "$CONF_DIR"
install -d -o root -g root -m 700 "$BACKUP_DIR"

# --- Code --------------------------------------------------------------------
if [[ -d "$APP_DIR/.git" ]]; then
  info "Aktualisiere Code ($BRANCH) …"
  as_app git -C "$APP_DIR" remote set-url origin "$REPO_URL"
  as_app git -C "$APP_DIR" fetch --quiet origin "$BRANCH"
  as_app git -C "$APP_DIR" reset --quiet --hard "origin/$BRANCH"
else
  info "Lade JobForge von $REPO_URL …"
  rm -rf "$APP_DIR"
  as_app git -c init.defaultBranch=main clone --quiet --branch "$BRANCH" "$REPO_URL" "$APP_DIR"
fi
VERSION_INFO="$(as_app git -C "$APP_DIR" log -1 --format='%h (%cd)' --date=short)"
ok "Code bereit: $VERSION_INFO"

# --- Python-Umgebung ------------------------------------------------------------
info "Richte Python-Umgebung ein …"
[[ -x "$VENV/bin/python" ]] || as_app python3 -m venv "$VENV"
as_app "$VENV/bin/pip" install --quiet --upgrade pip wheel
as_app "$VENV/bin/pip" install --quiet -r "$APP_DIR/requirements.txt"
ok "Python-Abhängigkeiten installiert"

# --- Konfiguration --------------------------------------------------------------
IPS="$(hostname -I 2>/dev/null | tr ' ' '\n' | grep -v '^$' | grep -v ':' || true)"
if [[ ! -f "$ENV_FILE" ]]; then
  info "Erzeuge Konfiguration $ENV_FILE …"
  if [[ "$DB" == "postgres" ]]; then
    DB_URL="postgres://${SERVICE_USER}@%2Fvar%2Frun%2Fpostgresql/jobforge"
  else
    DB_URL="sqlite:///${DATA_DIR}/jobforge.sqlite3"
  fi
  cat > "$ENV_FILE" <<EOF
# JobForge Konfiguration – nach Änderungen: jobforge restart
DEBUG=0
SECRET_KEY=$(rand 60)
DATABASE_URL=${DB_URL}
DATA_DIR=${DATA_DIR}
ALLOWED_HOSTS=
CSRF_TRUSTED_ORIGINS=
HTTPS=0
TIME_ZONE=Europe/Berlin
GUNICORN_PORT=${PORT}
GUNICORN_WORKERS=$(( $(nproc) * 2 > 4 ? 4 : $(nproc) * 2 ))

# E-Mail-Versand (optional)
#EMAIL_HOST=smtp.example.com
#EMAIL_PORT=587
#EMAIL_HOST_USER=
#EMAIL_HOST_PASSWORD=
#EMAIL_USE_TLS=1
#DEFAULT_FROM_EMAIL=buero@example.com
EOF
fi
chown root:"$SERVICE_USER" "$ENV_FILE"
chmod 640 "$ENV_FILE"
PORT="$(grep -E '^GUNICORN_PORT=' "$ENV_FILE" | cut -d= -f2 || echo "$PORT")"

if [[ $UPDATE_ONLY -eq 0 ]]; then
  HOSTS="localhost,127.0.0.1"
  ORIGINS=""
  [[ -n "$DOMAIN" ]] && HOSTS="$DOMAIN,$HOSTS" && ORIGINS="https://$DOMAIN,http://$DOMAIN"
  for ip in $IPS; do HOSTS="$HOSTS,$ip"; ORIGINS="${ORIGINS:+$ORIGINS,}http://$ip"; done
  HOSTS="$HOSTS,$(hostname)"
  set_env ALLOWED_HOSTS "$HOSTS"
  set_env CSRF_TRUSTED_ORIGINS "$ORIGINS"
fi

# --- Datenbank ------------------------------------------------------------------
if grep -q '^DATABASE_URL=postgres' "$ENV_FILE"; then
  systemctl enable --now postgresql >/dev/null 2>&1 || true
  if ! runuser -u postgres -- psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='${SERVICE_USER}'" | grep -q 1; then
    info "Lege PostgreSQL-Datenbank an …"
    runuser -u postgres -- createuser "$SERVICE_USER"
  fi
  if ! runuser -u postgres -- psql -tAc "SELECT 1 FROM pg_database WHERE datname='jobforge'" | grep -q 1; then
    # template0 + UTF8: funktioniert auch, wenn der Cluster ohne System-Locale (SQL_ASCII) angelegt wurde
    runuser -u postgres -- createdb -O "$SERVICE_USER" -E UTF8 -T template0 --locale=C.UTF-8 jobforge 2>/dev/null       || runuser -u postgres -- createdb -O "$SERVICE_USER" -E UTF8 -T template0 --locale=C jobforge
  fi
  ok "PostgreSQL bereit (Zugriff per Unix-Socket, ohne Passwort)"
fi

info "Migriere Datenbank & sammle statische Dateien …"
manage migrate --noinput -v 0
manage collectstatic --noinput -v 0
ok "Datenbank aktuell"

ADMIN_OUT=""
if [[ $UPDATE_ONLY -eq 0 ]]; then
  ADMIN_OUT="$(manage jobforge_admin --if-none --username "$ADMIN_USER" --email "$ADMIN_EMAIL" || true)"
  if [[ "$DEMO" == "1" ]]; then manage jobforge_demo || warn "Beispieldaten konnten nicht angelegt werden"; fi
fi

# --- systemd --------------------------------------------------------------------
info "Richte Dienste ein …"
cat > /etc/systemd/system/jobforge.service <<EOF
[Unit]
Description=JobForge – Forge your workflow
After=network.target postgresql.service
Wants=postgresql.service

[Service]
Type=simple
User=${SERVICE_USER}
Group=${SERVICE_USER}
WorkingDirectory=${APP_DIR}
EnvironmentFile=${ENV_FILE}
Environment=JOBFORGE_ENV_FILE=${ENV_FILE} LANG=C.UTF-8 PYTHONUNBUFFERED=1
ExecStart=${VENV}/bin/gunicorn jobforge.wsgi:application --bind 127.0.0.1:\${GUNICORN_PORT} --workers \${GUNICORN_WORKERS} --threads 2 --timeout 120 --access-logfile - --error-logfile -
Restart=always
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ReadWritePaths=${DATA_DIR}

[Install]
WantedBy=multi-user.target
EOF

cat > /etc/systemd/system/jobforge-backup.service <<EOF
[Unit]
Description=JobForge Datensicherung

[Service]
Type=oneshot
ExecStart=/usr/local/bin/jobforge backup --quiet
EOF
cat > /etc/systemd/system/jobforge-backup.timer <<EOF
[Unit]
Description=Tägliche JobForge Datensicherung

[Timer]
OnCalendar=*-*-* 02:30:00
RandomizedDelaySec=900
Persistent=true

[Install]
WantedBy=timers.target
EOF

install -m 755 "$APP_DIR/scripts/jobforge-cli.sh" /usr/local/bin/jobforge
systemctl daemon-reload
systemctl enable --quiet jobforge.service jobforge-backup.timer
systemctl restart jobforge.service
systemctl start jobforge-backup.timer
ok "Dienst jobforge läuft"

# --- nginx -------------------------------------------------------------------------
if [[ "$WITH_NGINX" == "1" ]] && command -v nginx >/dev/null 2>&1; then
  SITE=/etc/nginx/sites-available/jobforge
  if [[ $UPDATE_ONLY -eq 0 || ! -f "$SITE" ]]; then
    info "Konfiguriere nginx …"
    SERVER_NAME="${DOMAIN:-_}"
    DEFAULT_FLAG=""
    [[ -z "$DOMAIN" ]] && DEFAULT_FLAG=" default_server"
    cat > "$SITE" <<EOF
# JobForge – erzeugt von install.sh
server {
    listen 80${DEFAULT_FLAG};
    listen [::]:80${DEFAULT_FLAG};
    server_name ${SERVER_NAME};

    client_max_body_size 50M;
    gzip on;
    gzip_types text/css application/javascript application/json image/svg+xml;

    location /static/ {
        alias ${APP_DIR}/staticfiles/;
        expires 30d;
        add_header Cache-Control "public";
        access_log off;
    }

    location / {
        proxy_pass http://127.0.0.1:${PORT};
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 120s;
    }
}
EOF
    ln -sf "$SITE" /etc/nginx/sites-enabled/jobforge
    [[ -z "$DOMAIN" ]] && rm -f /etc/nginx/sites-enabled/default
    nginx -t -q
    systemctl enable --quiet nginx
    systemctl reload nginx || systemctl restart nginx
    ok "nginx eingerichtet"

    if [[ -n "$DOMAIN" && -n "$EMAIL" ]] && command -v certbot >/dev/null 2>&1; then
      info "Beantrage TLS-Zertifikat für $DOMAIN …"
      if certbot --nginx -d "$DOMAIN" -m "$EMAIL" --agree-tos -n --redirect --quiet; then
        set_env HTTPS 1
        systemctl restart jobforge.service
        ok "HTTPS aktiv"
      else
        warn "Zertifikat konnte nicht ausgestellt werden (zeigt die Domain auf diesen Server?). Später: certbot --nginx -d $DOMAIN"
      fi
    fi
  fi
fi

# --- Funktionstest ---------------------------------------------------------------
for _ in $(seq 1 30); do
  if curl -fsS "http://127.0.0.1:${PORT}/health/" >/dev/null 2>&1; then break; fi
  sleep 1
done
curl -fsS "http://127.0.0.1:${PORT}/health/" >/dev/null 2>&1 || die "JobForge antwortet nicht. Logs: journalctl -u jobforge -n 50"

# --- Zusammenfassung --------------------------------------------------------------
if [[ -n "$DOMAIN" ]]; then
  if grep -q '^HTTPS=1' "$ENV_FILE"; then URL="https://$DOMAIN"; else URL="http://$DOMAIN"; fi
elif [[ "$WITH_NGINX" == "1" ]]; then
  URL="http://$(echo "$IPS" | head -n1)"
else
  URL="http://127.0.0.1:${PORT}"
fi
echo
echo -e "${c_ok}══════════════════════════════════════════════════════════════${c_off}"
echo -e "${c_ok}  JobForge ist bereit:${c_off}  $URL"
echo -e "${c_ok}══════════════════════════════════════════════════════════════${c_off}"
if [[ "$ADMIN_OUT" == *"JOBFORGE_ADMIN_PASSWORD="* ]]; then
  PW="$(echo "$ADMIN_OUT" | grep JOBFORGE_ADMIN_PASSWORD= | cut -d= -f2-)"
  umask 077
  printf 'Benutzer: %s\nPasswort: %s\n' "$ADMIN_USER" "$PW" > "$CONF_DIR/initial-admin.txt"
  echo "  Anmeldung:  Benutzer '$ADMIN_USER'  ·  Passwort '$PW'"
  echo "  (auch gespeichert in $CONF_DIR/initial-admin.txt – bitte nach dem ersten Login ändern)"
fi
echo
echo "  Verwaltung:  jobforge status | logs | update | backup | restore | manage …"
echo "  Konfiguration: $ENV_FILE   Daten: $DATA_DIR   Backups: $BACKUP_DIR"
echo
