from django.apps import AppConfig
from django.db.models.signals import post_migrate


def _after_migrate(sender, **kwargs):
    # Erst nach dem letzten App-Modul ausführen, damit alle Berechtigungen existieren.
    if sender.name != "api":
        return
    from .defaults import ensure_defaults

    ensure_defaults(verbosity=kwargs.get("verbosity", 1))


class CoreConfig(AppConfig):
    name = "core"
    verbose_name = "System"

    def ready(self):
        from . import signals

        signals.connect_all()
        post_migrate.connect(_after_migrate, dispatch_uid="jobforge-defaults")
