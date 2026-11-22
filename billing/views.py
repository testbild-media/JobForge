from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.mail import EmailMessage
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from core.crud import Crud, color_badge
from core.models import AuditLog, TaxRate
from projects.forms import AdvanceForm
from projects.models import Job
from projects.views import article_options

from . import services
from .forms import DocumentForm, DocumentPositionFormSet, LayoutForm, PaymentForm, SendForm
from .models import Document, DocumentLayout, Payment
from .pdf import render_html, render_pdf, weasyprint_available
from .xrechnung import build_xrechnung


def doc_status(d):
    return color_badge(d.display_status[1], d.status_color)


def doc_number(d):
    return d.number or f"Entwurf #{d.pk}"


TYPE_GROUPS = {
    "angebote": ("Angebote", ["quote"]),
    "auftragsbestaetigungen": ("Auftragsbestätigungen", ["confirmation"]),
    "rechnungen": ("Rechnungen", list(Document.INVOICE_TYPES)),
}


class DocumentCrud(Crud):
    model = Document
    form_class = DocumentForm
    namespace = "billing"
    name = "document"
    list_display = [("Nummer", doc_number), "doc_type", "date", ("Kunde", "customer__name"), "subject",
                    ("Netto", lambda d: d.totals()["net_total"]), ("Brutto", "gross_total"),
                    ("Offen", lambda d: d.open_amount if d.is_invoice else None), ("Status", doc_status)]
    search_fields = ["number", "subject", "customer__company_name", "customer__last_name", "job__number"]
    list_filters = [
        ("art", "Bereich", [(k, v[0]) for k, v in TYPE_GROUPS.items()], lambda qs, v: qs),
        "doc_type", "status",
        ("offen", "Zahlung", [("1", "Offen"), ("overdue", "Überfällig")], lambda qs, v: (
            qs.filter(status__in=["final", "sent", "partially_paid"], doc_type__in=Document.INVOICE_TYPES)
            .exclude(doc_type="credit") if v == "1" else
            qs.filter(status__in=["final", "sent", "partially_paid"], due_date__lt=timezone.localdate())
            .exclude(doc_type="credit"))),
    ]
    detail_template = "billing/document_detail.html"
    show_notes = True
    show_attachments = True

    @classmethod
    def get_queryset(cls, request):
        qs = Document.objects.select_related("customer", "job", "payment_term").prefetch_related("positions",
                                                                                                 "payments")
        group = TYPE_GROUPS.get(request.GET.get("art", ""))
        if group:
            qs = qs.filter(doc_type__in=group[1])
        return qs

    @classmethod
    def get_initial(cls, request):
        initial = super().get_initial(request)
        initial.setdefault("layout", getattr(DocumentLayout.default(), "pk", None))
        return initial

    @classmethod
    def after_save(cls, request, obj, created):
        if created:
            obj.created_by = request.user
            layout = obj.layout or DocumentLayout.default()
            if layout and not obj.intro and not obj.outro:
                obj.intro, obj.outro = layout.texts_for(obj.doc_type)
            if not obj.payment_term and obj.customer.payment_term:
                obj.payment_term = obj.customer.payment_term
            obj.save()

    @classmethod
    def success_url(cls, obj):
        if not obj.positions.exists() and not obj.is_locked:
            return reverse("billing:document_positions", args=[obj.pk])
        return obj.get_absolute_url()

    @classmethod
    def extra_context(cls, request, obj=None):
        if obj is None:
            return {}
        return {
            "rows": obj.rows(), "totals": obj.totals(), "payments": obj.payments.all(),
            "derived": obj.derived.all(), "pdf_available": weasyprint_available(),
            "payment_form": PaymentForm(initial={"document": obj.pk, "amount": obj.open_amount}),
            "advance_form": AdvanceForm(initial={"percent": 30}),
            "convert_targets": convert_targets(obj),
        }


def convert_targets(doc):
    if doc.doc_type == "quote":
        return [("confirmation", "Auftragsbestätigung"), ("invoice", "Rechnung"), ("advance", "Abschlagsrechnung")]
    if doc.doc_type == "confirmation":
        return [("invoice", "Rechnung"), ("advance", "Abschlagsrechnung"), ("partial", "Teilrechnung"),
                ("final", "Schlussrechnung")]
    if doc.doc_type in ("invoice", "partial", "advance", "final"):
        return [("invoice", "Kopie als neue Rechnung")]
    return []


class PaymentCrud(Crud):
    model = Payment
    form_class = PaymentForm
    namespace = "billing"
    name = "payment"
    list_display = ["date", ("Rechnung", "document"), ("Kunde", "document__customer__name"), "amount", "method",
                    "reference"]
    search_fields = ["document__number", "reference", "note", "document__customer__company_name"]
    list_filters = ["method"]
    has_detail = False

    @classmethod
    def get_queryset(cls, request):
        return Payment.objects.select_related("document", "document__customer")

    @classmethod
    def success_url(cls, obj):
        return obj.document.get_absolute_url()


class LayoutCrud(Crud):
    model = DocumentLayout
    form_class = LayoutForm
    namespace = "billing"
    name = "layout"
    list_display = ["name", "is_default", "logo_position", "font_family"]
    has_detail = False

    @classmethod
    def after_save(cls, request, obj, created):
        if obj.is_default:
            DocumentLayout.objects.exclude(pk=obj.pk).update(is_default=False)


# -- Aktionen ---------------------------------------------------------------

@login_required
@permission_required("billing.change_document", raise_exception=True)
def document_positions(request, pk):
    doc = get_object_or_404(Document, pk=pk)
    if doc.is_locked:
        messages.error(request, "Festgeschriebene Dokumente können nicht mehr geändert werden.")
        return redirect(doc.get_absolute_url())
    formset = DocumentPositionFormSet(request.POST or None, instance=doc, prefix="pos")
    if request.method == "POST":
        if formset.is_valid():
            formset.save()
            doc.save()
            messages.success(request, "Positionen gespeichert.")
            if "continue" in request.POST:
                return redirect("billing:document_positions", pk=doc.pk)
            return redirect(doc.get_absolute_url())
        messages.error(request, "Bitte die markierten Positionen prüfen.")
    factor = doc.job.calc_days if doc.job else Decimal("1")
    return render(request, "billing/document_positions.html", {
        "doc": doc, "formset": formset, "title": f"Positionen – {doc}", "articles": article_options(),
        "default_factor": factor, "default_tax": TaxRate.default_rate(), "back_url": doc.get_absolute_url(),
        "document_mode": True,
    })


@login_required
@permission_required("billing.finalize_document", raise_exception=True)
def document_finalize(request, pk):
    doc = get_object_or_404(Document, pk=pk)
    if request.method == "POST":
        if not doc.positions.exists():
            messages.error(request, "Ein Dokument ohne Positionen kann nicht festgeschrieben werden.")
        else:
            doc.finalize(request.user)
            AuditLog.log(doc, f"{doc} festgeschrieben", request.user)
            messages.success(request, f"{doc} wurde festgeschrieben.")
    return redirect(doc.get_absolute_url())


@login_required
@permission_required("billing.change_document", raise_exception=True)
def document_set_status(request, pk):
    doc = get_object_or_404(Document, pk=pk)
    status = request.POST.get("status")
    allowed = {"sent", "accepted", "rejected"}
    if request.method == "POST" and status in allowed and doc.is_locked:
        doc.status = status
        if status == "sent" and not doc.sent_at:
            doc.sent_at = timezone.now()
        doc.save()
        messages.success(request, f"Status: {doc.get_status_display()}")
    return redirect(doc.get_absolute_url())


@login_required
@permission_required("billing.add_document", raise_exception=True)
def document_convert(request, pk):
    doc = get_object_or_404(Document, pk=pk)
    if request.method != "POST":
        return redirect(doc.get_absolute_url())
    target = request.POST.get("target")
    try:
        if target == "job":
            job = services.job_from_quote(doc, request.user)
            messages.success(request, f"Job {job.number} wurde aus dem Angebot erstellt.")
            return redirect(job.get_absolute_url())
        if target == "advance" and (request.POST.get("percent") or request.POST.get("amount")):
            form = AdvanceForm(request.POST)
            if not form.is_valid() or not doc.job:
                raise services.BillingError("Bitte Prozentsatz/Betrag angeben (nur mit Job möglich).")
            new = services.create_advance(doc.job, form.cleaned_data["percent"], form.cleaned_data["amount"],
                                          request.user, base_document=doc)
        else:
            new = services.convert(doc, target, request.user)
    except services.BillingError as e:
        messages.error(request, str(e))
        return redirect(doc.get_absolute_url())
    messages.success(request, f"{new.get_doc_type_display()} wurde als Entwurf erstellt.")
    return redirect(new.get_absolute_url())


@login_required
@permission_required("billing.add_document", raise_exception=True)
def document_cancel(request, pk):
    doc = get_object_or_404(Document, pk=pk)
    if request.method == "POST":
        try:
            credit = services.cancel_invoice(doc, request.user)
            messages.success(request, "Rechnung storniert – Rechnungskorrektur wurde als Entwurf angelegt.")
            return redirect(credit.get_absolute_url())
        except services.BillingError as e:
            messages.error(request, str(e))
    return redirect(doc.get_absolute_url())


@login_required
@permission_required("billing.add_document", raise_exception=True)
def document_from_job(request, pk):
    job = get_object_or_404(Job, pk=pk)
    if request.method != "POST":
        return redirect(job.get_absolute_url())
    doc_type = request.POST.get("doc_type", "quote")
    try:
        if doc_type == "advance":
            form = AdvanceForm(request.POST)
            if not form.is_valid():
                raise services.BillingError("Bitte Prozentsatz oder Betrag für den Abschlag angeben.")
            doc = services.create_advance(job, form.cleaned_data["percent"], form.cleaned_data["amount"],
                                          request.user)
        else:
            doc = services.document_from_job(job, doc_type, request.user)
    except services.BillingError as e:
        messages.error(request, str(e))
        return redirect(job.get_absolute_url())
    messages.success(request, f"{doc.get_doc_type_display()} wurde als Entwurf erstellt.")
    return redirect(doc.get_absolute_url())


def _filename(doc, ext):
    base = (doc.number or f"Entwurf-{doc.pk}").replace("/", "-")
    return f"{doc.get_doc_type_display().split(' ')[0]}_{base}.{ext}"


@login_required
@permission_required("billing.view_document", raise_exception=True)
def document_pdf(request, pk):
    doc = get_object_or_404(Document, pk=pk)
    pdf = render_pdf(doc)
    if pdf is None:
        messages.warning(request, "PDF-Erzeugung nicht verfügbar (WeasyPrint/Pango fehlt) – Druckansicht wird angezeigt.")
        return redirect("billing:document_preview", pk=doc.pk)
    resp = HttpResponse(pdf, content_type="application/pdf")
    disposition = "attachment" if request.GET.get("download") else "inline"
    resp["Content-Disposition"] = f'{disposition}; filename="{_filename(doc, "pdf")}"'
    return resp


@login_required
@permission_required("billing.view_document", raise_exception=True)
def document_preview(request, pk):
    doc = get_object_or_404(Document, pk=pk)
    return HttpResponse(render_html(doc, preview=True))


@login_required
@permission_required("billing.view_document", raise_exception=True)
def document_xrechnung(request, pk):
    doc = get_object_or_404(Document, pk=pk)
    if not doc.is_invoice:
        messages.error(request, "XRechnung ist nur für Rechnungen verfügbar.")
        return redirect(doc.get_absolute_url())
    if not doc.is_locked:
        messages.warning(request, "Hinweis: Das Dokument ist noch nicht festgeschrieben (Entwurfsnummer).")
    resp = HttpResponse(build_xrechnung(doc), content_type="application/xml")
    resp["Content-Disposition"] = f'attachment; filename="{_filename(doc, "xml")}"'
    return resp


@login_required
@permission_required("billing.change_document", raise_exception=True)
def document_send(request, pk):
    doc = get_object_or_404(Document, pk=pk)
    if not doc.is_locked:
        messages.error(request, "Bitte das Dokument vor dem Versand festschreiben.")
        return redirect(doc.get_absolute_url())
    from core.models import CompanySettings

    company = CompanySettings.get()
    person = doc.customer.persons.filter(is_primary=True).exclude(email="").first()
    initial = {
        "to": (person.email if person else "") or doc.customer.email,
        "subject": f"{doc.get_doc_type_display()} {doc.number} – {company.name}",
        "body": f"Guten Tag,\n\nanbei erhalten Sie unser{'e' if doc.doc_type != 'quote' else ''} "
                f"{doc.get_doc_type_display()} {doc.number}.\n\nMit freundlichen Grüßen\n{company.name}",
        "attach_xml": doc.is_invoice,
    }
    form = SendForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        mail = EmailMessage(d["subject"], d["body"], to=[d["to"]], cc=[d["cc"]] if d["cc"] else None,
                            reply_to=[company.email] if company.email else None)
        pdf = render_pdf(doc)
        if pdf:
            mail.attach(_filename(doc, "pdf"), pdf, "application/pdf")
        if d["attach_xml"] and doc.is_invoice:
            mail.attach(_filename(doc, "xml"), build_xrechnung(doc), "application/xml")
        try:
            mail.send()
        except Exception as e:  # SMTP-Fehler anzeigen
            messages.error(request, f"Versand fehlgeschlagen: {e}")
        else:
            doc.status = "sent" if doc.status in ("final", "draft") else doc.status
            doc.sent_at = timezone.now()
            doc.save()
            AuditLog.log(doc, f"Per E-Mail an {d['to']} versendet", request.user)
            messages.success(request, f"{doc} wurde an {d['to']} versendet.")
            return redirect(doc.get_absolute_url())
    return render(request, "inventory/action_form.html", {"form": form, "title": f"{doc} versenden", "icon": "mail",
                                                          "intro": "PDF wird automatisch angehängt."})


@login_required
@permission_required("billing.add_payment", raise_exception=True)
def payment_add(request, pk):
    doc = get_object_or_404(Document, pk=pk)
    form = PaymentForm(request.POST or None, initial={"document": doc.pk})
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Zahlung erfasst.")
    elif request.method == "POST":
        messages.error(request, "Zahlung konnte nicht gespeichert werden: " + "; ".join(
            f"{k}: {', '.join(v)}" for k, v in form.errors.items()))
    return redirect(doc.get_absolute_url())


@login_required
@permission_required("billing.view_document", raise_exception=True)
def open_items(request):
    docs = [d for d in Document.objects.filter(
        doc_type__in=["invoice", "partial", "advance", "final"], status__in=["final", "sent", "partially_paid"]
    ).select_related("customer").prefetch_related("positions", "payments").order_by("due_date")]
    total = sum((d.open_amount for d in docs), Decimal("0"))
    overdue = [d for d in docs if d.is_overdue]
    return render(request, "billing/open_items.html", {
        "documents": docs, "total": total, "overdue_total": sum((d.open_amount for d in overdue), Decimal("0")),
        "title": "Offene Posten",
    })
