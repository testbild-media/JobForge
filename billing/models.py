import datetime
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.db import models
from django.db.models import Sum
from django.urls import reverse
from django.utils import timezone

from core.models import CompanySettings, NumberSequence

TWO = Decimal("0.01")
ZERO = Decimal("0")


def q2(value):
    return Decimal(value).quantize(TWO, rounding=ROUND_HALF_UP)


class DocumentLayout(models.Model):
    name = models.CharField("Bezeichnung", max_length=100)
    is_default = models.BooleanField("Standard", default=False)
    accent_color = models.CharField("Akzentfarbe", max_length=7, blank=True,
                                    help_text="Leer = Primärfarbe aus den Firmeneinstellungen")
    font_family = models.CharField("Schriftart", max_length=100, default="DejaVu Sans, Arial, sans-serif")
    font_size = models.DecimalField("Schriftgröße (pt)", max_digits=4, decimal_places=1, default=Decimal("9.5"))
    logo_position = models.CharField("Logo-Position", max_length=10, choices=[("right", "Rechts"), ("left", "Links"),
                                                                             ("none", "Kein Logo")], default="right")
    show_sender_line = models.BooleanField("Absenderzeile über Adresse", default=True)
    show_article_numbers = models.BooleanField("Artikelnummern anzeigen", default=False)
    footer_columns = models.TextField(
        "Fußzeile", blank=True,
        help_text="Leer = automatisch aus Firmendaten. Spalten mit '|' trennen, Zeilenumbrüche erlaubt.",
    )
    quote_intro = models.TextField("Einleitung Angebot", blank=True,
                                   default="Vielen Dank für Ihre Anfrage. Gerne unterbreiten wir Ihnen folgendes Angebot:")
    quote_outro = models.TextField("Schlusstext Angebot", blank=True,
                                   default="Wir freuen uns auf Ihren Auftrag.\nMit freundlichen Grüßen")
    confirmation_intro = models.TextField("Einleitung Auftragsbestätigung", blank=True,
                                          default="Vielen Dank für Ihren Auftrag. Hiermit bestätigen wir:")
    confirmation_outro = models.TextField("Schlusstext Auftragsbestätigung", blank=True,
                                          default="Mit freundlichen Grüßen")
    invoice_intro = models.TextField("Einleitung Rechnung", blank=True,
                                     default="Vielen Dank für Ihren Auftrag. Wir berechnen Ihnen folgende Leistungen:")
    invoice_outro = models.TextField("Schlusstext Rechnung", blank=True, default="Mit freundlichen Grüßen")
    custom_css = models.TextField("Eigenes CSS", blank=True,
                                  help_text="Wird an das PDF-Stylesheet angehängt, z. B. 'h1 { color: navy; }'")

    class Meta:
        verbose_name = "Dokumentenlayout"
        verbose_name_plural = "Dokumentenlayouts"
        ordering = ["-is_default", "name"]

    def __str__(self):
        return self.name

    @classmethod
    def default(cls):
        return cls.objects.filter(is_default=True).first() or cls.objects.first()

    def texts_for(self, doc_type):
        if doc_type == "quote":
            return self.quote_intro, self.quote_outro
        if doc_type == "confirmation":
            return self.confirmation_intro, self.confirmation_outro
        return self.invoice_intro, self.invoice_outro


class Document(models.Model):
    TYPES = [
        ("quote", "Angebot"),
        ("confirmation", "Auftragsbestätigung"),
        ("invoice", "Rechnung"),
        ("partial", "Teilrechnung"),
        ("advance", "Abschlagsrechnung"),
        ("final", "Schlussrechnung"),
        ("credit", "Rechnungskorrektur / Gutschrift"),
    ]
    INVOICE_TYPES = ("invoice", "partial", "advance", "final", "credit")
    SEQUENCE_FOR = {"quote": "quote", "confirmation": "confirmation", "credit": "credit"}
    STATUSES = [
        ("draft", "Entwurf"),
        ("final", "Festgeschrieben"),
        ("sent", "Versendet"),
        ("accepted", "Angenommen"),
        ("rejected", "Abgelehnt"),
        ("partially_paid", "Teilweise bezahlt"),
        ("paid", "Bezahlt"),
        ("cancelled", "Storniert"),
    ]
    STATUS_COLORS = {
        "draft": "#94a3b8", "final": "#0ea5e9", "sent": "#6366f1", "accepted": "#16a34a", "rejected": "#ef4444",
        "partially_paid": "#f59e0b", "paid": "#16a34a", "cancelled": "#64748b", "overdue": "#dc2626",
    }

    doc_type = models.CharField("Dokumentart", max_length=12, choices=TYPES, default="quote")
    number = models.CharField("Nummer", max_length=40, unique=True, null=True, blank=True)
    status = models.CharField("Status", max_length=15, choices=STATUSES, default="draft")
    customer = models.ForeignKey("contacts.Contact", verbose_name="Kunde", on_delete=models.PROTECT,
                                 related_name="documents")
    job = models.ForeignKey("projects.Job", verbose_name="Job", null=True, blank=True, on_delete=models.SET_NULL,
                            related_name="documents")
    project = models.ForeignKey("projects.Project", verbose_name="Projekt", null=True, blank=True,
                                on_delete=models.SET_NULL, related_name="documents")
    source = models.ForeignKey("self", verbose_name="Erstellt aus", null=True, blank=True, on_delete=models.SET_NULL,
                               related_name="derived")
    layout = models.ForeignKey(DocumentLayout, verbose_name="Layout", null=True, blank=True, on_delete=models.SET_NULL)
    date = models.DateField("Datum", default=timezone.localdate)
    service_start = models.DateField("Leistung von", null=True, blank=True)
    service_end = models.DateField("Leistung bis", null=True, blank=True)
    valid_until = models.DateField("Gültig bis", null=True, blank=True)
    due_date = models.DateField("Fällig am", null=True, blank=True)
    payment_term = models.ForeignKey("core.PaymentTerm", verbose_name="Zahlungsbedingung", null=True, blank=True,
                                     on_delete=models.SET_NULL)
    recipient = models.TextField("Empfängeradresse", blank=True, help_text="Leer = Adresse des Kunden")
    buyer_reference = models.CharField("Käuferreferenz / Leitweg-ID", max_length=60, blank=True)
    customer_order_ref = models.CharField("Bestellnummer des Kunden", max_length=60, blank=True)
    subject = models.CharField("Betreff", max_length=200, blank=True)
    intro = models.TextField("Einleitung", blank=True)
    outro = models.TextField("Schlusstext", blank=True)
    discount_percent = models.DecimalField("Gesamtrabatt %", max_digits=5, decimal_places=2, default=0)
    group_subtotals = models.BooleanField("Zwischensummen je Gruppe", default=True)
    deducted = models.ManyToManyField("self", verbose_name="Abgezogene Abschläge", blank=True, symmetrical=False,
                                      related_name="deducted_in")
    finalized_at = models.DateTimeField("Festgeschrieben am", null=True, blank=True)
    sent_at = models.DateTimeField("Versendet am", null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="Erstellt von", null=True, blank=True,
                                   on_delete=models.SET_NULL)
    created = models.DateTimeField("Erstellt", auto_now_add=True)
    updated = models.DateTimeField("Geändert", auto_now=True)

    class Meta:
        verbose_name = "Dokument"
        verbose_name_plural = "Angebote & Rechnungen"
        ordering = ["-date", "-pk"]
        permissions = [("finalize_document", "Dokumente festschreiben")]

    def __str__(self):
        return f"{self.get_doc_type_display()} {self.number or '(Entwurf #%s)' % self.pk}"

    def get_absolute_url(self):
        return reverse("billing:document_detail", args=[self.pk])

    # -- Eigenschaften ----------------------------------------------------
    @property
    def is_invoice(self):
        return self.doc_type in self.INVOICE_TYPES

    @property
    def is_locked(self):
        return self.finalized_at is not None

    @property
    def display_status(self):
        if self.is_overdue:
            return "overdue", "Überfällig"
        return self.status, self.get_status_display()

    @property
    def status_color(self):
        return self.STATUS_COLORS.get(self.display_status[0], "#64748b")

    @property
    def is_overdue(self):
        return (
            self.is_invoice and self.doc_type != "credit" and self.status in ("final", "sent", "partially_paid")
            and self.due_date is not None and self.due_date < timezone.localdate()
        )

    @property
    def sign(self):
        return Decimal("-1") if self.doc_type == "credit" else Decimal("1")

    # -- Summen ----------------------------------------------------------
    def _positions(self):
        cache = getattr(self, "_pos_cache", None)
        if cache is None:
            cache = list(self.positions.select_related("article").all())
            self._pos_cache = cache
        return cache

    def totals(self):
        small_business = CompanySettings.get().small_business
        by_rate = {}
        for p in self._positions():
            if p.is_priced:
                rate = ZERO if small_business else p.tax_rate
                by_rate[rate] = by_rate.get(rate, ZERO) + p.net_total
        lines_net = sum(by_rate.values(), ZERO)
        breakdown, discount_total = [], ZERO
        for rate in sorted(by_rate, reverse=True):
            net = by_rate[rate]
            disc = q2(net * self.discount_percent / Decimal("100"))
            taxable = net - disc
            tax = q2(taxable * rate / Decimal("100"))
            discount_total += disc
            breakdown.append({"rate": rate, "net": net, "discount": disc, "taxable": taxable, "tax": tax})
        net_total = sum((b["taxable"] for b in breakdown), ZERO)
        tax_total = sum((b["tax"] for b in breakdown), ZERO)
        gross = net_total + tax_total
        deductions = []
        if self.pk and self.doc_type == "final":
            for d in self.deducted.all():
                t = d.totals()
                deductions.append({"document": d, "net": t["net_total"], "tax": t["tax_total"], "gross": t["gross"]})
        prepaid = sum((d["gross"] for d in deductions), ZERO)
        return {
            "lines_net": lines_net,
            "discount_total": discount_total,
            "breakdown": breakdown,
            "net_total": net_total,
            "tax_total": tax_total,
            "gross": gross,
            "deductions": deductions,
            "prepaid": prepaid,
            "amount_due": gross - prepaid,
            "small_business": small_business,
        }

    @property
    def gross_total(self):
        return self.totals()["gross"]

    @property
    def amount_due(self):
        return self.totals()["amount_due"]

    @property
    def paid_amount(self):
        return self.payments.aggregate(s=Sum("amount"))["s"] or ZERO

    @property
    def open_amount(self):
        if not self.is_invoice or self.status == "cancelled":
            return ZERO
        return self.amount_due - self.paid_amount

    def rows(self):
        """Positionen inkl. Gruppen-Nummerierung und Zwischensummen für Anzeige/PDF."""
        rows, group_no, item_no, group_sum, in_group, running = [], 0, 0, ZERO, False, ZERO
        positions = self._positions()
        for idx, p in enumerate(positions):
            if p.kind == "heading":
                if in_group and self.group_subtotals:
                    rows.append({"type": "group_total", "label": current_label, "total": group_sum})
                group_no += 1
                item_no, group_sum, in_group = 0, ZERO, True
                current_label = p.description.split("\n")[0]
                rows.append({"type": "heading", "pos": p, "number": f"{group_no}"})
                continue
            if p.kind == "subtotal":
                rows.append({"type": "subtotal", "pos": p, "total": running})
                continue
            if p.kind == "pagebreak":
                rows.append({"type": "pagebreak", "pos": p})
                continue
            if p.kind == "text":
                rows.append({"type": "text", "pos": p})
                continue
            item_no += 1
            number = f"{group_no}.{item_no}" if group_no else f"{item_no}"
            total = p.net_total
            group_sum += total
            running += total
            rows.append({"type": "item", "pos": p, "number": number, "total": total})
        if in_group and self.group_subtotals and group_no > 0:
            rows.append({"type": "group_total", "label": current_label, "total": group_sum})
        return rows

    # -- Workflow --------------------------------------------------------
    def finalize(self, user=None):
        if self.is_locked:
            return
        if not self.number:
            self.number = NumberSequence.next(self.SEQUENCE_FOR.get(self.doc_type, "invoice"))
        self.finalized_at = timezone.now()
        if self.status == "draft":
            self.status = "final"
        if self.is_invoice and not self.due_date:
            days = self.payment_term.days if self.payment_term else CompanySettings.get().default_payment_days
            self.due_date = self.date + datetime.timedelta(days=days)
        self.save()

    def update_payment_status(self):
        if not self.is_invoice or self.status in ("draft", "cancelled"):
            return
        paid, due = self.paid_amount, self.amount_due
        if due > 0 and paid >= due:
            self.status = "paid"
        elif paid > 0:
            self.status = "partially_paid"
        elif self.status in ("paid", "partially_paid"):
            self.status = "sent" if self.sent_at else "final"
        self.save(update_fields=["status", "updated"])


class DocumentPosition(models.Model):
    KINDS = [
        ("heading", "Überschrift / Gruppe"),
        ("rental", "Vermietung"),
        ("sale", "Verkauf"),
        ("service", "Dienstleistung"),
        ("staff", "Personal"),
        ("text", "Textzeile"),
        ("subtotal", "Zwischensumme"),
        ("pagebreak", "Seitenumbruch"),
    ]
    PRICED = ("rental", "sale", "service", "staff")

    document = models.ForeignKey(Document, verbose_name="Dokument", on_delete=models.CASCADE, related_name="positions")
    order = models.PositiveIntegerField("Pos.", default=0)
    kind = models.CharField("Art", max_length=10, choices=KINDS, default="service")
    article = models.ForeignKey("inventory.Article", verbose_name="Artikel", null=True, blank=True,
                                on_delete=models.SET_NULL)
    description = models.TextField("Beschreibung", blank=True)
    quantity = models.DecimalField("Menge", max_digits=12, decimal_places=3, default=1)
    unit = models.CharField("Einheit", max_length=20, blank=True, default="Stk")
    unit_price = models.DecimalField("Einzelpreis", max_digits=12, decimal_places=2, default=0)
    factor = models.DecimalField("Tage/Faktor", max_digits=8, decimal_places=2, default=1)
    discount = models.DecimalField("Rabatt %", max_digits=5, decimal_places=2, default=0)
    tax_rate = models.DecimalField("USt %", max_digits=5, decimal_places=2, default=Decimal("19.00"))

    class Meta:
        verbose_name = "Dokumentposition"
        verbose_name_plural = "Dokumentpositionen"
        ordering = ["order", "pk"]

    def __str__(self):
        return self.description.split("\n")[0][:80] if self.description else "Position"

    @property
    def is_priced(self):
        return self.kind in self.PRICED

    @property
    def net_total(self):
        if not self.is_priced:
            return ZERO
        return q2(self.quantity * self.unit_price * self.factor * (Decimal("1") - self.discount / Decimal("100")))

    @property
    def net_unit_price(self):
        """Effektiver Netto-Einzelpreis inkl. Faktor und Rabatt (für XRechnung)."""
        return (self.unit_price * self.factor * (Decimal("1") - self.discount / Decimal("100"))).quantize(
            Decimal("0.0001"), rounding=ROUND_HALF_UP)

    @property
    def title(self):
        return self.description.split("\n")[0] if self.description else ""

    @property
    def details(self):
        parts = self.description.split("\n", 1)
        return parts[1] if len(parts) > 1 else ""


class Payment(models.Model):
    METHODS = [("transfer", "Überweisung"), ("cash", "Bar"), ("card", "Karte"), ("paypal", "PayPal"),
               ("direct_debit", "Lastschrift"), ("offset", "Verrechnung"), ("other", "Sonstige")]

    document = models.ForeignKey(Document, verbose_name="Rechnung", on_delete=models.PROTECT, related_name="payments",
                                 limit_choices_to={"doc_type__in": Document.INVOICE_TYPES})
    date = models.DateField("Zahlungsdatum", default=timezone.localdate)
    amount = models.DecimalField("Betrag", max_digits=12, decimal_places=2)
    method = models.CharField("Zahlart", max_length=15, choices=METHODS, default="transfer")
    reference = models.CharField("Referenz", max_length=100, blank=True)
    note = models.CharField("Bemerkung", max_length=200, blank=True)
    created = models.DateTimeField("Erfasst", auto_now_add=True)

    class Meta:
        verbose_name = "Zahlungseingang"
        verbose_name_plural = "Zahlungseingänge"
        ordering = ["-date", "-pk"]

    def __str__(self):
        return f"{self.amount} € am {self.date:%d.%m.%Y} ({self.document})"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        self.document.update_payment_status()

    def delete(self, *args, **kwargs):
        doc = self.document
        result = super().delete(*args, **kwargs)
        doc.update_payment_status()
        return result
