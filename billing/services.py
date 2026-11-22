"""Erzeugen und Umwandeln von Angeboten, Auftragsbestätigungen und Rechnungen."""
import datetime
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from core.models import CompanySettings, PaymentTerm, TaxRate

from .models import Document, DocumentLayout, DocumentPosition, q2


class BillingError(Exception):
    pass


POSITION_FIELDS = ["order", "kind", "article", "description", "quantity", "unit", "unit_price", "factor", "discount",
                   "tax_rate"]


def new_document(doc_type, customer, job=None, project=None, user=None, source=None):
    if customer is None:
        raise BillingError("Für dieses Dokument muss ein Kunde hinterlegt sein.")
    company = CompanySettings.get()
    layout = DocumentLayout.default()
    intro, outro = layout.texts_for(doc_type) if layout else ("", "")
    term = customer.payment_term or PaymentTerm.objects.filter(is_default=True).first()
    doc = Document(
        doc_type=doc_type, customer=customer, job=job, project=project or (job.project if job else None),
        layout=layout, payment_term=term, intro=intro, outro=outro, created_by=user, source=source,
        buyer_reference=customer.leitweg_id, discount_percent=customer.discount_percent or 0,
        date=timezone.localdate(),
    )
    if doc_type == "quote":
        doc.valid_until = doc.date + datetime.timedelta(days=company.quote_validity_days)
    if job is not None:
        doc.subject = job.title
        if job.start:
            doc.service_start = timezone.localtime(job.start).date()
        if job.end:
            doc.service_end = timezone.localtime(job.end).date()
    if source is not None:
        for f in ["subject", "service_start", "service_end", "recipient", "buyer_reference", "customer_order_ref",
                  "discount_percent", "group_subtotals", "payment_term"]:
            setattr(doc, f, getattr(source, f))
    doc.save()
    return doc


def copy_positions(source_positions, doc):
    objs = [
        DocumentPosition(document=doc, **{f: getattr(p, f) for f in POSITION_FIELDS})
        for p in source_positions
    ]
    DocumentPosition.objects.bulk_create(objs)


@transaction.atomic
def document_from_job(job, doc_type, user=None):
    if doc_type == "advance":
        raise BillingError("Abschlagsrechnungen bitte über „Abschlag erstellen“ anlegen.")
    doc = new_document(doc_type, job.customer, job=job, user=user)
    copy_positions(job.positions.all(), doc)
    if doc_type == "final":
        doc.deducted.set(previous_advances(job))
    return doc


def previous_advances(job):
    return Document.objects.filter(job=job, doc_type__in=["advance", "partial"], finalized_at__isnull=False).exclude(
        status="cancelled")


@transaction.atomic
def create_advance(job, percent=None, amount=None, user=None, base_document=None):
    """Abschlagsrechnung über einen Prozentsatz oder Nettobetrag des Auftragsvolumens."""
    base_positions = list(base_document.positions.all()) if base_document else list(job.positions.all())
    by_rate = {}
    for p in base_positions:
        if p.kind in ("rental", "sale", "service", "staff"):
            by_rate[p.tax_rate] = by_rate.get(p.tax_rate, Decimal("0")) + p.net_total
    total = sum(by_rate.values(), Decimal("0"))
    if not by_rate:
        rate = TaxRate.default_rate()
        by_rate = {rate: Decimal("0")}
    if percent is None and amount is None:
        raise BillingError("Bitte Prozentsatz oder Betrag angeben.")
    doc = new_document("advance", job.customer, job=job, user=user, source=base_document)
    doc.doc_type = "advance"
    doc.save()
    for i, (rate, net) in enumerate(sorted(by_rate.items(), reverse=True)):
        if percent is not None:
            value = q2(net * Decimal(percent) / Decimal("100"))
            label = f"Abschlag {Decimal(percent):g} % auf Auftrag {job.number} – {job.title}"
        else:
            share = (net / total) if total else Decimal("1") / len(by_rate)
            value = q2(Decimal(amount) * share)
            label = f"Abschlag auf Auftrag {job.number} – {job.title}"
        if len(by_rate) > 1:
            label += f" (Anteil {rate:g} % USt)"
        DocumentPosition.objects.create(document=doc, order=(i + 1) * 10, kind="service", description=label,
                                        quantity=1, unit="pauschal", unit_price=value, tax_rate=rate)
    return doc


@transaction.atomic
def convert(source, target_type, user=None):
    if target_type == "advance":
        if not source.job:
            raise BillingError("Abschläge sind nur für Dokumente mit Job möglich.")
        return create_advance(source.job, percent=Decimal("30"), user=user, base_document=source)
    doc = new_document(target_type, source.customer, job=source.job, project=source.project, user=user, source=source)
    copy_positions(source.positions.all(), doc)
    if target_type == "final" and source.job:
        doc.deducted.set(previous_advances(source.job))
    if source.doc_type == "quote" and source.status in ("final", "sent"):
        source.status = "accepted"
        source.save(update_fields=["status", "updated"])
    return doc


@transaction.atomic
def cancel_invoice(invoice, user=None):
    """Storniert eine festgeschriebene Rechnung über eine Rechnungskorrektur."""
    if not invoice.is_invoice or invoice.doc_type == "credit":
        raise BillingError("Nur Rechnungen können storniert werden.")
    if not invoice.is_locked:
        raise BillingError("Entwürfe können einfach gelöscht werden.")
    credit = new_document("credit", invoice.customer, job=invoice.job, project=invoice.project, user=user,
                          source=invoice)
    credit.subject = f"Stornierung der {invoice.get_doc_type_display()} {invoice.number}"
    credit.intro = f"Hiermit stornieren wir die {invoice.get_doc_type_display()} {invoice.number} vom {invoice.date:%d.%m.%Y}."
    credit.save()
    copy_positions(invoice.positions.all(), credit)
    invoice.status = "cancelled"
    invoice.save(update_fields=["status", "updated"])
    return credit


@transaction.atomic
def job_from_quote(quote, user=None):
    from projects.models import Job, JobPosition

    if quote.job_id:
        return quote.job
    job = Job.objects.create(title=quote.subject or f"Auftrag zu {quote.number}", customer=quote.customer,
                             project=quote.project, manager=user,
                             start=timezone.make_aware(datetime.datetime.combine(quote.service_start, datetime.time(8)))
                             if quote.service_start else None,
                             end=timezone.make_aware(datetime.datetime.combine(quote.service_end, datetime.time(18)))
                             if quote.service_end else None)
    JobPosition.objects.bulk_create([
        JobPosition(job=job, **{f: getattr(p, f) for f in POSITION_FIELDS})
        for p in quote.positions.exclude(kind__in=["subtotal", "pagebreak"])
    ])
    quote.job = job
    if quote.status in ("final", "sent"):
        quote.status = "accepted"
    quote.save()
    return job


def epc_qr_payload(doc):
    """GiroCode (EPC-QR) für SEPA-Überweisungen."""
    company = CompanySettings.get()
    if not company.iban or not doc.is_invoice or doc.doc_type == "credit":
        return None
    amount = doc.open_amount if doc.pk else doc.amount_due
    if amount <= 0:
        return None
    lines = ["BCD", "002", "1", "SCT", company.bic or "", (company.account_holder or company.name)[:70],
             company.iban.replace(" ", ""), f"EUR{amount:.2f}", "", "", f"{doc.number or ''}"[:140]]
    return "\n".join(lines)
