"""Lagerbuchungen: Wareneingang, Ausgabe, Rücknahme, Umlagerung, Defekte, Inventur."""
from decimal import Decimal

from django.db import transaction
from django.db.models import Q, Sum

from .models import Article, Location, Movement, Stock, Unit


class InventoryError(Exception):
    pass


def D(value):
    return Decimal(str(value))


def _stock(article, location):
    stock, _ = Stock.objects.select_for_update().get_or_create(article=article, location=location)
    return stock


def _move(kind, article, user=None, **kwargs):
    return Movement.objects.create(kind=kind, article=article, user=user, **kwargs)


def resolve_code(code):
    """Ermittelt das Objekt zu einem gescannten Code."""
    code = (code or "").strip()
    if not code:
        return None, None
    unit = Unit.objects.select_related("article").filter(code__iexact=code).first()
    if unit:
        return "unit", unit
    loc = Location.objects.filter(code__iexact=code).first()
    if loc:
        return "location", loc
    article = Article.objects.filter(Q(barcode=code) | Q(number__iexact=code)).first()
    if article:
        return "article", article
    unit = Unit.objects.select_related("article").filter(serial_number__iexact=code).first()
    if unit:
        return "unit", unit
    return None, None


@transaction.atomic
def receive(article, quantity, location, user=None, supplier=None, reference="", note="", serials=None,
            unit_price=None):
    quantity = D(quantity)
    if article.kind == "serial":
        serials = [s.strip() for s in (serials or []) if s.strip()]
        count = len(serials) if serials else int(quantity)
        if count <= 0:
            raise InventoryError("Bitte Menge oder Seriennummern angeben.")
        units = []
        for i in range(count):
            unit = Unit.objects.create(
                article=article, serial_number=serials[i] if serials else "", location=location,
                supplier=supplier, purchase_price=unit_price if unit_price is not None else article.purchase_price,
            )
            _move("in", article, user, unit=unit, quantity=1, to_location=location, contact=supplier,
                  reference=reference, note=note)
            units.append(unit)
        return units
    if article.kind not in ("bulk", "consumable"):
        raise InventoryError("Für diesen Artikeltyp wird kein Bestand geführt.")
    if quantity <= 0:
        raise InventoryError("Die Menge muss größer als 0 sein.")
    stock = _stock(article, location)
    stock.quantity += quantity
    stock.save()
    _move("in", article, user, quantity=quantity, to_location=location, contact=supplier, reference=reference,
          note=note)
    return stock


def _site_location_ids(site):
    return site.descendant_ids() if site else None


def _take_bulk(article, quantity, preferred=None, location=None):
    """Verteilt eine Entnahme auf Lagerplätze; gibt [(stock, menge)] zurück."""
    if location is not None:
        stock = _stock(article, location)
        if stock.usable < quantity:
            raise InventoryError(
                f"Nicht genug Bestand von „{article.name}“ an {location}: verfügbar {stock.usable:g}, benötigt {quantity:g}."
            )
        return [(stock, quantity)]
    qs = Stock.objects.select_for_update().filter(article=article)
    candidates = sorted(qs, key=lambda s: (preferred is not None and s.location_id not in preferred, -s.usable))
    plan, remaining = [], quantity
    for stock in candidates:
        if remaining <= 0:
            break
        take = min(stock.usable, remaining)
        if take > 0:
            plan.append((stock, take))
            remaining -= take
    if remaining > 0:
        raise InventoryError(f"Nicht genug Bestand von „{article.name}“: es fehlen {remaining:g} {article.unit}.")
    return plan


@transaction.atomic
def checkout(job, unit=None, article=None, quantity=1, location=None, user=None, note=""):
    """Material an einen Job ausgeben."""
    if unit is not None:
        unit = Unit.objects.select_for_update().get(pk=unit.pk)
        if unit.condition != "ok":
            raise InventoryError(f"{unit} ist nicht einsatzbereit ({unit.get_condition_display()}).")
        if unit.current_job_id and unit.current_job_id != job.pk:
            raise InventoryError(f"{unit} ist bereits an {unit.current_job} ausgegeben.")
        if unit.current_job_id == job.pk:
            raise InventoryError(f"{unit} ist bereits für diesen Job ausgegeben.")
        unit.current_job = job
        unit.save()
        return [_move("out", unit.article, user, unit=unit, quantity=1, from_location=unit.location, job=job,
                      note=note)]
    if article is None:
        raise InventoryError("Kein Artikel angegeben.")
    if article.kind == "serial":
        raise InventoryError(f"„{article.name}“ wird über einzelne Geräte ausgegeben – bitte Gerätecode scannen.")
    quantity = D(quantity)
    preferred = _site_location_ids(job.warehouse) if job.warehouse_id else None
    moves = []
    for stock, take in _take_bulk(article, quantity, preferred, location):
        stock.quantity -= take
        stock.save()
        moves.append(_move("out", article, user, quantity=take, from_location=stock.location, job=job, note=note))
    return moves


def _last_out_location(job, article):
    mv = Movement.objects.filter(job=job, article=article, kind="out").exclude(from_location=None).first()
    return mv.from_location if mv else article.default_location


@transaction.atomic
def checkin(job, unit=None, article=None, quantity=1, location=None, defective=False, user=None, note=""):
    """Material von einem Job zurücknehmen."""
    if unit is not None:
        unit = Unit.objects.select_for_update().get(pk=unit.pk)
        if job is None:
            job = unit.current_job
        if unit.current_job_id is None:
            raise InventoryError(f"{unit} ist nicht ausgegeben.")
        unit.current_job = None
        if location is not None:
            unit.location = location
        moves = [_move("return", unit.article, user, unit=unit, quantity=1, to_location=unit.location, job=job,
                       note=note)]
        if defective:
            unit.condition = "defective"
            moves.append(_move("defect", unit.article, user, unit=unit, quantity=1, job=job,
                               note=note or "Bei Rücknahme als defekt gemeldet"))
        unit.save()
        return moves
    if article is None:
        raise InventoryError("Kein Artikel angegeben.")
    quantity = D(quantity)
    if quantity <= 0:
        raise InventoryError("Die Menge muss größer als 0 sein.")
    location = location or _last_out_location(job, article)
    if location is None:
        raise InventoryError("Bitte einen Lagerort für die Rücknahme wählen.")
    stock = _stock(article, location)
    stock.quantity += quantity
    if defective:
        stock.defective += quantity
    stock.save()
    moves = [_move("return", article, user, quantity=quantity, to_location=location, job=job, note=note)]
    if defective:
        moves.append(_move("defect", article, user, quantity=quantity, to_location=location, job=job,
                           note=note or "Bei Rücknahme als defekt gemeldet"))
    return moves


@transaction.atomic
def consume(job, article, quantity, user=None, note=""):
    """Ausgegebenes Verbrauchsmaterial als verbraucht/verkauft verbuchen (keine Rückgabe erwartet)."""
    quantity = D(quantity)
    balance = job_balance(job).get(article.pk, {}).get("open", Decimal("0"))
    if quantity > balance:
        raise InventoryError(f"Es sind nur {balance:g} {article.unit} „{article.name}“ an diesen Job ausgegeben.")
    return _move("consume", article, user, quantity=quantity, job=job, note=note)


@transaction.atomic
def transfer(article, quantity, from_location, to_location, unit=None, user=None, note=""):
    if unit is not None:
        unit = Unit.objects.select_for_update().get(pk=unit.pk)
        old = unit.location
        unit.location = to_location
        unit.save()
        return _move("transfer", unit.article, user, unit=unit, quantity=1, from_location=old,
                     to_location=to_location, note=note)
    quantity = D(quantity)
    if from_location == to_location:
        raise InventoryError("Quelle und Ziel sind identisch.")
    src = _stock(article, from_location)
    if src.usable < quantity:
        raise InventoryError(f"An {from_location} sind nur {src.usable:g} {article.unit} verfügbar.")
    src.quantity -= quantity
    src.save()
    dst = _stock(article, to_location)
    dst.quantity += quantity
    dst.save()
    return _move("transfer", article, user, quantity=quantity, from_location=from_location, to_location=to_location,
                 note=note)


@transaction.atomic
def set_unit_condition(unit, condition, user=None, note=""):
    unit = Unit.objects.select_for_update().get(pk=unit.pk)
    if unit.condition == condition:
        return None
    unit.condition = condition
    unit.save()
    kind = {"ok": "repair", "lost": "lost", "retired": "lost"}.get(condition, "defect")
    return _move(kind, unit.article, user, unit=unit, quantity=1, from_location=unit.location,
                 note=note or f"Zustand: {unit.get_condition_display()}")


@transaction.atomic
def bulk_condition(article, location, quantity, action, user=None, note=""):
    """action: defect | repair | lost"""
    quantity = D(quantity)
    stock = _stock(article, location)
    if action == "defect":
        if stock.usable < quantity:
            raise InventoryError("Menge übersteigt den einsatzfähigen Bestand.")
        stock.defective += quantity
    elif action == "repair":
        if stock.defective < quantity:
            raise InventoryError("Menge übersteigt den defekten Bestand.")
        stock.defective -= quantity
    elif action == "lost":
        if stock.quantity < quantity:
            raise InventoryError("Menge übersteigt den Bestand.")
        stock.quantity -= quantity
        stock.defective = min(stock.defective, stock.quantity)
    else:
        raise InventoryError("Unbekannte Aktion.")
    stock.save()
    return _move(action, article, user, quantity=quantity, from_location=location, note=note)


@transaction.atomic
def adjust(article, location, new_quantity, user=None, note=""):
    stock = _stock(article, location)
    diff = D(new_quantity) - stock.quantity
    if diff == 0:
        return None
    stock.quantity = D(new_quantity)
    stock.defective = min(stock.defective, stock.quantity)
    stock.save()
    return _move("adjust", article, user, quantity=diff, to_location=location, note=note or "Inventur")


def job_balance(job):
    """Ausgegebene, zurückgegebene und noch offene Mengen je Artikel eines Jobs."""
    rows = Movement.objects.filter(job=job, kind__in=["out", "return", "consume"]).values("article", "kind").annotate(
        q=Sum("quantity"))
    out = {}
    for r in rows:
        entry = out.setdefault(r["article"], {"out": Decimal("0"), "returned": Decimal("0"), "consumed": Decimal("0")})
        key = {"out": "out", "return": "returned", "consume": "consumed"}[r["kind"]]
        entry[key] += r["q"] or 0
    for entry in out.values():
        entry["open"] = entry["out"] - entry["returned"] - entry["consumed"]
    return out
