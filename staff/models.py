import datetime
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone

from core.models import CustomFieldsMixin, NumberSequence


class Qualification(models.Model):
    name = models.CharField("Bezeichnung", max_length=100, unique=True)
    description = models.TextField("Beschreibung", blank=True)

    class Meta:
        verbose_name = "Qualifikation"
        verbose_name_plural = "Qualifikationen"
        ordering = ["name"]

    def __str__(self):
        return self.name


class Employee(CustomFieldsMixin, models.Model):
    KINDS = [("employee", "Festangestellt"), ("parttime", "Teilzeit / Aushilfe"), ("freelancer", "Freelancer")]

    number = models.CharField("Personalnummer", max_length=30, unique=True, blank=True)
    user = models.OneToOneField(settings.AUTH_USER_MODEL, verbose_name="Benutzerkonto", null=True, blank=True,
                                on_delete=models.SET_NULL, related_name="employee")
    kind = models.CharField("Beschäftigungsart", max_length=12, choices=KINDS, default="employee")
    first_name = models.CharField("Vorname", max_length=100)
    last_name = models.CharField("Nachname", max_length=100)
    email = models.EmailField("E-Mail", blank=True)
    phone = models.CharField("Telefon", max_length=50, blank=True)
    mobile = models.CharField("Mobil", max_length=50, blank=True)
    street = models.CharField("Straße & Nr.", max_length=200, blank=True)
    zip_code = models.CharField("PLZ", max_length=20, blank=True)
    city = models.CharField("Ort", max_length=100, blank=True)
    birthday = models.DateField("Geburtstag", null=True, blank=True)
    position = models.CharField("Tätigkeitsbereich", max_length=150, blank=True)
    qualifications = models.ManyToManyField(Qualification, verbose_name="Qualifikationen", blank=True)
    hourly_rate = models.DecimalField("Stundensatz (Verkauf)", max_digits=10, decimal_places=2, null=True, blank=True)
    daily_rate = models.DecimalField("Tagessatz (Verkauf)", max_digits=10, decimal_places=2, null=True, blank=True)
    hourly_cost = models.DecimalField("Interne Kosten / Std.", max_digits=10, decimal_places=2, null=True, blank=True,
                                      help_text="Lohnkosten bzw. Honorar – für Auswertungen")
    weekly_hours = models.DecimalField("Soll-Stunden / Woche", max_digits=5, decimal_places=2, null=True, blank=True)
    color = models.CharField("Farbe", max_length=7, default="#0ea5e9")
    notes = models.TextField("Bemerkungen", blank=True)
    active = models.BooleanField("Aktiv", default=True)
    created = models.DateTimeField("Erstellt", auto_now_add=True)

    class Meta:
        verbose_name = "Mitarbeiter/in"
        verbose_name_plural = "Personal"
        ordering = ["last_name", "first_name"]

    def __str__(self):
        return f"{self.first_name} {self.last_name}"

    def save(self, *args, **kwargs):
        if not self.number:
            self.number = NumberSequence.next("employee")
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("staff:employee_detail", args=[self.pk])

    @property
    def is_freelancer(self):
        return self.kind == "freelancer"


class Availability(models.Model):
    KINDS = [
        ("vacation", "Urlaub"),
        ("sick", "Krank"),
        ("unavailable", "Nicht verfügbar"),
        ("training", "Schulung"),
        ("other", "Sonstige Abwesenheit"),
        ("available", "Verfügbar (Freelancer)"),
    ]
    COLORS = {"vacation": "#22c55e", "sick": "#ef4444", "unavailable": "#64748b", "training": "#a855f7",
              "other": "#94a3b8", "available": "#0ea5e9"}

    employee = models.ForeignKey(Employee, verbose_name="Person", on_delete=models.CASCADE,
                                 related_name="availabilities")
    kind = models.CharField("Art", max_length=12, choices=KINDS, default="vacation")
    start = models.DateField("Von")
    end = models.DateField("Bis")
    note = models.CharField("Bemerkung", max_length=200, blank=True)
    approved = models.BooleanField("Genehmigt", default=True)

    class Meta:
        verbose_name = "Verfügbarkeit / Abwesenheit"
        verbose_name_plural = "Verfügbarkeiten & Abwesenheiten"
        ordering = ["-start"]

    def __str__(self):
        return f"{self.employee}: {self.get_kind_display()} {self.start:%d.%m.}–{self.end:%d.%m.%Y}"

    @property
    def is_absence(self):
        return self.kind != "available"

    @property
    def color(self):
        return self.COLORS.get(self.kind, "#94a3b8")


class Assignment(models.Model):
    """Personaleinsatz / Schicht einer Person in einem Job."""

    STATUSES = [("planned", "Geplant"), ("requested", "Angefragt"), ("confirmed", "Bestätigt"),
                ("declined", "Abgesagt")]
    STATUS_COLORS = {"planned": "#94a3b8", "requested": "#f59e0b", "confirmed": "#16a34a", "declined": "#ef4444"}
    RATE_TYPES = [("hourly", "Stundensatz"), ("daily", "Tagessatz"), ("flat", "Pauschal")]

    job = models.ForeignKey("projects.Job", verbose_name="Job", on_delete=models.CASCADE, related_name="assignments")
    employee = models.ForeignKey(Employee, verbose_name="Person", on_delete=models.PROTECT, related_name="assignments")
    role = models.CharField("Funktion / Schicht", max_length=100, blank=True)
    qualification = models.ForeignKey(Qualification, verbose_name="Benötigte Qualifikation", null=True, blank=True,
                                      on_delete=models.SET_NULL)
    start = models.DateTimeField("Beginn")
    end = models.DateTimeField("Ende")
    status = models.CharField("Status", max_length=10, choices=STATUSES, default="planned")
    rate_type = models.CharField("Abrechnung", max_length=6, choices=RATE_TYPES, default="hourly")
    rate = models.DecimalField("Satz", max_digits=10, decimal_places=2, null=True, blank=True,
                               help_text="Leer = Satz aus dem Personalstamm")
    note = models.CharField("Bemerkung", max_length=200, blank=True)

    class Meta:
        verbose_name = "Personaleinsatz"
        verbose_name_plural = "Personaleinsätze"
        ordering = ["start"]

    def __str__(self):
        return f"{self.employee} – {self.job.title} ({timezone.localtime(self.start):%d.%m. %H:%M})"

    @property
    def hours(self):
        return Decimal((self.end - self.start).total_seconds() / 3600).quantize(Decimal("0.01"))

    @property
    def effective_rate(self):
        if self.rate is not None:
            return self.rate
        if self.rate_type == "daily":
            return self.employee.daily_rate or Decimal("0")
        return self.employee.hourly_rate or Decimal("0")

    @property
    def status_color(self):
        return self.STATUS_COLORS.get(self.status, "#94a3b8")


class TimeEntry(models.Model):
    employee = models.ForeignKey(Employee, verbose_name="Person", on_delete=models.PROTECT, related_name="time_entries")
    job = models.ForeignKey("projects.Job", verbose_name="Job", null=True, blank=True, on_delete=models.SET_NULL,
                            related_name="time_entries")
    project = models.ForeignKey("projects.Project", verbose_name="Projekt", null=True, blank=True,
                                on_delete=models.SET_NULL, related_name="time_entries")
    date = models.DateField("Datum", default=timezone.localdate)
    start_time = models.TimeField("Beginn", null=True, blank=True)
    end_time = models.TimeField("Ende", null=True, blank=True)
    break_minutes = models.PositiveIntegerField("Pause (Min.)", default=0)
    manual_hours = models.DecimalField("Stunden (manuell)", max_digits=6, decimal_places=2, null=True, blank=True,
                                       help_text="Alternativ zu Beginn/Ende")
    activity = models.CharField("Tätigkeit", max_length=200, blank=True)
    billable = models.BooleanField("Abrechenbar", default=True)
    approved = models.BooleanField("Freigegeben", default=False)
    billed = models.BooleanField("Abgerechnet", default=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name="+")
    created = models.DateTimeField("Erfasst", auto_now_add=True)

    class Meta:
        verbose_name = "Zeiteintrag"
        verbose_name_plural = "Zeiterfassung"
        ordering = ["-date", "-start_time"]
        permissions = [
            ("view_all_timeentries", "Zeiten aller Mitarbeitenden sehen"),
            ("approve_timeentry", "Zeiten freigeben"),
        ]

    def __str__(self):
        return f"{self.employee} {self.date:%d.%m.%Y} {self.hours:g} h"

    @property
    def is_running(self):
        return self.start_time is not None and self.end_time is None and self.manual_hours is None

    @property
    def hours(self):
        if self.manual_hours is not None:
            return self.manual_hours
        if self.start_time and self.end_time:
            start = datetime.datetime.combine(self.date, self.start_time)
            end = datetime.datetime.combine(self.date, self.end_time)
            if end < start:  # über Mitternacht
                end += datetime.timedelta(days=1)
            minutes = (end - start).total_seconds() / 60 - self.break_minutes
            return Decimal(max(minutes, 0) / 60).quantize(Decimal("0.01"))
        return Decimal("0")

    @property
    def cost(self):
        return (self.hours * (self.employee.hourly_cost or 0)).quantize(Decimal("0.01"))
