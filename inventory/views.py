import datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.db.models import Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from core.crud import Crud, color_badge, fmt
from planning.availability import article_availability, bookings

from . import services
from .forms import (AdjustForm, ArticleForm, AvailabilityForm, BulkConditionForm, LocationForm, ReceiveForm,
                    SetComponentFormSet, TransferForm, UnitConditionForm, UnitForm)
from .models import Article, ArticleGroup, Category, Location, Movement, Stock, Unit


def _stock_cell(a):
    if not a.is_stocked and not a.is_set:
        return "–"
    usable, total = a.usable_quantity(), a.total_quantity() if a.is_stocked else a.usable_quantity()
    text = f"{fmt(usable)} {a.unit}"
    if a.is_stocked and total != usable:
        text += f" (von {fmt(total)})"
    if a.kind == "consumable" and a.min_stock and usable < a.min_stock:
        return color_badge(text + " – Mindestbestand!", "#dc2626")
    return text


class ArticleCrud(Crud):
    model = Article
    form_class = ArticleForm
    namespace = "inventory"
    name = "article"
    list_display = ["number", "name", ("Art", "kind"), ("Gruppe", "group"), ("Kategorie", "category"),
                    ("Bestand", _stock_cell), ("Miete/Tag", "rental_price"), ("VK", "sale_price")]
    search_fields = ["number", "name", "manufacturer", "model_name", "barcode", "description"]
    list_filters = ["kind", "group", "category", "active"]
    inlines = [(SetComponentFormSet, "Set-Bestandteile (nur für Sets / Bundles)")]
    detail_template = "inventory/article_detail.html"
    show_notes = True
    show_attachments = True
    list_actions = [("Wareneingang", "inventory:receive", "download", "inventory.add_movement"),
                    ("Etiketten", "inventory:labels", "qr", "inventory.view_article")]

    @classmethod
    def get_queryset(cls, request):
        return Article.objects.select_related("group", "category")

    @classmethod
    def extra_context(cls, request, obj=None):
        if obj is None:
            return {}
        now = timezone.now()
        horizon = now + datetime.timedelta(days=60)
        upcoming = bookings(now, horizon, article_ids={obj.pk}).get(obj.pk, [])
        return {
            "stock": obj.stock.select_related("location").order_by("location__path"),
            "units": obj.units.select_related("location", "current_job"),
            "components": obj.components.select_related("component"),
            "used_in": obj.used_in_sets.select_related("set_article"),
            "movements": obj.movements.select_related("unit", "from_location", "to_location", "job", "user")[:30],
            "avail_now": article_availability(obj, now, now + datetime.timedelta(hours=1)),
            "avail_30": article_availability(obj, now, now + datetime.timedelta(days=30)),
            "upcoming": sorted(upcoming, key=lambda x: x[0]),
        }


class UnitCrud(Crud):
    model = Unit
    form_class = UnitForm
    namespace = "inventory"
    name = "unit"
    list_display = ["code", ("Artikel", "article__name"), "serial_number", ("Lagerort", "location"),
                    ("Zustand", lambda u: color_badge(u.get_condition_display(), u.condition_color)),
                    ("Ausgegeben an", "current_job")]
    search_fields = ["code", "serial_number", "article__name", "article__number", "notes"]
    list_filters = ["condition", ("out", "Ausgegeben", [("1", "Ja"), ("0", "Nein")],
                                  lambda qs, v: qs.filter(current_job__isnull=(v == "0")))]
    detail_template = "inventory/unit_detail.html"
    show_notes = True
    show_attachments = True
    list_actions = [("Etiketten", "inventory:labels", "qr", "inventory.view_unit")]

    @classmethod
    def get_queryset(cls, request):
        qs = Unit.objects.select_related("article", "location", "current_job")
        if request.GET.get("article"):
            qs = qs.filter(article_id=request.GET["article"])
        return qs

    @classmethod
    def extra_context(cls, request, obj=None):
        if obj is None:
            return {}
        return {
            "movements": obj.movements.select_related("job", "from_location", "to_location", "user")[:50],
            "condition_form": UnitConditionForm(initial={"condition": obj.condition}),
        }


class LocationCrud(Crud):
    model = Location
    form_class = LocationForm
    namespace = "inventory"
    name = "location"
    list_display = [("Lagerort", "path"), "code", "kind", "active"]
    search_fields = ["name", "code", "path"]
    list_filters = ["kind", "active"]
    paginate_by = 200
    detail_template = "inventory/location_detail.html"
    list_actions = [("Etiketten", "inventory:labels", "qr", "inventory.view_location")]

    @classmethod
    def extra_context(cls, request, obj=None):
        if obj is None:
            return {}
        ids = obj.descendant_ids()
        return {
            "children": obj.children.all(),
            "stock": Stock.objects.filter(location_id__in=ids, quantity__gt=0).select_related("article", "location"),
            "units": Unit.objects.filter(location_id__in=ids).select_related("article", "location", "current_job"),
        }


class CategoryCrud(Crud):
    model = Category
    namespace = "inventory"
    name = "category"
    fields = ["name", "parent", "order"]
    list_display = [("Kategorie", str), "order"]
    search_fields = ["name"]
    has_detail = False


class GroupCrud(Crud):
    model = ArticleGroup
    namespace = "inventory"
    name = "group"
    fields = ["name", "description", "color"]
    list_display = ["name", "description"]
    search_fields = ["name"]
    has_detail = False


class StockCrud(Crud):
    model = Stock
    namespace = "inventory"
    name = "stock"
    fields = ["article", "location", "quantity", "defective"]
    list_display = [("Artikel", "article"), ("Lagerort", "location"), "quantity", "defective"]
    search_fields = ["article__name", "article__number", "location__path"]
    list_filters = ["location"]
    has_detail = False
    list_actions = [("Inventur", "inventory:adjust", "edit", "inventory.change_stock")]

    @classmethod
    def get_queryset(cls, request):
        return Stock.objects.select_related("article", "location").filter(quantity__gt=0)


class MovementCrud(Crud):
    model = Movement
    namespace = "inventory"
    name = "movement"
    fields = ["kind", "article", "quantity", "note"]
    list_display = ["timestamp", "kind", ("Artikel", "article__name"), ("Gerät", "unit__code"), "quantity",
                    ("Von", "from_location"), ("Nach", "to_location"), ("Job", "job"), ("Benutzer", "user")]
    search_fields = ["article__name", "article__number", "unit__code", "job__number", "note", "reference"]
    list_filters = ["kind"]
    has_detail = False
    list_actions = [("Wareneingang", "inventory:receive", "download", "inventory.add_movement"),
                    ("Umlagerung", "inventory:transfer", "repeat", "inventory.add_movement")]

    @classmethod
    def get_queryset(cls, request):
        return Movement.objects.select_related("article", "unit", "from_location", "to_location", "job", "user")


def _run(request, func, success):
    try:
        result = func()
    except services.InventoryError as e:
        messages.error(request, str(e))
        return None
    messages.success(request, success)
    return result or True


@login_required
@permission_required("inventory.add_movement", raise_exception=True)
def receive(request):
    form = ReceiveForm(request.POST or None, initial={"article": request.GET.get("article")})
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        ok = _run(request, lambda: services.receive(
            d["article"], d["quantity"], d["location"], user=request.user, supplier=d["supplier"],
            reference=d["reference"], note=d["note"], serials=d["serials"].splitlines(), unit_price=d["unit_price"],
        ), f"Wareneingang für „{d['article'].name}“ gebucht.")
        if ok:
            return redirect(d["article"].get_absolute_url())
    return render(request, "inventory/action_form.html", {
        "form": form, "title": "Wareneingang", "icon": "download",
        "intro": "Neue Ware oder neue Geräte einbuchen. Für Einzelgeräte werden automatisch Gerätecodes erzeugt."})


@login_required
@permission_required("inventory.add_movement", raise_exception=True)
def transfer(request):
    initial = {k: request.GET.get(k) for k in ("article", "unit", "from_location") if request.GET.get(k)}
    form = TransferForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        ok = _run(request, lambda: services.transfer(
            d["article"] or (d["unit"].article if d["unit"] else None), d["quantity"] or 1, d["from_location"],
            d["to_location"], unit=d["unit"], user=request.user, note=d["note"]), "Umlagerung gebucht.")
        if ok:
            return redirect("inventory:movement_list")
    return render(request, "inventory/action_form.html", {"form": form, "title": "Umlagerung", "icon": "repeat"})


@login_required
@permission_required("inventory.change_stock", raise_exception=True)
def adjust(request):
    form = AdjustForm(request.POST or None, initial={k: request.GET.get(k) for k in ("article", "location")})
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        if _run(request, lambda: services.adjust(d["article"], d["location"], d["quantity"], request.user, d["note"]),
                "Bestand korrigiert."):
            return redirect("inventory:stock_list")
    return render(request, "inventory/action_form.html", {
        "form": form, "title": "Inventur / Bestandskorrektur", "icon": "edit",
        "intro": "Gezählten Bestand eintragen – die Differenz wird als Korrekturbuchung protokolliert."})


@login_required
@permission_required("inventory.add_movement", raise_exception=True)
def bulk_condition(request):
    form = BulkConditionForm(request.POST or None, initial={k: request.GET.get(k) for k in ("article", "location")})
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        if _run(request, lambda: services.bulk_condition(d["article"], d["location"], d["quantity"], d["action"],
                                                         request.user, d["note"]), "Buchung gespeichert."):
            return redirect("inventory:defects")
    return render(request, "inventory/action_form.html", {
        "form": form, "title": "Defekt / Verlust (Mengenartikel)", "icon": "tool"})


@login_required
@permission_required("inventory.change_unit", raise_exception=True)
def unit_condition(request, pk):
    unit = get_object_or_404(Unit, pk=pk)
    form = UnitConditionForm(request.POST)
    if form.is_valid():
        services.set_unit_condition(unit, form.cleaned_data["condition"], request.user, form.cleaned_data["note"])
        messages.success(request, "Zustand aktualisiert.")
    return redirect(unit.get_absolute_url())


@login_required
@permission_required("inventory.view_unit", raise_exception=True)
def defects(request):
    units = Unit.objects.exclude(condition__in=["ok", "retired"]).select_related("article", "location")
    stock = Stock.objects.filter(defective__gt=0).select_related("article", "location")
    out_units = Unit.objects.filter(current_job__isnull=False).select_related("article", "current_job")
    overdue = [u for u in out_units if (u.current_job.period_end and u.current_job.period_end < timezone.now())]
    low = [a for a in Article.objects.filter(kind="consumable", active=True, min_stock__gt=0)
           if a.usable_quantity() < a.min_stock]
    return render(request, "inventory/defects.html", {"units": units, "stock": stock, "overdue": overdue, "low": low,
                                                      "title": "Defekte & Fehlbestände"})


@login_required
def scan(request):
    """Universeller Scanner: Code nachschlagen und zum Objekt springen."""
    code = request.GET.get("code", "").strip()
    if code:
        kind, obj = services.resolve_code(code)
        if obj is not None:
            return redirect(obj.get_absolute_url())
        from projects.models import Job

        job = Job.objects.filter(number__iexact=code).first()
        if job:
            return redirect(job.get_absolute_url())
        messages.warning(request, f"Kein Gerät, Artikel oder Lagerort mit dem Code „{code}“ gefunden.")
    return render(request, "inventory/scan.html", {"title": "Scanner"})


@login_required
def qr_svg(request, code):
    import qrcode
    import qrcode.image.svg

    img = qrcode.make(code, image_factory=qrcode.image.svg.SvgPathImage, box_size=10, border=1)
    resp = HttpResponse(img.to_string(), content_type="image/svg+xml")
    resp["Cache-Control"] = "max-age=86400"
    return resp


@login_required
def labels(request):
    """Druckbare QR-Etiketten für Geräte, Artikel oder Lagerorte."""
    items = []
    ids = [i for i in request.GET.getlist("id") if i.isdigit()]
    kind = request.GET.get("kind", "unit")
    if kind == "unit":
        qs = Unit.objects.select_related("article", "location")
        if request.GET.get("article"):
            qs = qs.filter(article_id=request.GET["article"])
        qs = qs.filter(pk__in=ids) if ids else qs.exclude(condition__in=["lost", "retired"])
        items = [{"code": u.code, "title": u.article.name, "sub": f"SN {u.serial_number}" if u.serial_number else ""}
                 for u in qs[:500]]
    elif kind == "article":
        qs = Article.objects.filter(pk__in=ids) if ids else Article.objects.filter(active=True)
        items = [{"code": a.barcode or a.number, "title": a.name, "sub": a.number} for a in qs[:500]]
    elif kind == "location":
        qs = Location.objects.filter(pk__in=ids) if ids else Location.objects.filter(active=True)
        items = [{"code": loc.code, "title": loc.name, "sub": loc.path} for loc in qs[:500]]
    return render(request, "inventory/labels.html", {"items": items, "kind": kind, "title": "Etiketten"})


@login_required
@permission_required("inventory.view_article", raise_exception=True)
def availability(request):
    now = timezone.localtime().replace(minute=0, second=0, microsecond=0)
    data = request.GET if request.GET.get("start") else None
    form = AvailabilityForm(data, initial={"start": now, "end": now + datetime.timedelta(days=3)})
    rows = []
    if form.is_valid():
        d = form.cleaned_data
        qs = Article.objects.filter(active=True, kind__in=["serial", "bulk", "consumable", "set"])
        if d.get("q"):
            qs = qs.filter(Q(name__icontains=d["q"]) | Q(number__icontains=d["q"]) | Q(group__name__icontains=d["q"]))
        if d.get("only_booked"):
            booked_ids = set(bookings(d["start"], d["end"]).keys())
            qs = qs.filter(pk__in=booked_ids)
        for article in qs.select_related("group")[:300]:
            rows.append(article_availability(article, d["start"], d["end"], site=d.get("site")))
    return render(request, "inventory/availability.html", {"form": form, "rows": rows,
                                                           "title": "Verfügbarkeitsprüfung"})


@login_required
def article_lookup(request):
    """Kleine JSON-Hilfe für den Positionseditor."""
    article = get_object_or_404(Article, pk=request.GET.get("id"))
    return JsonResponse({
        "id": article.pk, "name": article.name, "number": article.number, "unit": article.unit,
        "rental_price": str(article.rental_price or 0), "sale_price": str(article.sale_price or 0),
        "tax_rate": str(article.tax_rate.rate) if article.tax_rate else None, "kind": article.kind,
        "description": article.description,
    })
