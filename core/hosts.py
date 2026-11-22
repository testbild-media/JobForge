"""
Öffentliche Adresse der Installation (Einstellungen › Firma & Branding).

Die Domain wird zur Laufzeit aus der Datenbank gelesen (kurz zwischengespeichert), damit
Host-Prüfung und CSRF-Schutz ohne Neustart funktionieren, wenn JobForge hinter einem
eigenen Reverse Proxy (Caddy, Nginx Proxy Manager, Traefik …) betrieben wird.
"""
import time
from urllib.parse import urlsplit

TTL_SECONDS = 15
_cache = {"time": -1e9, "url": ""}


def normalize_url(value):
    """'jobforge.example.com/' → 'https://jobforge.example.com'"""
    value = (value or "").strip().rstrip("/")
    if not value:
        return ""
    if "://" not in value:
        value = "https://" + value
    parts = urlsplit(value)
    scheme = parts.scheme.lower() if parts.scheme.lower() in ("http", "https") else "https"
    return f"{scheme}://{parts.netloc.lower()}"


def public_url():
    now = time.monotonic()
    if now - _cache["time"] > TTL_SECONDS:
        try:
            from .models import CompanySettings

            _cache["url"] = normalize_url(
                CompanySettings.objects.filter(pk=1).values_list("public_url", flat=True).first() or ""
            )
        except Exception:  # Datenbank noch nicht migriert
            _cache["url"] = ""
        _cache["time"] = now
    return _cache["url"]


def invalidate():
    _cache["time"] = -1e9


def public_host():
    url = public_url()
    return (urlsplit(url).hostname or "").lower() if url else ""


def public_origins():
    """Beide Schemata zulassen – falls der Proxy kein X-Forwarded-Proto sendet."""
    url = public_url()
    if not url:
        return set()
    netloc = urlsplit(url).netloc
    return {f"https://{netloc}", f"http://{netloc}"}
