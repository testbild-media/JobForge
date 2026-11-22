"""CSV-Import und -Export (Semikolon-getrennt, UTF-8 mit BOM – Excel-freundlich)."""
import csv
import io
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.http import HttpResponse
from django.utils import timezone

EXPORTS = {
    "contacts": {"label": "Kontakte", "perm": "contacts.view_contact"},
    "articles": {"label": "Artikel", "perm": "inventory.view_article"},
    "units": {"label": "Einzelgeräte", "perm": "inventory.view_unit"},
    "stock": {"label": "Lagerbestände", "perm": "inventory.view_stock"},
    "jobs": {"label": "Jobs / Aufträge", "perm": "projects.view_job"},
    "documents": {"label": "Rechnungen & Angebote", "perm": "billing.view_document"},
    "timeentries": {"label": "Zeiteinträge", "perm": "staff.view_all_timeentries"},
    "employees": {"label": "Personal", "perm": "staff.view_employee"},
}

CONTACT_FIELDS = ["number", "contact_type", "is_company", "company_name", "salutation", "first_name", "last_name",
                  "email", "phone", "mobile", "website", "street", "address_extra", "zip_code", "city", "country",
                  "vat_id", "tax_number", "leitweg_id", "discount_percent", "notes", "active"]
ARTICLE_FIELDS = ["number", "name", "kind", "group", "category", "description", "manufacturer", "model_name",
                  "barcode", "unit", "purchase_price", "rental_price", "sale_price", "replacement_value", "weight_kg",
                  "min_stock", "rentable", "sellable", "active"]
UNIT_FIELDS = ["code", "article", "serial_number", "location", "condition", "purchase_date", "purchase_price",
               "warranty_until", "notes"]
STOCK_FIELDS = ["article", "location", "quantity", "defective"]


def _val(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, Decimal):
        return str(value).replace(".", ",")
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _rows(key):
    from billing.models import Document
    from contacts.models import Contact
    from inventory.models import Article, Stock, Unit
    from projects.models import Job
    from staff.models import Employee, TimeEntry

    if key == "contacts":
        yield CONTACT_FIELDS
        for c in Contact.objects.all():
            yield [getattr(c, f) for f in CONTACT_FIELDS]
    elif key == "articles":
        yield ARTICLE_FIELDS
        for a in Article.objects.select_related("group", "category"):
            yield [a.group.name if f == "group" and a.group else a.category.name if f == "category" and a.category
                   else ("" if f in ("group", "category") else getattr(a, f)) for f in ARTICLE_FIELDS]
    elif key == "units":
        yield UNIT_FIELDS
        for u in Unit.objects.select_related("article", "location"):
            yield [u.article.number if f == "article" else (u.location.code if u.location else "") if f == "location"
                   else getattr(u, f) for f in UNIT_FIELDS]
    elif key == "stock":
        yield STOCK_FIELDS + ["article_name", "location_path"]
        for s in Stock.objects.select_related("article", "location"):
            yield [s.article.number, s.location.code, s.quantity, s.defective, s.article.name, s.location.path]
    elif key == "jobs":
        yield ["number", "title", "customer", "status", "start", "end", "venue", "net_total"]
        for j in Job.objects.filter(is_template=False).select_related("customer", "status"):
            yield [j.number, j.title, j.customer.name if j.customer else "", j.status, j.start, j.end, j.venue,
                   j.positions_total()]
    elif key == "documents":
        yield ["number", "type", "status", "date", "due_date", "customer_number", "customer", "net", "tax", "gross",
               "paid", "open"]
        for d in Document.objects.select_related("customer").prefetch_related("positions", "payments"):
            t = d.totals()
            yield [d.number or "", d.get_doc_type_display(), d.get_status_display(), d.date, d.due_date,
                   d.customer.number, d.customer.name, t["net_total"], t["tax_total"], t["gross"], d.paid_amount,
                   d.open_amount]
    elif key == "timeentries":
        yield ["date", "employee", "job", "start", "end", "break_minutes", "hours", "activity", "billable", "approved"]
        for e in TimeEntry.objects.select_related("employee", "job"):
            yield [e.date, str(e.employee), e.job.number if e.job else "", e.start_time, e.end_time,
                   e.break_minutes, e.hours, e.activity, e.billable, e.approved]
    elif key == "employees":
        fields = ["number", "kind", "first_name", "last_name", "email", "phone", "mobile", "position",
                  "hourly_rate", "daily_rate", "active"]
        yield fields
        for e in Employee.objects.all():
            yield [getattr(e, f) for f in fields]


def export_csv(key):
    buf = io.StringIO()
    buf.write("﻿")
    writer = csv.writer(buf, delimiter=";")
    for row in _rows(key):
        writer.writerow([_val(v) for v in row])
    resp = HttpResponse(buf.getvalue(), content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="jobforge-{key}-{timezone.now():%Y%m%d}.csv"'
    return resp


def _dec(value):
    value = (value or "").strip().replace(" ", "")
    if not value:
        return None
    if "," in value:
        value = value.replace(".", "").replace(",", ".")
    try:
        return Decimal(value)
    except InvalidOperation:
        raise ValueError(f"Ungültige Zahl: {value}")


def _bool(value):
    return str(value).strip().lower() in ("1", "ja", "true", "yes", "x", "wahr")


def _read(file):
    raw = file.read()
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    sample = text[:2000]
    delimiter = ";" if sample.count(";") >= sample.count(",") else ","
    return list(csv.DictReader(io.StringIO(text), delimiter=delimiter))


def run_import(target, file, update_existing=True, user=None):
    from contacts.models import Contact
    from inventory.models import Article, ArticleGroup, Category, Location, Stock, Unit

    report = {"created": 0, "updated": 0, "errors": []}
    rows = _read(file)
    for i, row in enumerate(rows, start=2):
        row = {k.strip(): (v or "").strip() for k, v in row.items() if k}
        try:
            with transaction.atomic():
                if target == "contacts":
                    obj = Contact.objects.filter(number=row.get("number")).first() if row.get("number") else None
                    if obj and not update_existing:
                        continue
                    created = obj is None
                    obj = obj or Contact()
                    for f in CONTACT_FIELDS:
                        if f not in row:
                            continue
                        v = row[f]
                        if f in ("is_company", "active"):
                            v = _bool(v)
                        elif f == "discount_percent":
                            v = _dec(v) or Decimal("0")
                        elif f == "contact_type" and v not in dict(Contact.TYPES):
                            v = "customer"
                        setattr(obj, f, v)
                    obj.save()
                elif target == "articles":
                    obj = Article.objects.filter(number=row.get("number")).first() if row.get("number") else None
                    if obj and not update_existing:
                        continue
                    created = obj is None
                    obj = obj or Article()
                    for f in ARTICLE_FIELDS:
                        if f not in row:
                            continue
                        v = row[f]
                        if f == "group":
                            v = ArticleGroup.objects.get_or_create(name=v)[0] if v else None
                        elif f == "category":
                            v = Category.objects.get_or_create(name=v, parent=None)[0] if v else None
                        elif f in ("purchase_price", "rental_price", "sale_price", "replacement_value", "weight_kg"):
                            v = _dec(v)
                        elif f == "min_stock":
                            v = _dec(v) or Decimal("0")
                        elif f in ("rentable", "sellable", "active"):
                            v = _bool(v)
                        elif f == "kind" and v not in dict(Article.KINDS):
                            v = "bulk"
                        setattr(obj, f, v)
                    if not obj.name:
                        raise ValueError("Spalte 'name' fehlt.")
                    obj.save()
                elif target == "units":
                    article = Article.objects.get(number=row["article"])
                    obj = Unit.objects.filter(code=row.get("code")).first() if row.get("code") else None
                    if obj and not update_existing:
                        continue
                    created = obj is None
                    obj = obj or Unit(article=article)
                    obj.article = article
                    obj.serial_number = row.get("serial_number", obj.serial_number)
                    if row.get("code"):
                        obj.code = row["code"]
                    if row.get("location"):
                        obj.location = Location.objects.get(code=row["location"])
                    if row.get("condition") in dict(Unit.CONDITIONS):
                        obj.condition = row["condition"]
                    obj.purchase_price = _dec(row.get("purchase_price")) if row.get("purchase_price") else \
                        obj.purchase_price
                    obj.notes = row.get("notes", obj.notes)
                    obj.save()
                elif target == "stock":
                    from inventory.services import adjust

                    article = Article.objects.get(number=row["article"])
                    location = Location.objects.get(code=row["location"])
                    created = not Stock.objects.filter(article=article, location=location).exists()
                    adjust(article, location, _dec(row.get("quantity")) or Decimal("0"), user, "CSV-Import")
                else:
                    raise ValueError("Unbekanntes Importziel.")
            report["created" if created else "updated"] += 1
        except Exception as e:  # Zeilenfehler sammeln, Import fortsetzen
            report["errors"].append(f"Zeile {i}: {e}")
    return report
