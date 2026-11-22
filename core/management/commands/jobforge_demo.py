"""Beispieldaten für Test und Vorführung: python manage.py jobforge_demo"""
import datetime
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from billing import services as billing
from contacts.models import Contact, ContactPerson
from core.models import CompanySettings
from inventory import services as inv
from inventory.models import Article, ArticleGroup, Category, Location, SetComponent
from projects.models import Job, JobPosition, JobStatus, Project, Task
from staff.models import Assignment, Availability, Employee, Qualification, TimeEntry


class Command(BaseCommand):
    help = "Legt Beispieldaten an (Firma, Kunden, Lager, Artikel, Jobs, Personal, Dokumente)."

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true", help="Auch anlegen, wenn bereits Daten existieren")

    @transaction.atomic
    def handle(self, *args, **opts):
        if Contact.objects.exists() and not opts["force"]:
            self.stdout.write("Es existieren bereits Daten – Abbruch (mit --force trotzdem anlegen).")
            return
        tz_now = timezone.localtime().replace(minute=0, second=0, microsecond=0)

        def at(days, hour):
            return (tz_now + datetime.timedelta(days=days)).replace(hour=hour)

        c = CompanySettings.get()
        if c.name == "Meine Firma":
            c.name = "Forge Eventtechnik GmbH"
            c.owner = "Max Mustermann"
            c.street, c.zip_code, c.city = "Werkstraße 12", "50667", "Köln"
            c.phone, c.email, c.website = "+49 221 123456", "info@forge-event.example", "www.forge-event.example"
            c.vat_id, c.tax_number = "DE123456789", "215/5678/1234"
            c.bank_name, c.iban, c.bic = "Musterbank Köln", "DE02120300000000202051", "BYLADEM1001"
            c.register_court, c.register_number = "Amtsgericht Köln", "HRB 12345"
            c.save()

        # Lager
        hq = Location.objects.create(name="Hauptlager Köln", kind="site", address="Werkstraße 12, 50667 Köln")
        hall = Location.objects.create(name="Halle A", kind="building", parent=hq)
        shelf1 = Location.objects.create(name="Regal 1", kind="shelf", parent=hall)
        shelf2 = Location.objects.create(name="Regal 2", kind="shelf", parent=hall)
        cable = Location.objects.create(name="Kabelwand", kind="bin", parent=hall)
        Location.objects.create(name="Transporter K-FG 123", kind="vehicle")
        second = Location.objects.create(name="Außenlager Bonn", kind="site")

        light = ArticleGroup.objects.create(name="Lichttechnik", color="#f59e0b")
        sound = ArticleGroup.objects.create(name="Tontechnik", color="#0ea5e9")
        rig = ArticleGroup.objects.create(name="Rigging & Bühne", color="#64748b")
        cons = ArticleGroup.objects.create(name="Verbrauchsmaterial", color="#22c55e")
        cat = Category.objects.create(name="Veranstaltungstechnik")

        def art(name, kind, group, rent=None, sale=None, buy=None, unit="Stk", **kw):
            return Article.objects.create(name=name, kind=kind, group=group, category=cat, rental_price=rent,
                                          sale_price=sale, purchase_price=buy, unit=unit, **kw)

        mh = art("Moving Head Spot 300W", "serial", light, rent=Decimal("45"), buy=Decimal("1890"),
                 manufacturer="BeamCo", default_location=shelf1)
        par = art("LED PAR RGBW", "serial", light, rent=Decimal("12"), buy=Decimal("220"), default_location=shelf1)
        speaker = art('Aktivlautsprecher 12"', "serial", sound, rent=Decimal("35"), buy=Decimal("980"),
                      default_location=shelf2)
        mixer = art("Digitalmischpult 32 Kanäle", "serial", sound, rent=Decimal("150"), buy=Decimal("4200"),
                    default_location=shelf2)
        truss = art("Traverse 2 m (3-Punkt)", "bulk", rig, rent=Decimal("8"), buy=Decimal("180"), default_location=hall)
        xlr = art("XLR-Kabel 10 m", "bulk", sound, rent=Decimal("2"), buy=Decimal("14"), default_location=cable)
        tape = art("Gaffa Tape schwarz", "consumable", cons, sale=Decimal("12.90"), buy=Decimal("6.50"), unit="Rolle",
                   sellable=True, rentable=False, min_stock=Decimal("10"), default_location=shelf2)
        tech = art("Veranstaltungstechniker", "service", None, sale=Decimal("55"), unit="Std", rentable=False)
        pa_set = art("PA-Set klein (2 Boxen + Kabel)", "set", sound, rent=Decimal("80"))
        SetComponent.objects.create(set_article=pa_set, component=speaker, quantity=2)
        SetComponent.objects.create(set_article=pa_set, component=xlr, quantity=4)

        inv.receive(mh, 4, shelf1, serials=["MH-1001", "MH-1002", "MH-1003", "MH-1004"])
        inv.receive(par, 12, shelf1)
        inv.receive(speaker, 6, shelf2)
        inv.receive(mixer, 1, shelf2, serials=["DM32-77801"])
        inv.receive(truss, 20, hall)
        inv.receive(truss, 8, second)
        inv.receive(xlr, 40, cable)
        inv.receive(tape, 24, shelf2)
        unit = par.units.last()
        inv.set_unit_condition(unit, "defective", note="Lüfter defekt")

        # Kontakte
        k1 = Contact.objects.create(company_name="Stadtwerke Musterstadt", street="Rathausplatz 1", zip_code="50668",
                                    city="Köln", email="einkauf@stadtwerke.example", phone="0221 99999",
                                    leitweg_id="05315-12345-67")
        ContactPerson.objects.create(contact=k1, first_name="Anna", last_name="Schmidt", position="Veranstaltungen",
                                     email="a.schmidt@stadtwerke.example", is_primary=True)
        k2 = Contact.objects.create(company_name="Agentur Lichtblick", street="Medienpark 5", zip_code="50670",
                                    city="Köln", email="hallo@lichtblick.example", discount_percent=Decimal("5"))
        k3 = Contact.objects.create(is_company=False, first_name="Julia", last_name="Weber", street="Gartenweg 3",
                                    zip_code="53111", city="Bonn", email="julia.weber@example.com")
        Contact.objects.create(company_name="Technik-Großhandel Nord", contact_type="supplier", city="Hamburg",
                               email="vertrieb@grosshandel.example")

        # Personal
        q_light = Qualification.objects.create(name="Lichttechnik")
        q_sound = Qualification.objects.create(name="Tontechnik")
        q_rig = Qualification.objects.create(name="Rigger (SQQ2)")
        demo_user, created = User.objects.get_or_create(username="techniker", defaults={
            "first_name": "Tom", "last_name": "Becker", "email": "tom@forge-event.example"})
        if created:
            demo_user.set_password("demo-techniker-123")
            demo_user.save()
            g = Group.objects.filter(name="Mitarbeiter").first()
            if g:
                demo_user.groups.add(g)
        e1 = Employee.objects.create(first_name="Tom", last_name="Becker", user=demo_user, position="Licht & Rigging",
                                     hourly_rate=Decimal("55"), daily_rate=Decimal("420"), hourly_cost=Decimal("28"),
                                     color="#f59e0b")
        e1.qualifications.set([q_light, q_rig])
        e2 = Employee.objects.create(first_name="Sara", last_name="Klein", position="Tontechnik", kind="freelancer",
                                     hourly_rate=Decimal("60"), daily_rate=Decimal("480"), hourly_cost=Decimal("40"),
                                     color="#0ea5e9")
        e2.qualifications.set([q_sound])
        e3 = Employee.objects.create(first_name="Jonas", last_name="Wolf", position="Lager / Fahrer", kind="parttime",
                                     hourly_rate=Decimal("38"), hourly_cost=Decimal("17"), color="#22c55e")
        Availability.objects.create(employee=e3, kind="vacation", start=(tz_now + datetime.timedelta(days=10)).date(),
                                    end=(tz_now + datetime.timedelta(days=17)).date())

        confirmed = JobStatus.objects.filter(name="Bestätigt").first()
        offer = JobStatus.objects.filter(name="Angebot").first()

        project = Project.objects.create(name="Sommerfest Stadtwerke", customer=k1, start_date=at(5, 0).date(),
                                         end_date=at(7, 0).date(), budget=Decimal("8500"))
        j1 = Job.objects.create(title="Sommerfest – Bühne & Beschallung", project=project, customer=k1,
                                status=confirmed, warehouse=hq, venue="Rheinpark Köln",
                                prep_start=at(4, 8), start=at(5, 14), end=at(6, 23), return_end=at(7, 18))
        j2 = Job.objects.create(title="Firmenjubiläum Lichtblick", customer=k2, status=offer, warehouse=hq,
                                venue="Lichtblick Loft", start=at(6, 10), end=at(6, 23))
        j3 = Job.objects.create(title="Hochzeit Weber – Licht", customer=k3, status=confirmed, venue="Gut Rosenhof",
                                start=at(12, 12), end=at(13, 3))

        def pos(job, order, kind, article=None, desc="", qty=1, price=None, unit="Stk", factor=None):
            JobPosition.objects.create(
                job=job, order=order, kind=kind, article=article, description=desc or (article.name if article else ""),
                quantity=Decimal(qty), unit=unit if not article else article.unit,
                unit_price=price if price is not None else (article.price_for(kind) if article else 0),
                factor=factor if factor is not None else (job.calc_days if kind == "rental" else 1),
            )

        pos(j1, 10, "heading", desc="Beschallung")
        pos(j1, 20, "rental", pa_set, qty=2)
        pos(j1, 30, "rental", mixer)
        pos(j1, 40, "heading", desc="Licht & Bühne")
        pos(j1, 50, "rental", mh, qty=4)
        pos(j1, 60, "rental", truss, qty=12)
        pos(j1, 70, "sale", tape, qty=4)
        pos(j1, 80, "heading", desc="Personal & Logistik")
        pos(j1, 90, "staff", tech, qty=16, desc="Veranstaltungstechniker Auf-/Abbau", unit="Std")
        pos(j1, 100, "service", desc="Transport & Anfahrt", price=Decimal("180"), unit="pauschal")

        pos(j2, 10, "rental", mh, qty=2)  # erzeugt Konflikt mit j1 (nur 4 Moving Heads)
        pos(j2, 20, "rental", par, qty=10)
        pos(j2, 30, "rental", speaker, qty=2)
        pos(j3, 10, "rental", par, qty=8)
        pos(j3, 20, "service", desc="Lichtdesign & Betreuung", price=Decimal("450"), unit="pauschal")

        Assignment.objects.create(job=j1, employee=e1, role="Licht & Rigging", qualification=q_rig, start=at(4, 8),
                                  end=at(4, 18), status="confirmed")
        Assignment.objects.create(job=j1, employee=e2, role="FOH Ton", qualification=q_sound, start=at(5, 12),
                                  end=at(6, 23), status="requested", rate_type="daily")
        Assignment.objects.create(job=j1, employee=e1, role="Lichtbetreuung Show", start=at(6, 12), end=at(6, 23),
                                  status="confirmed")
        Assignment.objects.create(job=j2, employee=e1, role="Licht", start=at(6, 9), end=at(6, 23))  # Doppelbuchung
        Task.objects.create(job=j1, title="Bühnenplan vom Kunden anfordern", due_date=at(1, 0).date(), assignee=None)
        Task.objects.create(job=j1, title="Stromanschlüsse vor Ort klären", due_date=at(3, 0).date())
        TimeEntry.objects.create(employee=e3, job=j1, date=tz_now.date(), start_time=datetime.time(8, 0),
                                 end_time=datetime.time(12, 30), break_minutes=15, activity="Material kommissioniert")

        quote = billing.document_from_job(j1, "quote")
        quote.finalize()
        inv_doc = billing.document_from_job(j3, "invoice")
        inv_doc.date = tz_now.date() - datetime.timedelta(days=20)
        inv_doc.save()
        inv_doc.finalize()

        self.stdout.write(self.style.SUCCESS(
            "Beispieldaten angelegt. Demo-Login Mitarbeiter: techniker / demo-techniker-123"))
