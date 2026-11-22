"""PDF-Ausgabe über WeasyPrint (HTML/CSS → PDF). Fällt auf HTML-Druckansicht zurück."""
import base64
import logging
import mimetypes

from django.conf import settings
from django.template.loader import render_to_string

from core.models import CompanySettings

from .models import DocumentLayout
from .services import epc_qr_payload

log = logging.getLogger("jobforge.pdf")


def logo_data_uri(company):
    if not company.logo:
        return None
    try:
        with company.logo.open("rb") as fh:
            data = fh.read()
    except (OSError, ValueError):
        return None
    mime = mimetypes.guess_type(company.logo.name)[0] or "image/png"
    return f"data:{mime};base64,{base64.b64encode(data).decode()}"


def qr_svg(data, size_mm=28):
    import qrcode
    import qrcode.image.svg

    img = qrcode.make(data, image_factory=qrcode.image.svg.SvgPathImage, box_size=10, border=1)
    svg = img.to_string(encoding="unicode")
    return svg.replace("<svg ", f'<svg style="width:{size_mm}mm;height:{size_mm}mm" ', 1)


def footer_columns(company, layout):
    if layout and layout.footer_columns.strip():
        return [c.strip() for c in layout.footer_columns.split("|")]
    cols = [
        "\n".join(x for x in [company.name, company.street, f"{company.zip_code} {company.city}".strip()] if x),
        "\n".join(x for x in [f"Tel. {company.phone}" if company.phone else "", company.email, company.website] if x),
        "\n".join(x for x in [company.bank_name, f"IBAN {company.iban}" if company.iban else "",
                              f"BIC {company.bic}" if company.bic else ""] if x),
        "\n".join(x for x in [
            f"Inhaber/GF: {company.owner}" if company.owner else "",
            f"USt-IdNr. {company.vat_id}" if company.vat_id else "",
            f"St.-Nr. {company.tax_number}" if company.tax_number else "",
            f"{company.register_court} {company.register_number}".strip(),
        ] if x),
    ]
    return [c for c in cols if c]


def document_context(doc):
    company = CompanySettings.get()
    layout = doc.layout or DocumentLayout.default()
    totals = doc.totals()
    payment_text = ""
    if doc.is_invoice and doc.doc_type != "credit" and doc.payment_term:
        payment_text = doc.payment_term.render(doc.due_date)
    qr = epc_qr_payload(doc) if doc.is_locked else None
    return {
        "doc": doc,
        "company": company,
        "layout": layout,
        "accent": (layout.accent_color if layout and layout.accent_color else company.primary_color),
        "rows": doc.rows(),
        "totals": totals,
        "logo": logo_data_uri(company) if layout and layout.logo_position != "none" else None,
        "recipient": doc.recipient or doc.customer.address_text(),
        "payment_text": payment_text,
        "footer": footer_columns(company, layout),
        "qr_svg": qr_svg(qr) if qr else None,
    }


def render_html(doc, preview=False):
    ctx = document_context(doc)
    ctx["preview"] = preview
    return render_to_string("billing/document_pdf.html", ctx)


def weasyprint_available():
    try:
        import weasyprint  # noqa: F401
        return True
    except Exception:  # OSError, wenn Pango fehlt
        return False


def render_pdf(doc):
    try:
        from weasyprint import HTML
    except Exception as e:  # pragma: no cover - abhängig vom System
        log.warning("WeasyPrint nicht verfügbar: %s", e)
        return None
    html = render_html(doc)
    return HTML(string=html, base_url=str(settings.BASE_DIR)).write_pdf()
