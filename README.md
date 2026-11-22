# ⚒ JobForge – Forge your workflow

**JobForge** ist eine webbasierte Open-Source-Software zur Verwaltung und Organisation von Freelancern,
Selbstständigen sowie kleinen und mittelständischen Betrieben – besonders für technische Dienstleister
(Veranstaltungstechnik, Verleih, Handwerk, Service), aber branchenübergreifend einsetzbar.

Kunden, Projekte, Aufträge, Inventar, Vermietung, Verkauf, Personalplanung, Zeiterfassung und
Rechnungsstellung – zentral in einer Anwendung, selbst gehostet auf dem eigenen Server.

[![Lizenz: AGPL v3](https://img.shields.io/badge/Lizenz-AGPL%20v3-blue.svg)](LICENSE)

---

## Installation in einer Zeile

Auf einem frischen **Debian 12/13** oder **Ubuntu 22.04/24.04** Server (oder VPS):

```bash
curl -fsSL https://raw.githubusercontent.com/__GITHUB_OWNER__/JobForge/main/install.sh | sudo bash
```

Mit eigener Domain und automatischem HTTPS-Zertifikat (Let's Encrypt):

```bash
curl -fsSL https://raw.githubusercontent.com/__GITHUB_OWNER__/JobForge/main/install.sh | sudo bash -s -- --domain jobforge.example.com --email admin@example.com
```

Der Installer richtet alles ein: Python-Umgebung, PostgreSQL, Gunicorn als systemd-Dienst, nginx als
Reverse Proxy, tägliche Datensicherung und den Verwaltungsbefehl `jobforge`. Am Ende werden URL und
Zugangsdaten des ersten Administrators angezeigt (zusätzlich in `/etc/jobforge/initial-admin.txt`).

| Option | Bedeutung |
|---|---|
| `--domain NAME` | Domain für den nginx-vHost |
| `--email ADRESSE` | mit `--domain`: TLS-Zertifikat über Let's Encrypt beantragen |
| `--sqlite` | SQLite statt PostgreSQL (sehr kleine Installationen) |
| `--no-nginx` | kein nginx, Gunicorn lauscht nur auf `127.0.0.1:8000` |
| `--demo` | Beispieldaten anlegen (Kunden, Lager, Jobs, Personal, Rechnungen) |
| `--admin-user NAME` / `--admin-email MAIL` | erster Administrator |
| `--branch NAME` / `--repo URL` | andere Quelle (z. B. Fork) |

Mindestanforderung: 1 vCPU, 1 GB RAM, 5 GB Speicher. Empfohlen: 2 vCPU, 2 GB RAM.

### Verwaltung

```bash
jobforge status            # Dienststatus
jobforge logs -f           # Protokoll live
sudo jobforge update       # auf neueste Version aktualisieren (inkl. Vorab-Backup)
sudo jobforge backup       # Datensicherung nach /var/backups/jobforge (täglich automatisch)
sudo jobforge restore DATEI
sudo jobforge admin        # Admin anlegen bzw. Passwort zurücksetzen
sudo jobforge config       # Konfiguration bearbeiten (/etc/jobforge/jobforge.env)
```

### Docker

```bash
git clone https://github.com/__GITHUB_OWNER__/JobForge.git && cd JobForge
cp .env.example .env   # SECRET_KEY setzen, DEBUG=0
docker compose up -d
docker compose logs jobforge | grep JOBFORGE_ADMIN
```

---

## Funktionen (Version 1.0)

**Allgemein**
- Vollständig webbasiert, responsive, installierbar als **PWA** auf Smartphone und Tablet
- Firmen-Branding: Logo, Farben, Firmen-, Bank- und Steuerdaten
- Benutzer mit **Rollen und Berechtigungen** (Administrator, Büro, Projektleitung, Lager, Mitarbeiter – frei anpassbar)
- Eine Firma pro Installation mit beliebig vielen **Lagerstandorten**
- **Änderungsprotokoll** aller wichtigen Vorgänge (wer hat wann was geändert)
- Globale Suche inkl. Code-Erkennung (Gerät, Artikel, Lagerort, Job)

**Kunden & Lieferanten**
- Zentraler Kontaktstamm mit Ansprechpartnern, mehreren Adressen, Zahlungsbedingungen und Kundenrabatt
- Kundenhistorie mit Projekten, Jobs, Angeboten, Rechnungen, offenen Posten, Notizen und Dateien

**Inventar & Lager**
- Hierarchische Lagerstruktur: Standort › Gebäude › Raum › Regal › Fach/Schublade › Lagerplatz (auch Fahrzeuge, Cases)
- Artikel als **Einzelgerät** (mit Seriennummer), **Mengenartikel**, **Verbrauchsmaterial**, **Set/Bundle** oder Dienstleistung
- Einkaufs-, Miet-, Verkaufspreis und Wiederbeschaffungswert, Gruppen, Kategorien, Zusatzfelder
- **QR-/Barcode-Scan per Smartphone-Kamera** (oder Handscanner), druckbare QR-Etiketten
- Wareneingang, Ausgabe, Rücknahme, Umlagerung, Inventur – mit vollständiger Bewegungshistorie
- Reservierung über Jobs, **Packlisten**, scanbasierte Materialausgabe und -rücknahme
- Kennzeichnung von defektem, verlorenem oder nicht verfügbarem Material, Mindestbestände

**Projekte & Jobs**
- Projekte mit beliebig vielen Jobs/Aufträgen; Vermietung, Verkauf, Dienstleistung und Personal in einem Auftrag
- Positionen mit Gruppen/Überschriften, Rabatten, Steuersätzen und Miettagen; individuelle Status
- Material-, Personal- und Ressourcenplanung, Aufgaben, Termine, Notizen, **Dokumentenablage**
- **Vorlagen** für Projekte und Jobs – durchgängig von der Anfrage bis zur Abrechnung

**Angebote & Rechnungen**
- Angebot, Auftragsbestätigung, Rechnung, **Teil-, Abschlags- und Schlussrechnung**, Rechnungskorrektur/Storno
- **PDF** (WeasyPrint) mit gestaltbaren Layouts (Texte, Farben, eigenes CSS), GiroCode-QR für Überweisungen
- **XRechnung** (UBL 2.1, CIUS XRechnung 3.0) inkl. Leitweg-ID
- Individuelle **Nummernkreise**, Festschreiben (GoBD-orientiert), Gruppen-Zwischensummen, Gesamtrabatt
- Zahlungseingänge, Zahlungsstatus, offene Posten, Überfälligkeiten, E-Mail-Versand

**Kalender & Ressourcenplanung**
- Zentraler Kalender (Jobs, Termine, Einsätze, Abwesenheiten, Aufgaben) + iCal-Export
- **Verfügbarkeitsprüfung** für Material und Personal unter Berücksichtigung von Vorbereitungs- und Rückgabezeiten
- **Erkennung von Doppelbuchungen und Materialkonflikten** (Spitzenlast-Berechnung), standortbezogene Bestände

**Personal & Zeiterfassung**
- Mitarbeitende und Freelancer, Qualifikationen, Tätigkeitsbereiche, Stunden- und Tagessätze
- Wochen-Personalplan, Schichtzuweisung, Zu-/Absage durch die Person selbst, Abwesenheiten
- Zeiterfassung mit Stempeluhr, Zuordnung zu Jobs/Projekten, Freigabe, Übernahme in die Abrechnung

**Schnittstellen**
- Offene **REST-API** (Token-Authentifizierung) mit OpenAPI-Dokumentation unter `/api/docs/`
- **Webhooks** mit HMAC-SHA256-Signatur für automatisierte Abläufe
- CSV-Import/-Export (Excel-kompatibel), JSON-Vollsicherung
- Individuelle **Zusatzfelder** für Kontakte, Artikel, Geräte, Projekte, Jobs und Personal

### Geplant (1.x)
ZUGFeRD, Mahnwesen und Zahlungserinnerungen, Buchhaltungsexporte (DATEV) –
sowie optionale Add-ons: Materialprüfungen (Prüfintervalle, Prüfprotokolle), Offline-Inventar mit
Synchronisierung und erweiterte Auswertungen.

---

## API-Beispiel

```bash
curl -H "Authorization: Token <TOKEN>" https://jobforge.example.com/api/v1/jobs/
curl -H "Authorization: Token <TOKEN>" "https://jobforge.example.com/api/v1/availability/?article=3&start=2026-06-01T08:00:00&end=2026-06-03T18:00:00"
curl -X POST -H "Authorization: Token <TOKEN>" -H "Content-Type: application/json" \
     -d '{"code": "G000017", "mode": "out"}' https://jobforge.example.com/api/v1/jobs/12/scan/
```

Den persönlichen Token erzeugt jede Person unter *Benutzermenü › API-Zugang*. Webhooks senden
`{"event": "job.updated", "timestamp": "…", "data": {…}}` mit Header `X-JobForge-Signature: sha256=<hmac>`.

---

## Entwicklung

Voraussetzung: Python 3.11+ (für PDFs zusätzlich Pango, unter Debian/Ubuntu `libpango-1.0-0`).

```bash
git clone https://github.com/__GITHUB_OWNER__/JobForge.git && cd JobForge
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python manage.py migrate
python manage.py jobforge_demo        # optional: Beispieldaten
python manage.py jobforge_admin       # Administrator anlegen (Passwort wird ausgegeben)
python manage.py runserver
python manage.py test                 # Tests
```

**Aufbau:** Django 5.2 + Django REST Framework, serverseitig gerenderte Oberfläche ohne Build-Schritt
(eigenes CSS, kleines Vanilla-JS), PostgreSQL oder SQLite, WeasyPrint für PDFs.

| App | Inhalt |
|---|---|
| `core` | Firma/Branding, Nummernkreise, Steuern, Rollen, Änderungsprotokoll, Zusatzfelder, Webhooks, Import/Export, generisches CRUD |
| `contacts` | Kunden, Lieferanten, Ansprechpartner, Adressen |
| `inventory` | Lagerorte, Artikel, Sets, Einzelgeräte, Bestände, Bewegungen, Scanner, Etiketten |
| `projects` | Projekte, Jobs, Positionen, Status, Aufgaben, Termine, Vorlagen, Packlisten |
| `billing` | Angebote, Rechnungen, Layouts, PDF, XRechnung, Zahlungen |
| `staff` | Personal, Qualifikationen, Abwesenheiten, Einsätze, Zeiterfassung |
| `planning` | Verfügbarkeit, Konflikterkennung, Kalender, iCal |
| `api` | REST-API |

Beiträge sind willkommen – bitte Issues und Pull Requests auf GitHub nutzen.

## Lizenz

JobForge steht unter der [GNU Affero General Public License v3.0](LICENSE) (AGPL-3.0-or-later).
Wer JobForge verändert und als Dienst über ein Netzwerk anbietet, muss den Quellcode der veränderten
Version den Nutzern zugänglich machen.
