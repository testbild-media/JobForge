from django.db import models
from django.urls import reverse

from core.models import CustomFieldsMixin, NumberSequence


class Contact(CustomFieldsMixin, models.Model):
    TYPES = [("customer", "Kunde"), ("supplier", "Lieferant"), ("both", "Kunde & Lieferant"), ("other", "Sonstiger")]

    number = models.CharField("Nummer", max_length=30, unique=True, blank=True)
    contact_type = models.CharField("Typ", max_length=10, choices=TYPES, default="customer")
    is_company = models.BooleanField("Firma", default=True)
    company_name = models.CharField("Firmenname", max_length=200, blank=True)
    salutation = models.CharField("Anrede", max_length=30, blank=True)
    first_name = models.CharField("Vorname", max_length=100, blank=True)
    last_name = models.CharField("Nachname", max_length=100, blank=True)
    email = models.EmailField("E-Mail", blank=True)
    phone = models.CharField("Telefon", max_length=50, blank=True)
    mobile = models.CharField("Mobil", max_length=50, blank=True)
    website = models.CharField("Website", max_length=200, blank=True)
    street = models.CharField("Straße & Nr.", max_length=200, blank=True)
    address_extra = models.CharField("Adresszusatz", max_length=200, blank=True)
    zip_code = models.CharField("PLZ", max_length=20, blank=True)
    city = models.CharField("Ort", max_length=100, blank=True)
    country = models.CharField("Land (ISO)", max_length=2, default="DE")
    vat_id = models.CharField("USt-IdNr.", max_length=30, blank=True)
    tax_number = models.CharField("Steuernummer", max_length=30, blank=True)
    leitweg_id = models.CharField(
        "Leitweg-ID / Käuferreferenz", max_length=60, blank=True,
        help_text="Für XRechnung an öffentliche Auftraggeber (BT-10).",
    )
    payment_term = models.ForeignKey(
        "core.PaymentTerm", verbose_name="Zahlungsbedingung", null=True, blank=True, on_delete=models.SET_NULL
    )
    discount_percent = models.DecimalField("Kundenrabatt (%)", max_digits=5, decimal_places=2, default=0)
    notes = models.TextField("Bemerkungen", blank=True)
    active = models.BooleanField("Aktiv", default=True)
    created = models.DateTimeField("Erstellt", auto_now_add=True)
    updated = models.DateTimeField("Geändert", auto_now=True)

    class Meta:
        verbose_name = "Kontakt"
        verbose_name_plural = "Kontakte"
        ordering = ["company_name", "last_name", "first_name"]

    def __str__(self):
        return f"{self.name} ({self.number})" if self.number else self.name

    @property
    def name(self):
        if self.is_company and self.company_name:
            return self.company_name
        person = " ".join(p for p in [self.first_name, self.last_name] if p)
        return person or self.company_name or "Unbenannt"

    @property
    def is_customer(self):
        return self.contact_type in ("customer", "both")

    @property
    def is_supplier(self):
        return self.contact_type in ("supplier", "both")

    def address_lines(self):
        lines = [self.name]
        if self.is_company and (self.first_name or self.last_name):
            lines.append(" ".join(p for p in [self.salutation, self.first_name, self.last_name] if p))
        for part in [self.address_extra, self.street, f"{self.zip_code} {self.city}".strip()]:
            if part:
                lines.append(part)
        if self.country and self.country.upper() != "DE":
            lines.append(self.country.upper())
        return lines

    def address_text(self):
        return "\n".join(self.address_lines())

    def save(self, *args, **kwargs):
        if not self.number:
            self.number = NumberSequence.next("supplier" if self.contact_type == "supplier" else "customer")
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("contacts:contact_detail", args=[self.pk])


class ContactPerson(models.Model):
    contact = models.ForeignKey(Contact, verbose_name="Kontakt", on_delete=models.CASCADE, related_name="persons")
    salutation = models.CharField("Anrede", max_length=30, blank=True)
    first_name = models.CharField("Vorname", max_length=100, blank=True)
    last_name = models.CharField("Nachname", max_length=100)
    position = models.CharField("Funktion", max_length=100, blank=True)
    email = models.EmailField("E-Mail", blank=True)
    phone = models.CharField("Telefon", max_length=50, blank=True)
    mobile = models.CharField("Mobil", max_length=50, blank=True)
    is_primary = models.BooleanField("Hauptansprechpartner", default=False)

    class Meta:
        verbose_name = "Ansprechpartner"
        verbose_name_plural = "Ansprechpartner"
        ordering = ["-is_primary", "last_name"]

    def __str__(self):
        name = " ".join(p for p in [self.first_name, self.last_name] if p)
        return f"{name} ({self.contact.name})"


class Address(models.Model):
    KINDS = [("billing", "Rechnungsadresse"), ("shipping", "Lieferadresse"), ("venue", "Einsatzort"), ("other", "Sonstige")]

    contact = models.ForeignKey(Contact, verbose_name="Kontakt", on_delete=models.CASCADE, related_name="addresses")
    kind = models.CharField("Art", max_length=10, choices=KINDS, default="shipping")
    label = models.CharField("Bezeichnung", max_length=100, blank=True)
    street = models.CharField("Straße & Nr.", max_length=200)
    zip_code = models.CharField("PLZ", max_length=20)
    city = models.CharField("Ort", max_length=100)
    country = models.CharField("Land", max_length=2, default="DE")
    notes = models.CharField("Hinweis", max_length=200, blank=True)

    class Meta:
        verbose_name = "Adresse"
        verbose_name_plural = "Adressen"

    def __str__(self):
        prefix = f"{self.label}: " if self.label else ""
        return f"{prefix}{self.street}, {self.zip_code} {self.city}"
