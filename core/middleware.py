import threading
from urllib.parse import urlsplit

from django.conf import settings
from django.http import HttpResponseBadRequest
from django.http.request import split_domain_port, validate_host
from django.middleware.csrf import CsrfViewMiddleware

from .hosts import public_host, public_origins

_local = threading.local()


def get_current_user():
    user = getattr(_local, "user", None)
    if user is not None and getattr(user, "is_authenticated", False):
        return user
    return None


def set_current_user(user):
    _local.user = user


class CurrentUserMiddleware:
    """Merkt sich den angemeldeten Benutzer für das Änderungsprotokoll."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        set_current_user(getattr(request, "user", None))
        try:
            return self.get_response(request)
        finally:
            set_current_user(None)


class HostCheckMiddleware:
    """
    Prüft den Host-Header gegen die Basisliste (ALLOWED_HOSTS aus der Konfiguration: localhost,
    Server-IPs …) plus die in der Oberfläche eingetragene Domain. Solange keine Domain eingetragen
    ist, wird jeder Host akzeptiert, damit die Ersteinrichtung hinter einem Reverse Proxy klappt.
    Setzt außerdem Session-/CSRF-Cookies auf „Secure“, wenn die Anfrage per HTTPS kam.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        base = list(getattr(settings, "JOBFORGE_ALLOWED_HOSTS", []))
        domain = public_host()
        if domain and "*" not in base and request.path != "/health/":
            host, _port = split_domain_port(request.get_host())
            if not host or not validate_host(host, base + [domain]):
                return HttpResponseBadRequest(
                    f"Unbekannte Domain „{request.get_host()}“. JobForge ist für „{domain}“ eingerichtet "
                    "(Einstellungen › Firma & Branding › Adresse der Installation).",
                    content_type="text/plain; charset=utf-8",
                )
        response = self.get_response(request)
        if request.is_secure():
            for name in (settings.SESSION_COOKIE_NAME, settings.CSRF_COOKIE_NAME):
                if name in response.cookies:
                    response.cookies[name]["secure"] = True
        return response


class CsrfMiddleware(CsrfViewMiddleware):
    """CSRF-Schutz, der zusätzlich die in der Oberfläche eingetragene Adresse als vertrauenswürdig kennt."""

    @property
    def allowed_origins_exact(self):
        return {o for o in settings.CSRF_TRUSTED_ORIGINS if "*" not in o} | public_origins()

    @property
    def csrf_trusted_origins_hosts(self):
        return [urlsplit(o).netloc.lstrip("*") for o in settings.CSRF_TRUSTED_ORIGINS] + [
            urlsplit(o).netloc for o in public_origins()
        ]
