import datetime
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone

from core.models import CustomFieldsMixin, NumberSequence

TWO = Decimal("0.01")


class JobStatus(models.Model):
    name = models.CharField("Bezeichnung", max_length=60)
    color = models.CharField("Farbe", max_length=7, default="#64748b")
    order = models.PositiveIntegerField("Reihenfolge", default=0)
    reserves_inventory = models.BooleanField(
        "Reserviert Material", default=True,
        help_text="Jobs in diesem Status blockieren Material und Personal in der Verfügbarkeit.",
    )
    is_closed = models.BooleanField("Abgeschlossen", default=False)
    is_default = models.BooleanField("Standard für neue Jobs", default=False)

    class Meta:
        verbose_name = "Status"
        verbose_name_plural = "Status (Projekte & Jobs)"
        ordering = ["order", "name"]

    def __str__(self):
        return self.name

    @classmethod
    def default(cls):
        return cls.objects.filter(is_default=True).first() or cls.objects.order_by("order").first()


class Project(CustomFieldsMixin, models.Model):
    number = models.CharField("Projektnummer", max_length=40, unique=True, blank=True)
    name = models.CharField("Projektname", max_length=200)
    customer = models.ForeignKey("contacts.Contact", verbose_name="Kunde", null=True, blank=True,
                                 on_delete=models.PROTECT, related_name="projects")
    status = models.ForeignKey(JobStatus, verbose_name="Status", null=True, blank=True, on_delete=models.SET_NULL)
    manager = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="Projektleitung", null=True, blank=True,
                                on_delete=models.SET_NULL, related_name="managed_projects")
    start_date = models.DateField("Beginn", null=True, blank=True)
    end_date = models.DateField("Ende", null=True, blank=True)
    budget = models.DecimalField("Budget", max_digits=12, decimal_places=2, null=True, blank=True)
    description = models.TextField("Beschreibung", blank=True)
    is_template = models.BooleanField("Vorlage", default=False)
    created = models.DateTimeField("Erstellt", auto_now_add=True)
    updated = models.DateTimeField("Geändert", auto_now=True)

    class Meta:
        verbose_name = "Projekt"
        verbose_name_plural = "Projekte"
        ordering = ["-created"]

    def __str__(self):
        return f"{self.number} {self.name}" if self.number else self.name

    def save(self, *args, **kwargs):
        if not self.number and not self.is_template:
            self.number = NumberSequence.next("project")
        if not self.number and self.is_template:
            self.number = f"VORLAGE-P-{timezone.now():%Y%m%d%H%M%S%f}"
        if not self.status_id:
            self.status = JobStatus.default()
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("projects:project_detail", args=[self.pk])


class Job(CustomFieldsMixin, models.Model):
    number = models.CharField("Jobnummer", max_length=40, unique=True, blank=True)
    title = models.CharField("Bezeichnung", max_length=200)
    project = models.ForeignKey(Project, verbose_name="Projekt", null=True, blank=True, on_delete=models.SET_NULL,
                                related_name="jobs")
    customer = models.ForeignKey("contacts.Contact", verbose_name="Kunde", null=True, blank=True,
                                 on_delete=models.PROTECT, related_name="jobs")
    contact_person = models.ForeignKey("contacts.ContactPerson", verbose_name="Ansprechpartner", null=True, blank=True,
                                       on_delete=models.SET_NULL)
    status = models.ForeignKey(JobStatus, verbose_name="Status", null=True, blank=True, on_delete=models.SET_NULL)
    manager = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="Verantwortlich", null=True, blank=True,
                                on_delete=models.SET_NULL, related_name="managed_jobs")
    warehouse = models.ForeignKey("inventory.Location", verbose_name="Lagerstandort", null=True, blank=True,
                                  on_delete=models.SET_NULL, limit_choices_to={"parent__isnull": True},
                                  related_name="jobs")
    venue = models.CharField("Einsatzort", max_length=200, blank=True)
    venue_address = models.TextField("Adresse Einsatzort", blank=True)
    prep_start = models.DateTimeField("Vorbereitung ab", null=True, blank=True,
                                      help_text="Ab hier ist Material reserviert (Ladezeit/Aufbau).")
    start = models.DateTimeField("Beginn", null=True, blank=True)
    end = models.DateTimeField("Ende", null=True, blank=True)
    return_end = models.DateTimeField("Rückgabe bis", null=True, blank=True,
                                      help_text="Bis hier bleibt Material reserviert (Abbau/Rücklauf).")
    rental_days = models.DecimalField("Berechnungstage", max_digits=6, decimal_places=2, null=True, blank=True,
                                      help_text="Leer = automatisch aus Beginn/Ende (Kalendertage).")
    description = models.TextField("Beschreibung", blank=True)
    internal_notes = models.TextField("Interne Notizen", blank=True)
    is_template = models.BooleanField("Vorlage", default=False)
    created = models.DateTimeField("Erstellt", auto_now_add=True)
    updated = models.DateTimeField("Geändert", auto_now=True)

    class Meta:
        verbose_name = "Job / Auftrag"
        verbose_name_plural = "Jobs / Aufträge"
        ordering = ["-start", "-created"]

    def __str__(self):
        return f"{self.number} {self.title}" if self.number else self.title

    def save(self, *args, **kwargs):
        if not self.number:
            if self.is_template:
                self.number = f"VORLAGE-{timezone.now():%Y%m%d%H%M%S%f}"
            else:
                self.number = NumberSequence.next("job")
        if not self.status_id:
            self.status = JobStatus.default()
        if not self.customer_id and self.project_id and self.project.customer_id:
            self.customer_id = self.project.customer_id
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("projects:job_detail", args=[self.pk])

    @property
    def period_start(self):
        return self.prep_start or self.start

    @property
    def period_end(self):
        return self.return_end or self.end

    @property
    def calc_days(self):
        if self.rental_days:
            return self.rental_days
        if self.start and self.end:
            s, e = timezone.localtime(self.start).date(), timezone.localtime(self.end).date()
            return Decimal(max((e - s).days + 1, 1))
        return Decimal("1")

    @property
    def reserves(self):
        return bool(self.status and self.status.reserves_inventory and not self.is_template)

    def positions_total(self):
        return sum((p.net_total for p in self.positions.all()), Decimal("0"))

    def material_requirements(self):
        """Benötigtes Material je Artikel (Sets werden in Bestandteile aufgelöst)."""
        req = {}
        for pos in self.positions.filter(article__isnull=False, kind__in=["rental", "sale"]).select_related("article"):
            for article, qty in expand_article(pos.article, pos.quantity):
                req[article] = req.get(article, Decimal("0")) + qty
        return req


def expand_article(article, quantity, depth=0):
    """Löst Sets rekursiv in lagerführende Bestandteile auf."""
    if article.kind == "set" and depth < 5:
        out = []
        for comp in article.components.select_related("component"):
            out.extend(expand_article(comp.component, quantity * comp.quantity, depth + 1))
        return out
    if article.is_stocked:
        return [(article, quantity)]
    return []


class JobPosition(models.Model):
    KINDS = [
        ("heading", "Überschrift / Gruppe"),
        ("rental", "Vermietung"),
        ("sale", "Verkauf"),
        ("service", "Dienstleistung"),
        ("staff", "Personal"),
        ("text", "Textzeile"),
    ]
    PRICED = ("rental", "sale", "service", "staff")

    job = models.ForeignKey(Job, verbose_name="Job", on_delete=models.CASCADE, related_name="positions")
    order = models.PositiveIntegerField("Pos.", default=0)
    kind = models.CharField("Art", max_length=10, choices=KINDS, default="rental")
    article = models.ForeignKey("inventory.Article", verbose_name="Artikel", null=True, blank=True,
                                on_delete=models.PROTECT, related_name="job_positions")
    description = models.TextField("Beschreibung", blank=True)
    quantity = models.DecimalField("Menge", max_digits=12, decimal_places=3, default=1)
    unit = models.CharField("Einheit", max_length=20, blank=True, default="Stk")
    unit_price = models.DecimalField("Einzelpreis", max_digits=12, decimal_places=2, default=0)
    factor = models.DecimalField("Tage/Faktor", max_digits=8, decimal_places=2, default=1)
    discount = models.DecimalField("Rabatt %", max_digits=5, decimal_places=2, default=0)
    tax_rate = models.DecimalField("USt %", max_digits=5, decimal_places=2, default=Decimal("19.00"))

    class Meta:
        verbose_name = "Auftragsposition"
        verbose_name_plural = "Auftragspositionen"
        ordering = ["order", "pk"]

    def __str__(self):
        return self.description.split("\n")[0][:80] if self.description else (str(self.article) if self.article else "Position")

    @property
    def is_priced(self):
        return self.kind in self.PRICED

    @property
    def net_total(self):
        if not self.is_priced:
            return Decimal("0")
        value = self.quantity * self.unit_price * self.factor * (Decimal("1") - self.discount / Decimal("100"))
        return value.quantize(TWO, rounding=ROUND_HALF_UP)


class Task(models.Model):
    PRIORITIES = [("low", "Niedrig"), ("normal", "Normal"), ("high", "Hoch")]
    title = models.CharField("Aufgabe", max_length=200)
    description = models.TextField("Beschreibung", blank=True)
    project = models.ForeignKey(Project, verbose_name="Projekt", null=True, blank=True, on_delete=models.CASCADE,
                                related_name="tasks")
    job = models.ForeignKey(Job, verbose_name="Job", null=True, blank=True, on_delete=models.CASCADE,
                            related_name="tasks")
    assignee = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="Zuständig", null=True, blank=True,
                                 on_delete=models.SET_NULL, related_name="tasks")
    due_date = models.DateField("Fällig am", null=True, blank=True)
    priority = models.CharField("Priorität", max_length=10, choices=PRIORITIES, default="normal")
    done = models.BooleanField("Erledigt", default=False)
    done_at = models.DateTimeField("Erledigt am", null=True, blank=True)
    created = models.DateTimeField("Erstellt", auto_now_add=True)

    class Meta:
        verbose_name = "Aufgabe"
        verbose_name_plural = "Aufgaben"
        ordering = ["done", "due_date", "-created"]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if self.done and not self.done_at:
            self.done_at = timezone.now()
        if not self.done:
            self.done_at = None
        super().save(*args, **kwargs)

    @property
    def overdue(self):
        return bool(self.due_date and not self.done and self.due_date < timezone.localdate())


class Appointment(models.Model):
    title = models.CharField("Titel", max_length=200)
    start = models.DateTimeField("Beginn")
    end = models.DateTimeField("Ende", null=True, blank=True)
    all_day = models.BooleanField("Ganztägig", default=False)
    job = models.ForeignKey(Job, verbose_name="Job", null=True, blank=True, on_delete=models.CASCADE,
                            related_name="appointments")
    project = models.ForeignKey(Project, verbose_name="Projekt", null=True, blank=True, on_delete=models.CASCADE,
                                related_name="appointments")
    location = models.CharField("Ort", max_length=200, blank=True)
    participants = models.ManyToManyField("staff.Employee", verbose_name="Teilnehmer", blank=True)
    description = models.TextField("Beschreibung", blank=True)
    color = models.CharField("Farbe", max_length=7, default="#0ea5e9")

    class Meta:
        verbose_name = "Termin"
        verbose_name_plural = "Termine"
        ordering = ["start"]

    def __str__(self):
        return f"{self.title} ({timezone.localtime(self.start):%d.%m.%Y %H:%M})"

    @property
    def end_or_start(self):
        return self.end or (self.start + datetime.timedelta(hours=1))
