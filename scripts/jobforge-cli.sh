#!/usr/bin/env bash
# JobForge Verwaltungsbefehl – wird von install.sh nach /usr/local/bin/jobforge kopiert.
set -Eeuo pipefail

PREFIX=/opt/jobforge
APP_DIR="$PREFIX/app"
VENV="$PREFIX/venv"
ENV_FILE=/etc/jobforge/jobforge.env
DATA_DIR=/var/lib/jobforge
BACKUP_DIR=/var/backups/jobforge
KEEP_BACKUPS="${JOBFORGE_KEEP_BACKUPS:-14}"
SERVICE_USER=jobforge

need_root() { [[ $EUID -eq 0 ]] || { echo "Bitte mit sudo ausführen." >&2; exit 1; }; }
as_app() { runuser -u "$SERVICE_USER" -- "$@"; }
manage() { as_app env JOBFORGE_ENV_FILE="$ENV_FILE" "$VENV/bin/python" "$APP_DIR/manage.py" "$@"; }
db_url() { grep -E '^DATABASE_URL=' "$ENV_FILE" | cut -d= -f2-; }

usage() {
  cat <<EOF
JobForge – Verwaltung

  jobforge status                 Dienststatus anzeigen
  jobforge start|stop|restart     Dienst steuern
  jobforge logs [-f]              Protokoll anzeigen
  jobforge update                 Auf neueste Version aktualisieren (inkl. Backup)
  jobforge backup [--quiet]       Datensicherung nach $BACKUP_DIR
  jobforge backups                Vorhandene Sicherungen auflisten
  jobforge restore DATEI          Sicherung wiederherstellen
  jobforge admin [BENUTZER]       Administrator anlegen bzw. Passwort zurücksetzen
  jobforge demo                   Beispieldaten anlegen
  jobforge manage BEFEHL …        Django-Verwaltungsbefehl ausführen
  jobforge config                 Konfigurationsdatei bearbeiten
  jobforge version                Installierte Version
EOF
}

cmd_backup() {
  need_root
  local quiet="${1:-}" stamp tmp file
  stamp="$(date +%Y%m%d-%H%M%S)"
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' RETURN
  if [[ "$(db_url)" == postgres* ]]; then
    as_app pg_dump -Fc -h /var/run/postgresql jobforge > "$tmp/database.dump"
  else
    local db="${DATA_DIR}/jobforge.sqlite3"
    as_app "$VENV/bin/python" -c "import sqlite3,sys; s=sqlite3.connect(sys.argv[1]); d=sqlite3.connect(sys.argv[2]); s.backup(d); d.close()" "$db" "$tmp/database.sqlite3"
  fi
  cp "$ENV_FILE" "$tmp/jobforge.env"
  tar -C "$DATA_DIR" -czf "$tmp/media.tar.gz" media
  as_app git -C "$APP_DIR" rev-parse HEAD > "$tmp/version.txt" 2>/dev/null || true
  file="$BACKUP_DIR/jobforge-$stamp.tar.gz"
  tar -C "$tmp" -czf "$file" .
  chmod 600 "$file"
  ls -1t "$BACKUP_DIR"/jobforge-*.tar.gz 2>/dev/null | tail -n +"$((KEEP_BACKUPS + 1))" | xargs -r rm -f
  [[ "$quiet" == "--quiet" ]] || echo "Sicherung erstellt: $file ($(du -h "$file" | cut -f1))"
}

cmd_restore() {
  need_root
  local file="${1:-}" tmp
  [[ -f "$file" ]] || { echo "Datei nicht gefunden: $file" >&2; exit 1; }
  read -r -p "Aktuelle Daten werden durch die Sicherung ersetzt. Fortfahren? [j/N] " ans </dev/tty || ans=""
  [[ "$ans" =~ ^[jJyY]$ ]] || { echo "Abgebrochen."; exit 1; }
  cmd_backup --quiet
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' RETURN
  tar -C "$tmp" -xzf "$file"
  systemctl stop jobforge
  if [[ -f "$tmp/database.dump" ]]; then
    runuser -u postgres -- dropdb --if-exists jobforge
    runuser -u postgres -- createdb -O "$SERVICE_USER" -E UTF8 -T template0 --locale=C.UTF-8 jobforge 2>/dev/null \
      || runuser -u postgres -- createdb -O "$SERVICE_USER" -E UTF8 -T template0 --locale=C jobforge
    as_app pg_restore -h /var/run/postgresql -d jobforge --no-owner "$tmp/database.dump"
  elif [[ -f "$tmp/database.sqlite3" ]]; then
    install -o "$SERVICE_USER" -g "$SERVICE_USER" -m 640 "$tmp/database.sqlite3" "$DATA_DIR/jobforge.sqlite3"
  fi
  rm -rf "${DATA_DIR:?}/media"
  tar -C "$DATA_DIR" -xzf "$tmp/media.tar.gz"
  chown -R "$SERVICE_USER:$SERVICE_USER" "$DATA_DIR/media"
  manage migrate --noinput -v 0
  systemctl start jobforge
  echo "Wiederherstellung abgeschlossen. (Die Konfiguration $ENV_FILE wurde nicht verändert; die gesicherte liegt im Archiv.)"
}

case "${1:-help}" in
  status) systemctl --no-pager status jobforge ;;
  start|stop|restart) need_root; systemctl "$1" jobforge; echo "jobforge: $1 ok" ;;
  logs) shift; journalctl -u jobforge --no-pager -n 200 "$@" ;;
  update)
    need_root
    cmd_backup --quiet && echo "Vorab-Sicherung erstellt."
    bash "$APP_DIR/install.sh" --update --repo "$(as_app git -C "$APP_DIR" remote get-url origin)" \
      --branch "$(as_app git -C "$APP_DIR" rev-parse --abbrev-ref HEAD)"
    ;;
  backup) shift; cmd_backup "${1:-}" ;;
  backups) ls -lh "$BACKUP_DIR" ;;
  restore) shift; cmd_restore "${1:-}" ;;
  admin) need_root; manage jobforge_admin --username "${2:-admin}" --reset ;;
  demo) need_root; manage jobforge_demo ;;
  manage) need_root; shift; manage "$@" ;;
  config) need_root; "${EDITOR:-nano}" "$ENV_FILE"; echo "Zum Übernehmen: jobforge restart" ;;
  version) as_app git -C "$APP_DIR" log -1 --format='JobForge %h vom %cd' --date=short ;;
  help|-h|--help) usage ;;
  *) usage; exit 1 ;;
esac
