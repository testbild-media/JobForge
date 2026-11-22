from pathlib import Path

from django.conf import settings

from .models import CompanySettings

_ASSETS = [Path(settings.BASE_DIR) / "static" / p for p in ("css/app.css", "js/app.js", "js/scanner.js")]


def asset_version():
    """Produktiv: Versionsnummer. In der Entwicklung: Änderungszeit der Assets (Cache-Busting)."""
    if not settings.DEBUG:
        return settings.VERSION
    try:
        return f"{settings.VERSION}-{int(max(p.stat().st_mtime for p in _ASSETS))}"
    except OSError:
        return settings.VERSION


def jobforge(request):
    try:
        company = CompanySettings.get()
    except Exception:  # Datenbank noch nicht migriert
        company = None
    return {
        "company": company,
        "JOBFORGE_VERSION": settings.VERSION,
        "ASSET_VERSION": asset_version(),
    }
