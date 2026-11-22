from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Sum
from django.urls import reverse

from core.models import CustomFieldsMixin, NumberSequence


class Location(models.Model):
    """Lagerstruktur als Baum: Standort › Gebäude › Raum › Regal › Fach/Schublade › Lagerplatz."""

    KINDS = [
        ("site", "Lagerstandort"),
        ("building", "Gebäude"),
        ("room", "Raum"),
        ("shelf", "Regal"),
        ("compartment", "Fach"),
        ("drawer", "Schublade"),
        ("bin", "Lagerplatz"),
        ("vehicle", "Fahrzeug"),
        ("case", "Case / Kiste"),
        ("other", "Sonstiges"),
    ]

    name = models.CharField("Bezeichnung", max_length=100)
    code = models.CharField("Code", max_length=40, unique=True, blank=True, help_text="Für QR-/Barcode-Etiketten")
    kind = models.CharField("Art", max_length=12, choices=KINDS, default="site")
    parent = models.ForeignKey(
        "self", verbose_name="Übergeordnet", null=True, blank=True, on_delete=models.PROTECT, related_name="children"
    )
    address = models.TextField("Adresse", blank=True, help_text="Nur für Lagerstandorte relevant")
    path = models.CharField("Pfad", max_length=500, blank=True, editable=False)
    notes = models.TextField("Bemerkungen", blank=True)
    active = models.BooleanField("Aktiv", default=True)

    class Meta:
        verbose_name = "Lagerort"
        verbose_name_plural = "Lagerorte"
        ordering = ["path"]

    def __str__(self):
        return self.path or self.name

    def compute_path(self):
        parts, node, seen = [], self, set()
        while node is not None and node.pk not in seen:
            seen.add(node.pk)
            parts.append(node.name)
            node = node.parent
        return " › ".join(reversed(parts))

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = NumberSequence.next("location")
        self.path = self.compute_path()[:500]
        super().save(*args, **kwargs)
        for child in self.children.all():
            child.save()

    @property
    def site(self):
        node = self
        while node.parent_id:
            node = node.parent
        return node

    def descendant_ids(self):
        ids, frontier = [self.pk], [self.pk]
        while frontier:
            frontier = list(Location.objects.filter(parent_id__in=frontier).values_list("pk", flat=True))
            ids.extend(frontier)
        return ids

    def get_absolute_url(self):
        return reverse("inventory:location_detail", args=[self.pk])


class Category(models.Model):
    name = models.CharField("Bezeichnung", max_length=100)
    parent = models.ForeignKey(
        "self", verbose_name="Übergeordnet", null=True, blank=True, on_delete=models.PROTECT, related_name="children"
    )
    order = models.PositiveIntegerField("Reihenfolge", default=0)

    class Meta:
        verbose_name = "Kategorie"
        verbose_name_plural = "Kategorien"
        ordering = ["order", "name"]

    def __str__(self):
        return f"{self.parent} › {self.name}" if self.parent_id else self.name


class ArticleGroup(models.Model):
    name = models.CharField("Bezeichnung", max_length=100, unique=True)
    description = models.TextField("Beschreibung", blank=True)
    color = models.CharField("Farbe", max_length=7, default="#64748b")

    class Meta:
        verbose_name = "Artikelgruppe"
        verbose_name_plural = "Artikelgruppen"
        ordering = ["name"]

    def __str__(self):
        return self.name


class Article(CustomFieldsMixin, models.Model):
    KINDS = [
        ("serial", "Einzelgerät (mit Seriennummer)"),
        ("bulk", "Mengenartikel"),
        ("consumable", "Verbrauchsmaterial"),
        ("set", "Set / Bundle"),
        ("service", "Dienstleistung"),
    ]

    number = models.CharField("Artikelnummer", max_length=40, unique=True, blank=True)
    name = models.CharField("Bezeichnung", max_length=200)
    kind = models.CharField("Art", max_length=12, choices=KINDS, default="bulk")
    group = models.ForeignKey(ArticleGroup, verbose_name="Artikelgruppe", null=True, blank=True, on_delete=models.SET_NULL)
    category = models.ForeignKey(Category, verbose_name="Kategorie", null=True, blank=True, on_delete=models.SET_NULL)
    description = models.TextField("Beschreibung", blank=True)
    manufacturer = models.CharField("Hersteller", max_length=100, blank=True)
    model_name = models.CharField("Modell", max_length=100, blank=True)
    barcode = models.CharField("Barcode / EAN", max_length=64, blank=True, db_index=True)
    unit = models.CharField("Einheit", max_length=20, default="Stk")
    purchase_price = models.DecimalField("Einkaufspreis", max_digits=12, decimal_places=2, null=True, blank=True)
    rental_price = models.DecimalField("Mietpreis / Tag", max_digits=12, decimal_places=2, null=True, blank=True)
    sale_price = models.DecimalField("Verkaufspreis", max_digits=12, decimal_places=2, null=True, blank=True)
    replacement_value = models.DecimalField("Wiederbeschaffungswert", max_digits=12, decimal_places=2, null=True, blank=True)
    tax_rate = models.ForeignKey("core.TaxRate", verbose_name="Steuersatz", null=True, blank=True, on_delete=models.SET_NULL)
    weight_kg = models.DecimalField("Gewicht (kg)", max_digits=10, decimal_places=3, null=True, blank=True)
    min_stock = models.DecimalField("Mindestbestand", max_digits=12, decimal_places=3, default=0)
    default_location = models.ForeignKey(
        Location, verbose_name="Standard-Lagerort", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    supplier = models.ForeignKey(
        "contacts.Contact", verbose_name="Hauptlieferant", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="supplied_articles",
    )
    rentable = models.BooleanField("Vermietbar", default=True)
    sellable = models.BooleanField("Verkaufbar", default=False)
    image = models.ImageField("Bild", upload_to="articles/", blank=True)
    notes = models.TextField("Interne Notizen", blank=True)
    active = models.BooleanField("Aktiv", default=True)
    created = models.DateTimeField("Erstellt", auto_now_add=True)
    updated = models.DateTimeField("Geändert", auto_now=True)

    class Meta:
        verbose_name = "Artikel"
        verbose_name_plural = "Artikel"
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.number})" if self.number else self.name

    def save(self, *args, **kwargs):
        if not self.number:
            self.number = NumberSequence.next("article")
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("inventory:article_detail", args=[self.pk])

    @property
    def is_serial(self):
        return self.kind == "serial"

    @property
    def is_set(self):
        return self.kind == "set"

    @property
    def is_stocked(self):
        return self.kind in ("serial", "bulk", "consumable")

    def total_quantity(self, location_ids=None):
        """Physisch vorhandener Bestand (inkl. defekter Teile, ohne verlorene/ausgemusterte)."""
        if self.kind == "serial":
            qs = self.units.exclude(condition__in=["lost", "retired"])
            if location_ids is not None:
                qs = qs.filter(location_id__in=location_ids)
            return Decimal(qs.count())
        if self.kind in ("bulk", "consumable"):
            qs = self.stock.all()
            if location_ids is not None:
                qs = qs.filter(location_id__in=location_ids)
            return qs.aggregate(s=Sum("quantity"))["s"] or Decimal("0")
        return Decimal("0")

    def usable_quantity(self, location_ids=None):
        """Einsatzfähiger Bestand (ohne defekte/nicht verfügbare Teile)."""
        if self.kind == "serial":
            qs = self.units.filter(condition="ok")
            if location_ids is not None:
                qs = qs.filter(location_id__in=location_ids)
            return Decimal(qs.count())
        if self.kind in ("bulk", "consumable"):
            qs = self.stock.all()
            if location_ids is not None:
                qs = qs.filter(location_id__in=location_ids)
            agg = qs.aggregate(q=Sum("quantity"), d=Sum("defective"))
            return (agg["q"] or 0) - (agg["d"] or 0)
        if self.kind == "set":
            caps = []
            for comp in self.components.select_related("component"):
                if comp.quantity > 0 and comp.component.is_stocked:
                    caps.append((comp.component.usable_quantity(location_ids) / comp.quantity).to_integral_value(
                        rounding="ROUND_FLOOR"))
            return min(caps) if caps else Decimal("0")
        return Decimal("0")

    def price_for(self, kind):
        if kind == "rental":
            return self.rental_price or Decimal("0")
        if kind in ("sale", "service"):
            return self.sale_price or Decimal("0")
        return Decimal("0")


class SetComponent(models.Model):
    set_article = models.ForeignKey(Article, verbose_name="Set", on_delete=models.CASCADE, related_name="components")
    component = models.ForeignKey(Article, verbose_name="Bestandteil", on_delete=models.PROTECT, related_name="used_in_sets")
    quantity = models.DecimalField("Menge", max_digits=10, decimal_places=3, default=1)

    class Meta:
        verbose_name = "Set-Bestandteil"
        verbose_name_plural = "Set-Bestandteile"

    def __str__(self):
        return f"{self.quantity:g} × {self.component.name}"


class Unit(CustomFieldsMixin, models.Model):
    """Ein einzelnes, eindeutig identifizierbares Gerät (z. B. mit Seriennummer)."""

    CONDITIONS = [
        ("ok", "Einsatzbereit"),
        ("defective", "Defekt"),
        ("repair", "In Reparatur"),
        ("unavailable", "Nicht verfügbar"),
        ("lost", "Verloren"),
        ("retired", "Ausgemustert"),
    ]
    CONDITION_COLORS = {"ok": "#16a34a", "defective": "#dc2626", "repair": "#f59e0b", "unavailable": "#64748b",
                        "lost": "#7f1d1d", "retired": "#334155"}

    article = models.ForeignKey(
        Article, verbose_name="Artikel", on_delete=models.PROTECT, related_name="units",
        limit_choices_to={"kind": "serial"},
    )
    code = models.CharField("Code (QR/Barcode)", max_length=64, unique=True, blank=True)
    serial_number = models.CharField("Seriennummer", max_length=100, blank=True, db_index=True)
    location = models.ForeignKey(Location, verbose_name="Lagerort", null=True, blank=True, on_delete=models.SET_NULL,
                                 related_name="units")
    condition = models.CharField("Zustand", max_length=12, choices=CONDITIONS, default="ok")
    current_job = models.ForeignKey(
        "projects.Job", verbose_name="Ausgegeben an Job", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="units_out",
    )
    purchase_date = models.DateField("Kaufdatum", null=True, blank=True)
    purchase_price = models.DecimalField("Einkaufspreis", max_digits=12, decimal_places=2, null=True, blank=True)
    supplier = models.ForeignKey("contacts.Contact", verbose_name="Lieferant", null=True, blank=True,
                                 on_delete=models.SET_NULL, related_name="+")
    warranty_until = models.DateField("Garantie bis", null=True, blank=True)
    notes = models.TextField("Bemerkungen", blank=True)
    created = models.DateTimeField("Erstellt", auto_now_add=True)

    class Meta:
        verbose_name = "Einzelgerät"
        verbose_name_plural = "Einzelgeräte"
        ordering = ["article__name", "code"]

    def __str__(self):
        sn = f" SN {self.serial_number}" if self.serial_number else ""
        return f"{self.article.name} [{self.code}]{sn}"

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = NumberSequence.next("unit")
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("inventory:unit_detail", args=[self.pk])

    @property
    def condition_color(self):
        return self.CONDITION_COLORS.get(self.condition, "#64748b")


class Stock(models.Model):
    """Bestand eines Mengenartikels an einem Lagerort."""

    article = models.ForeignKey(Article, verbose_name="Artikel", on_delete=models.CASCADE, related_name="stock")
    location = models.ForeignKey(Location, verbose_name="Lagerort", on_delete=models.PROTECT, related_name="stock")
    quantity = models.DecimalField("Menge", max_digits=12, decimal_places=3, default=0)
    defective = models.DecimalField("davon defekt", max_digits=12, decimal_places=3, default=0)

    class Meta:
        verbose_name = "Lagerbestand"
        verbose_name_plural = "Lagerbestände"
        unique_together = [("article", "location")]
        ordering = ["article__name", "location__path"]

    def __str__(self):
        return f"{self.article.name} @ {self.location}: {self.quantity:g}"

    @property
    def usable(self):
        return self.quantity - self.defective


class Movement(models.Model):
    KINDS = [
        ("in", "Wareneingang"),
        ("out", "Ausgabe an Job"),
        ("return", "Rückgabe von Job"),
        ("transfer", "Umlagerung"),
        ("consume", "Verbrauch / Verkauf"),
        ("adjust", "Inventurkorrektur"),
        ("defect", "Defekt gemeldet"),
        ("repair", "Repariert / freigegeben"),
        ("lost", "Verloren / ausgebucht"),
    ]

    timestamp = models.DateTimeField("Zeitpunkt", auto_now_add=True, db_index=True)
    kind = models.CharField("Vorgang", max_length=10, choices=KINDS)
    article = models.ForeignKey(Article, verbose_name="Artikel", on_delete=models.PROTECT, related_name="movements")
    unit = models.ForeignKey(Unit, verbose_name="Gerät", null=True, blank=True, on_delete=models.SET_NULL,
                             related_name="movements")
    quantity = models.DecimalField("Menge", max_digits=12, decimal_places=3, default=1)
    from_location = models.ForeignKey(Location, verbose_name="Von", null=True, blank=True, on_delete=models.SET_NULL,
                                      related_name="+")
    to_location = models.ForeignKey(Location, verbose_name="Nach", null=True, blank=True, on_delete=models.SET_NULL,
                                    related_name="+")
    job = models.ForeignKey("projects.Job", verbose_name="Job", null=True, blank=True, on_delete=models.SET_NULL,
                            related_name="movements")
    contact = models.ForeignKey("contacts.Contact", verbose_name="Lieferant/Kunde", null=True, blank=True,
                                on_delete=models.SET_NULL, related_name="+")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="Benutzer", null=True, blank=True,
                             on_delete=models.SET_NULL)
    reference = models.CharField("Beleg / Referenz", max_length=100, blank=True)
    note = models.CharField("Bemerkung", max_length=300, blank=True)

    class Meta:
        verbose_name = "Lagerbewegung"
        verbose_name_plural = "Lagerbewegungen"
        ordering = ["-timestamp"]

    def __str__(self):
        return f"{self.get_kind_display()}: {self.quantity:g} × {self.article.name}"
