import re
from decimal import Decimal

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models, transaction
from django.utils import timezone


class CompanySettings(models.Model):
    """Firmendaten und Branding. Pro Installation genau eine Firma (pk=1)."""

    name = models.CharField("Firmenname", max_length=200, default="Meine Firma")
    owner = models.CharField("Inhaber / Geschäftsführung", max_length=200, blank=True)
    street = models.CharField("Straße & Nr.", max_length=200, blank=True)
    zip_code = models.CharField("PLZ", max_length=20, blank=True)
    city = models.CharField("Ort", max_length=100, blank=True)
    country = models.CharField("Land (ISO-Code)", max_length=2, default="DE")
    phone = models.CharField("Telefon", max_length=50, blank=True)
    email = models.EmailField("E-Mail", blank=True)
    website = models.CharField("Website", max_length=200, blank=True)
    vat_id = models.CharField("USt-IdNr.", max_length=30, blank=True)
    tax_number = models.CharField("Steuernummer", max_length=30, blank=True)
    register_court = models.CharField("Registergericht", max_length=100, blank=True)
    register_number = models.CharField("Handelsregister-Nr.", max_length=50, blank=True)
    bank_name = models.CharField("Bank", max_length=100, blank=True)
    iban = models.CharField("IBAN", max_length=34, blank=True)
    bic = models.CharField("BIC", max_length=11, blank=True)
    account_holder = models.CharField("Kontoinhaber", max_length=200, blank=True)
    logo = models.ImageField("Logo", upload_to="branding/", blank=True)
    primary_color = models.CharField("Primärfarbe", max_length=7, default="#e8590c")
    secondary_color = models.CharField("Sekundärfarbe", max_length=7, default="#1f2937")
    small_business = models.BooleanField(
        "Kleinunternehmer (§ 19 UStG)", default=False,
        help_text="Rechnungen ohne Umsatzsteuer mit entsprechendem Hinweis.",
    )
    currency = models.CharField("Währung", max_length=3, default="EUR")
    default_payment_days = models.PositiveIntegerField("Standard-Zahlungsziel (Tage)", default=14)
    quote_validity_days = models.PositiveIntegerField("Angebote gültig (Tage)", default=30)
    default_prep_hours = models.PositiveIntegerField(
        "Standard-Vorbereitungszeit (Std.)", default=24,
        help_text="Puffer vor Jobbeginn, in dem Material reserviert ist.",
    )
    default_return_hours = models.PositiveIntegerField(
        "Standard-Rückgabezeit (Std.)", default=24,
        help_text="Puffer nach Jobende für Rücknahme und Prüfung.",
    )

    class Meta:
        verbose_name = "Firmeneinstellungen"
        verbose_name_plural = "Firmeneinstellungen"

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    @property
    def address_line(self):
        return ", ".join(p for p in [self.street, f"{self.zip_code} {self.city}".strip()] if p)


SEQUENCE_CHOICES = [
    ("customer", "Kundennummer"),
    ("supplier", "Lieferantennummer"),
    ("article", "Artikelnummer"),
    ("unit", "Gerätenummer / Code"),
    ("location", "Lagerplatz-Code"),
    ("project", "Projektnummer"),
    ("job", "Auftrags-/Jobnummer"),
    ("quote", "Angebotsnummer"),
    ("confirmation", "Auftragsbestätigung"),
    ("invoice", "Rechnungsnummer"),
    ("credit", "Gutschrift / Rechnungskorrektur"),
    ("employee", "Personalnummer"),
]

DEFAULT_SEQUENCES = {
    "customer": ("K{NNNNN}", False),
    "supplier": ("L{NNNNN}", False),
    "article": ("A{NNNNN}", False),
    "unit": ("G{NNNNNN}", False),
    "location": ("LP{NNNN}", False),
    "project": ("P{YYYY}-{NNN}", True),
    "job": ("J{YYYY}-{NNNN}", True),
    "quote": ("AN{YYYY}-{NNNN}", True),
    "confirmation": ("AB{YYYY}-{NNNN}", True),
    "invoice": ("RE{YYYY}-{NNNN}", True),
    "credit": ("GS{YYYY}-{NNNN}", True),
    "employee": ("M{NNNN}", False),
}


class NumberSequence(models.Model):
    """Individuelle Nummernkreise. Platzhalter: {YYYY} {YY} {MM} {DD} {N…} (Anzahl N = Stellen)."""

    key = models.CharField("Nummernkreis", max_length=30, choices=SEQUENCE_CHOICES, unique=True)
    pattern = models.CharField(
        "Format", max_length=60, default="{YYYY}-{NNNN}",
        help_text="Platzhalter: {YYYY}, {YY}, {MM}, {DD}, {NNNN} (Anzahl N = Stellen).",
    )
    next_value = models.PositiveIntegerField("Nächste Nummer", default=1)
    yearly_reset = models.BooleanField("Jährlich zurücksetzen", default=False)
    current_year = models.PositiveIntegerField("Aktuelles Jahr", null=True, blank=True)

    class Meta:
        verbose_name = "Nummernkreis"
        verbose_name_plural = "Nummernkreise"
        ordering = ["key"]

    def __str__(self):
        return f"{self.get_key_display()} ({self.pattern})"

    def format(self, value, date=None):
        date = date or timezone.localdate()
        out = self.pattern.replace("{YYYY}", f"{date.year:04d}").replace("{YY}", f"{date.year % 100:02d}")
        out = out.replace("{MM}", f"{date.month:02d}").replace("{DD}", f"{date.day:02d}")
        return re.sub(r"\{(N+)\}", lambda m: f"{value:0{len(m.group(1))}d}", out)

    def preview(self):
        return self.format(self.next_value)

    @classmethod
    def next(cls, key):
        with transaction.atomic():
            try:
                seq = cls.objects.select_for_update().get(key=key)
            except cls.DoesNotExist:
                pattern, reset = DEFAULT_SEQUENCES.get(key, ("{NNNNN}", False))
                seq = cls.objects.create(key=key, pattern=pattern, yearly_reset=reset)
                seq = cls.objects.select_for_update().get(pk=seq.pk)
            year = timezone.localdate().year
            if seq.yearly_reset and seq.current_year != year:
                seq.next_value = 1
            seq.current_year = year
            value = seq.next_value
            seq.next_value += 1
            seq.save()
            return seq.format(value)


class TaxRate(models.Model):
    name = models.CharField("Bezeichnung", max_length=60)
    rate = models.DecimalField("Steuersatz (%)", max_digits=5, decimal_places=2)
    is_default = models.BooleanField("Standard", default=False)
    active = models.BooleanField("Aktiv", default=True)

    class Meta:
        verbose_name = "Steuersatz"
        verbose_name_plural = "Steuersätze"
        ordering = ["-rate"]

    def __str__(self):
        return f"{self.name} ({self.rate:g} %)"

    @classmethod
    def default_rate(cls):
        tr = cls.objects.filter(is_default=True, active=True).first()
        return tr.rate if tr else Decimal("19.00")


class PaymentTerm(models.Model):
    name = models.CharField("Bezeichnung", max_length=100)
    days = models.PositiveIntegerField("Zahlungsziel (Tage)", default=14)
    discount_days = models.PositiveIntegerField("Skonto-Frist (Tage)", default=0)
    discount_percent = models.DecimalField("Skonto (%)", max_digits=5, decimal_places=2, default=0)
    text = models.TextField(
        "Text auf Dokumenten", blank=True,
        help_text="Platzhalter: {days}, {due_date}, {discount_days}, {discount_percent}",
        default="Zahlbar innerhalb von {days} Tagen ohne Abzug bis zum {due_date}.",
    )
    is_default = models.BooleanField("Standard", default=False)

    class Meta:
        verbose_name = "Zahlungsbedingung"
        verbose_name_plural = "Zahlungsbedingungen"
        ordering = ["days"]

    def __str__(self):
        return self.name

    def render(self, due_date=None):
        try:
            return self.text.format(
                days=self.days,
                due_date=due_date.strftime("%d.%m.%Y") if due_date else "",
                discount_days=self.discount_days,
                discount_percent=f"{self.discount_percent:g}",
            )
        except (KeyError, IndexError, ValueError):
            return self.text


class AuditLog(models.Model):
    ACTIONS = [("create", "Erstellt"), ("update", "Geändert"), ("delete", "Gelöscht"), ("info", "Aktion")]

    timestamp = models.DateTimeField("Zeitpunkt", auto_now_add=True, db_index=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="Benutzer", null=True, blank=True, on_delete=models.SET_NULL)
    action = models.CharField("Aktion", max_length=10, choices=ACTIONS)
    content_type = models.ForeignKey(ContentType, null=True, blank=True, on_delete=models.SET_NULL)
    object_id = models.CharField(max_length=64, blank=True, db_index=True)
    object_repr = models.CharField("Objekt", max_length=255, blank=True)
    changes = models.JSONField("Änderungen", default=dict, blank=True)
    message = models.CharField("Nachricht", max_length=500, blank=True)

    class Meta:
        verbose_name = "Protokolleintrag"
        verbose_name_plural = "Änderungsprotokoll"
        ordering = ["-timestamp"]

    def __str__(self):
        return f"{self.timestamp:%d.%m.%Y %H:%M} {self.get_action_display()} {self.object_repr}"

    @classmethod
    def log(cls, obj, message, user=None, action="info"):
        from .middleware import get_current_user

        return cls.objects.create(
            user=user or get_current_user(),
            action=action,
            content_type=ContentType.objects.get_for_model(obj) if obj is not None else None,
            object_id=str(obj.pk) if obj is not None else "",
            object_repr=str(obj)[:255] if obj is not None else "",
            message=message[:500],
        )


CUSTOM_FIELD_TARGETS = [
    ("contacts.contact", "Kontakte"),
    ("inventory.article", "Artikel"),
    ("inventory.unit", "Einzelgeräte"),
    ("projects.project", "Projekte"),
    ("projects.job", "Jobs / Aufträge"),
    ("staff.employee", "Personal"),
]


class CustomFieldDefinition(models.Model):
    TYPES = [
        ("text", "Text"),
        ("textarea", "Mehrzeiliger Text"),
        ("number", "Zahl"),
        ("date", "Datum"),
        ("bool", "Ja/Nein"),
        ("choice", "Auswahl"),
        ("url", "Link"),
    ]
    target = models.CharField("Bereich", max_length=40, choices=CUSTOM_FIELD_TARGETS)
    key = models.SlugField("Schlüssel", max_length=50, help_text="Technischer Name, z. B. 'leistung_watt'")
    label = models.CharField("Bezeichnung", max_length=100)
    field_type = models.CharField("Typ", max_length=10, choices=TYPES, default="text")
    choices = models.TextField("Auswahlwerte", blank=True, help_text="Ein Wert pro Zeile (nur für Typ Auswahl)")
    required = models.BooleanField("Pflichtfeld", default=False)
    show_in_list = models.BooleanField("In Listen anzeigen", default=False)
    order = models.PositiveIntegerField("Reihenfolge", default=0)
    active = models.BooleanField("Aktiv", default=True)

    class Meta:
        verbose_name = "Zusatzfeld"
        verbose_name_plural = "Zusatzfelder"
        ordering = ["target", "order", "label"]
        unique_together = [("target", "key")]

    def __str__(self):
        return f"{self.get_target_display()}: {self.label}"

    def choice_list(self):
        return [c.strip() for c in self.choices.splitlines() if c.strip()]

    @classmethod
    def for_model(cls, model):
        target = f"{model._meta.app_label}.{model._meta.model_name}"
        return cls.objects.filter(target=target, active=True)


WEBHOOK_EVENTS_HELP = (
    "Kommagetrennt, z. B. 'job.created, document.updated' oder '*' für alle. "
    "Objekte: contact, article, unit, movement, project, job, document, payment, employee, timeentry, assignment. "
    "Aktionen: created, updated, deleted."
)


class Webhook(models.Model):
    name = models.CharField("Name", max_length=100)
    url = models.URLField("Ziel-URL", max_length=500)
    secret = models.CharField(
        "Geheimnis", max_length=100, blank=True,
        help_text="Wird zur HMAC-SHA256-Signatur (Header X-JobForge-Signature) verwendet.",
    )
    events = models.CharField("Ereignisse", max_length=500, default="*", help_text=WEBHOOK_EVENTS_HELP)
    active = models.BooleanField("Aktiv", default=True)
    created = models.DateTimeField("Erstellt", auto_now_add=True)

    class Meta:
        verbose_name = "Webhook"
        verbose_name_plural = "Webhooks"
        ordering = ["name"]

    def __str__(self):
        return self.name

    def matches(self, event):
        wanted = [e.strip() for e in self.events.split(",") if e.strip()]
        obj = event.split(".")[0]
        return "*" in wanted or event in wanted or f"{obj}.*" in wanted


class WebhookDelivery(models.Model):
    webhook = models.ForeignKey(Webhook, on_delete=models.CASCADE, related_name="deliveries")
    event = models.CharField("Ereignis", max_length=60)
    timestamp = models.DateTimeField("Zeitpunkt", auto_now_add=True)
    status_code = models.IntegerField("HTTP-Status", null=True, blank=True)
    success = models.BooleanField("Erfolgreich", default=False)
    response = models.TextField("Antwort", blank=True)

    class Meta:
        verbose_name = "Webhook-Zustellung"
        verbose_name_plural = "Webhook-Zustellungen"
        ordering = ["-timestamp"]


class Note(models.Model):
    """Notiz, die an beliebige Objekte (Kontakt, Projekt, Job, Artikel …) gehängt werden kann."""

    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveBigIntegerField()
    target = GenericForeignKey("content_type", "object_id")
    text = models.TextField("Notiz")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    created = models.DateTimeField("Erstellt", auto_now_add=True)

    class Meta:
        verbose_name = "Notiz"
        verbose_name_plural = "Notizen"
        ordering = ["-created"]
        indexes = [models.Index(fields=["content_type", "object_id"])]


def attachment_path(instance, filename):
    return f"attachments/{instance.content_type.model}/{instance.object_id}/{filename}"


class Attachment(models.Model):
    """Dokumentenablage für beliebige Objekte."""

    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveBigIntegerField()
    target = GenericForeignKey("content_type", "object_id")
    file = models.FileField("Datei", upload_to=attachment_path)
    name = models.CharField("Bezeichnung", max_length=200, blank=True)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    uploaded = models.DateTimeField("Hochgeladen", auto_now_add=True)

    class Meta:
        verbose_name = "Dokument"
        verbose_name_plural = "Dokumente"
        ordering = ["-uploaded"]
        indexes = [models.Index(fields=["content_type", "object_id"])]

    def __str__(self):
        return self.name or self.file.name.rsplit("/", 1)[-1]

    @property
    def filename(self):
        return self.file.name.rsplit("/", 1)[-1]


class CustomFieldsMixin(models.Model):
    custom_data = models.JSONField("Zusatzfelder", default=dict, blank=True)

    class Meta:
        abstract = True

    def custom_field_values(self):
        out = []
        for d in CustomFieldDefinition.for_model(type(self)):
            value = (self.custom_data or {}).get(d.key)
            if d.field_type == "bool":
                value = "Ja" if value else "Nein"
            out.append((d.label, value if value not in (None, "") else "–"))
        return out
