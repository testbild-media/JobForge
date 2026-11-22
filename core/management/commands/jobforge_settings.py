from django.core.management.base import BaseCommand

from core.models import CompanySettings


class Command(BaseCommand):
    help = "Systemeinstellungen setzen, z. B. die öffentliche Adresse: --public-url https://jobforge.firma.de"

    def add_arguments(self, parser):
        parser.add_argument("--public-url", help="Adresse, unter der JobForge erreichbar ist ('' = leeren)")

    def handle(self, *args, **opts):
        company = CompanySettings.get()
        if opts["public_url"] is not None:
            company.public_url = opts["public_url"]
            company.save()
        self.stdout.write(f"Adresse der Installation: {company.public_url or '(nicht gesetzt)'}")
