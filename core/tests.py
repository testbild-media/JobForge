"""Smoke- und Ablauftests für JobForge: python manage.py test"""
import datetime
import json
from decimal import Decimal
from xml.etree import ElementTree as ET

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from billing import services as billing
from billing.models import Document
from contacts.models import Contact
from core.crud import Crud
from inventory import services as inv
from inventory.models import Article, Location, Unit
from planning.availability import article_availability, job_material_check, material_conflicts, staff_conflicts
from projects.models import Job


def all_cruds():
    seen, stack = [], list(Crud.__subclasses__())
    while stack:
        cls = stack.pop()
        stack.extend(cls.__subclasses__())
        if cls.model is not None and cls.name:
            seen.append(cls)
    return seen


class SmokeTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("jobforge_demo", verbosity=0)
        cls.admin = User.objects.create_superuser("root", "root@example.com", "pw-root-123")

    def setUp(self):
        self.client.force_login(self.admin)

    def get_ok(self, url):
        resp = self.client.get(url)
        self.assertIn(resp.status_code, (200, 302), f"{url} -> {resp.status_code}")
        return resp

    def test_all_crud_pages(self):
        for crud in all_cruds():
            with self.subTest(crud=crud.__name__):
                self.get_ok(crud.url("list"))
                self.get_ok(crud.url("list") + "?q=a")
                self.get_ok(crud.url("create"))
                obj = crud.model._default_manager.first()
                if obj is not None:
                    self.get_ok(crud.url("update", obj.pk))
                    self.get_ok(crud.url("delete", obj.pk))
                    if crud.has_detail:
                        self.get_ok(crud.url("detail", obj.pk))

    def test_custom_pages(self):
        job = Job.objects.filter(is_template=False).first()
        doc = Document.objects.first()
        urls = [
            "/", "/suche/?q=Moving", "/einstellungen/", "/einstellungen/firma/", "/einstellungen/api/",
            "/einstellungen/import-export/", "/einstellungen/backup/", "/manifest.webmanifest", "/sw.js", "/offline/",
            "/health/",
            reverse("inventory:receive"), reverse("inventory:transfer"), reverse("inventory:adjust"),
            reverse("inventory:bulk_condition"), reverse("inventory:defects"), reverse("inventory:scan"),
            reverse("inventory:labels"), reverse("inventory:labels") + "?kind=article",
            reverse("inventory:labels") + "?kind=location", reverse("inventory:qr", args=["G000001"]),
            reverse("inventory:availability"),
            reverse("inventory:availability") + "?start=2026-01-01T08:00&end=2026-12-31T08:00",
            reverse("inventory:article_lookup") + f"?id={Article.objects.first().pk}",
            reverse("projects:job_positions", args=[job.pk]), reverse("projects:job_packlist", args=[job.pk]),
            reverse("projects:job_scan", args=[job.pk]), reverse("projects:job_from_template"),
            reverse("billing:document_positions", args=[Document.objects.filter(finalized_at=None).first().pk]
                    if Document.objects.filter(finalized_at=None).exists() else [doc.pk]),
            reverse("billing:document_preview", args=[doc.pk]), reverse("billing:document_pdf", args=[doc.pk]),
            reverse("billing:open_items"), reverse("billing:document_send", args=[doc.pk]),
            reverse("staff:planner"), reverse("staff:my_assignments"), reverse("staff:free_staff"),
            reverse("staff:free_staff") + "?start=2026-01-01T08:00&end=2026-01-02T08:00",
            reverse("planning:calendar"), reverse("planning:calendar") + "?l=jobs&l=assignments&l=absences",
            reverse("planning:conflicts"), reverse("planning:ics"),
            "/api/v1/", "/api/v1/jobs/", "/api/v1/articles/", "/api/v1/documents/", "/api/v1/me/",
            "/api/schema/", "/api/docs/",
        ]
        for name in ["contacts", "articles", "units", "stock", "jobs", "documents", "timeentries", "employees"]:
            urls.append(reverse("core:export", args=[name]))
        for url in urls:
            with self.subTest(url=url):
                self.get_ok(url)

    def test_login_required(self):
        self.client.logout()
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/login/", resp["Location"])
        self.assertEqual(self.client.get("/login/").status_code, 200)


class FlowTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("jobforge_demo", verbosity=0)
        cls.admin = User.objects.create_superuser("root", "root@example.com", "pw-root-123")

    def setUp(self):
        self.client.force_login(self.admin)
        self.job = Job.objects.get(title__startswith="Sommerfest")

    def test_conflicts_detected(self):
        conflicts = material_conflicts(timezone.now(), timezone.now() + datetime.timedelta(days=30))
        names = [c["article"].name for c in conflicts]
        self.assertIn("Moving Head Spot 300W", names)
        staff = staff_conflicts(timezone.now(), timezone.now() + datetime.timedelta(days=30))
        self.assertTrue(any(c["type"] == "double" for c in staff))

    def test_set_expansion_and_availability(self):
        req = {a.name: q for a, q in self.job.material_requirements().items()}
        self.assertEqual(req['Aktivlautsprecher 12"'], Decimal("4"))
        self.assertEqual(req["XLR-Kabel 10 m"], Decimal("8"))
        rows = job_material_check(self.job)
        self.assertTrue(rows)
        mh = Article.objects.get(name="Moving Head Spot 300W")
        av = article_availability(mh, self.job.period_start, self.job.period_end, exclude_job=self.job)
        self.assertEqual(av["capacity"], Decimal("4"))

    def test_checkout_and_return(self):
        unit = Unit.objects.filter(article__name="Moving Head Spot 300W").first()
        resp = self.client.post(reverse("projects:job_scan", args=[self.job.pk]),
                                {"code": unit.code, "mode": "out", "quantity": "1"})
        self.assertEqual(resp.status_code, 302)
        unit.refresh_from_db()
        self.assertEqual(unit.current_job, self.job)
        truss = Article.objects.get(name__startswith="Traverse")
        before = truss.usable_quantity()
        inv.checkout(self.job, article=truss, quantity=5)
        self.assertEqual(truss.usable_quantity(), before - 5)
        inv.checkin(self.job, article=truss, quantity=5, defective=False)
        self.assertEqual(truss.usable_quantity(), before)
        self.client.post(reverse("projects:job_scan", args=[self.job.pk]),
                         {"code": unit.code, "mode": "return", "quantity": "1", "defective": "on"})
        unit.refresh_from_db()
        self.assertIsNone(unit.current_job)
        self.assertEqual(unit.condition, "defective")
        with self.assertRaises(inv.InventoryError):
            inv.checkout(self.job, unit=unit)

    def test_quote_to_invoice_flow(self):
        quote = billing.document_from_job(self.job, "quote")
        self.assertIsNone(quote.number)
        totals = quote.totals()
        self.assertGreater(totals["gross"], 0)
        self.assertEqual(totals["gross"], totals["net_total"] + totals["tax_total"])
        self.client.post(reverse("billing:document_finalize", args=[quote.pk]))
        quote.refresh_from_db()
        self.assertTrue(quote.number.startswith("AN"))
        # Abschlag 30 %
        resp = self.client.post(reverse("billing:document_from_job", args=[self.job.pk]),
                                {"doc_type": "advance", "percent": "30"})
        self.assertEqual(resp.status_code, 302)
        advance = Document.objects.filter(doc_type="advance", job=self.job).latest("pk")
        self.assertEqual(advance.totals()["net_total"], (totals["lines_net"] * Decimal("0.3")).quantize(Decimal("0.01")))
        advance.finalize()
        # Schlussrechnung zieht Abschlag ab
        final = billing.convert(quote, "final")
        final.finalize()
        ft = final.totals()
        self.assertEqual(ft["prepaid"], advance.totals()["gross"])
        self.assertEqual(ft["amount_due"], ft["gross"] - ft["prepaid"])
        # XRechnung
        resp = self.client.get(reverse("billing:document_xrechnung", args=[final.pk]))
        self.assertEqual(resp.status_code, 200)
        root = ET.fromstring(resp.content)
        ns = {"cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
              "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"}
        payable = Decimal(root.find("cac:LegalMonetaryTotal/cbc:PayableAmount", ns).text)
        self.assertEqual(payable, ft["amount_due"])
        line_sum = sum(Decimal(e.text) for e in root.findall("cac:InvoiceLine/cbc:LineExtensionAmount", ns))
        self.assertEqual(line_sum, Decimal(root.find("cac:LegalMonetaryTotal/cbc:LineExtensionAmount", ns).text))
        # Zahlung
        self.client.post(reverse("billing:payment_add", args=[final.pk]),
                         {"document": final.pk, "date": timezone.localdate().isoformat(),
                          "amount": str(ft["amount_due"]), "method": "transfer"})
        final.refresh_from_db()
        self.assertEqual(final.status, "paid")
        # Storno
        credit = billing.cancel_invoice(advance)
        self.assertEqual(credit.doc_type, "credit")
        advance.refresh_from_db()
        self.assertEqual(advance.status, "cancelled")

    def test_positions_editor_post(self):
        job = Job.objects.get(title__startswith="Hochzeit")
        positions = list(job.positions.all())
        data = {"pos-TOTAL_FORMS": str(len(positions) + 1), "pos-INITIAL_FORMS": str(len(positions)),
                "pos-MIN_NUM_FORMS": "0", "pos-MAX_NUM_FORMS": "1000"}
        for i, p in enumerate(positions):
            data.update({f"pos-{i}-id": p.pk, f"pos-{i}-job": job.pk, f"pos-{i}-order": p.order,
                         f"pos-{i}-kind": p.kind, f"pos-{i}-article": p.article_id or "",
                         f"pos-{i}-description": p.description, f"pos-{i}-quantity": p.quantity,
                         f"pos-{i}-unit": p.unit, f"pos-{i}-unit_price": p.unit_price, f"pos-{i}-factor": p.factor,
                         f"pos-{i}-discount": p.discount, f"pos-{i}-tax_rate": p.tax_rate})
        n = len(positions)
        data.update({f"pos-{n}-job": job.pk, f"pos-{n}-order": 99, f"pos-{n}-kind": "service",
                     f"pos-{n}-description": "Extra", f"pos-{n}-quantity": "2", f"pos-{n}-unit": "Std",
                     f"pos-{n}-unit_price": "50", f"pos-{n}-factor": "1", f"pos-{n}-discount": "0",
                     f"pos-{n}-tax_rate": "19"})
        resp = self.client.post(reverse("projects:job_positions", args=[job.pk]), data)
        self.assertEqual(resp.status_code, 302, getattr(resp, "context", None) and resp.context.get("formset").errors)
        self.assertEqual(job.positions.count(), n + 1)

    def test_api_token_and_scan(self):
        from rest_framework.authtoken.models import Token

        token = Token.objects.create(user=self.admin)
        self.client.logout()
        h = {"HTTP_AUTHORIZATION": f"Token {token.key}"}
        resp = self.client.get("/api/v1/jobs/", **h)
        self.assertEqual(resp.status_code, 200)
        self.assertGreaterEqual(resp.json()["count"], 3)
        unit = Unit.objects.filter(condition="ok", current_job=None).first()
        resp = self.client.post(f"/api/v1/jobs/{self.job.pk}/scan/", data=json.dumps({"code": unit.code}),
                                content_type="application/json", **h)
        self.assertEqual(resp.status_code, 201, resp.content)
        resp = self.client.get(f"/api/v1/scan/?code={unit.code}", **h)
        self.assertEqual(resp.json()["type"], "unit")
        resp = self.client.post("/api/v1/contacts/", data=json.dumps({"company_name": "API GmbH"}),
                                content_type="application/json", **h)
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertTrue(Contact.objects.filter(company_name="API GmbH").exists())

    def test_permissions_employee_role(self):
        user = User.objects.get(username="techniker")
        self.client.force_login(user)
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(self.client.get(reverse("billing:document_list")).status_code, 403)
        self.assertEqual(self.client.get(reverse("projects:job_list")).status_code, 200)
        self.assertEqual(self.client.get(reverse("staff:timeentry_list")).status_code, 200)
        self.assertEqual(self.client.get(reverse("staff:my_assignments")).status_code, 200)
        self.assertEqual(self.client.get("/api/v1/documents/").status_code, 403)

    def test_template_and_import(self):
        resp = self.client.post(reverse("projects:job_duplicate", args=[self.job.pk]), {"template": "1"})
        self.assertEqual(resp.status_code, 302)
        tpl = Job.objects.filter(is_template=True).latest("pk")
        self.assertEqual(tpl.positions.count(), self.job.positions.count())
        resp = self.client.post(reverse("projects:job_from_template"), {"template": tpl.pk, "title": "Neu aus Vorlage"})
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(Job.objects.filter(title="Neu aus Vorlage", is_template=False).exists())
        from django.core.files.uploadedfile import SimpleUploadedFile

        csv = "number;name;kind;rental_price\n;Nebelmaschine;bulk;25,50\n".encode("utf-8")
        resp = self.client.post(reverse("core:import_export"), {"target": "articles", "update_existing": "on",
                                                                "file": SimpleUploadedFile("a.csv", csv)})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Article.objects.get(name="Nebelmaschine").rental_price, Decimal("25.50"))

    def test_location_tree_and_numbering(self):
        root = Location.objects.create(name="Testlager")
        child = Location.objects.create(name="Raum 1", parent=root, kind="room")
        self.assertEqual(child.path, "Testlager › Raum 1")
        root.name = "Umbenannt"
        root.save()
        child.refresh_from_db()
        self.assertEqual(child.path, "Umbenannt › Raum 1")
        c = Contact.objects.create(company_name="Nummer Test")
        self.assertTrue(c.number.startswith("K"))


class PublicUrlTest(TestCase):
    """Domain aus der Oberfläche: Host-Prüfung, CSRF hinter Reverse Proxy, Secure-Cookies."""

    def setUp(self):
        from core.hosts import invalidate
        from core.models import CompanySettings

        invalidate()
        self.addCleanup(invalidate)  # DB wird nach jedem Test zurückgerollt – Cache ebenfalls leeren
        self.company = CompanySettings.get()
        User.objects.create_user("proxyuser", password="pw-proxy-123")

    def set_url(self, url):
        self.company.public_url = url
        self.company.save()

    def test_setup_mode_accepts_any_host(self):
        self.assertEqual(self.client.get("/login/", HTTP_HOST="irgendwas.example").status_code, 200)

    def test_url_is_normalized(self):
        self.set_url("JobForge.Firma.de/")
        self.company.refresh_from_db()
        self.assertEqual(self.company.public_url, "https://jobforge.firma.de")

    def test_host_check(self):
        self.set_url("https://jobforge.firma.de")
        self.assertEqual(self.client.get("/login/", HTTP_HOST="jobforge.firma.de").status_code, 200)
        self.assertEqual(self.client.get("/login/", HTTP_HOST="localhost:8000").status_code, 200)
        self.assertEqual(self.client.get("/login/", HTTP_HOST="boese.example").status_code, 400)
        self.assertEqual(self.client.get("/health/", HTTP_HOST="boese.example").status_code, 200)

    def test_csrf_behind_proxy_without_forwarded_proto(self):
        from django.test import Client

        self.set_url("https://jobforge.firma.de")
        client = Client(enforce_csrf_checks=True)
        client.get("/login/", HTTP_HOST="jobforge.firma.de")
        token = client.cookies["csrftoken"].value
        resp = client.post("/login/", {"username": "proxyuser", "password": "pw-proxy-123",
                                       "csrfmiddlewaretoken": token},
                           HTTP_HOST="jobforge.firma.de", HTTP_ORIGIN="https://jobforge.firma.de")
        self.assertEqual(resp.status_code, 302)
        resp = Client(enforce_csrf_checks=True).post(
            "/login/", {"username": "x"}, HTTP_HOST="jobforge.firma.de", HTTP_ORIGIN="https://boese.example")
        self.assertEqual(resp.status_code, 403)

    def test_secure_cookies_with_forwarded_proto(self):
        self.set_url("https://jobforge.firma.de")
        resp = self.client.post("/login/", {"username": "proxyuser", "password": "pw-proxy-123"},
                                HTTP_HOST="jobforge.firma.de", HTTP_X_FORWARDED_PROTO="https")
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp.cookies["sessionid"]["secure"])

    def test_settings_form(self):
        admin = User.objects.create_superuser("root2", "r@example.com", "pw-root-123")
        self.client.force_login(admin)
        data = {f.name: getattr(self.company, f.name) for f in self.company._meta.fields
                if f.name not in ("id", "logo")}
        data.update(public_url="jobforge.test.de", small_business="")
        resp = self.client.post("/einstellungen/firma/", data)
        self.assertEqual(resp.status_code, 302)
        self.company.refresh_from_db()
        self.assertEqual(self.company.public_url, "https://jobforge.test.de")
