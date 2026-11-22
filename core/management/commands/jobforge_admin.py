import secrets

from django.contrib.auth.models import Group, User
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Legt einen Administrator an (falls noch keiner existiert) oder setzt dessen Passwort zurück."

    def add_arguments(self, parser):
        parser.add_argument("--username", default="admin")
        parser.add_argument("--email", default="")
        parser.add_argument("--password", default="", help="Leer = zufälliges Passwort erzeugen")
        parser.add_argument("--reset", action="store_true", help="Passwort eines bestehenden Benutzers neu setzen")
        parser.add_argument("--if-none", action="store_true", help="Nur anlegen, wenn noch kein Superuser existiert")

    def handle(self, *args, **opts):
        if opts["if_none"] and User.objects.filter(is_superuser=True).exists():
            self.stdout.write("Administrator existiert bereits – nichts zu tun.")
            return
        password = opts["password"] or secrets.token_urlsafe(12)
        user = User.objects.filter(username=opts["username"]).first()
        if user and not opts["reset"]:
            self.stderr.write(f"Benutzer '{user.username}' existiert bereits. --reset zum Zurücksetzen verwenden.")
            return
        if user is None:
            user = User(username=opts["username"], email=opts["email"])
        user.is_superuser = True
        user.is_staff = True
        user.is_active = True
        user.set_password(password)
        user.save()
        group = Group.objects.filter(name="Administrator").first()
        if group:
            user.groups.add(group)
        self.stdout.write(self.style.SUCCESS(f"JOBFORGE_ADMIN_USER={user.username}"))
        self.stdout.write(self.style.SUCCESS(f"JOBFORGE_ADMIN_PASSWORD={password}"))
