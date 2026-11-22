"""
XRechnung-Export (UBL 2.1 Invoice, CIUS XRechnung 3.0).
Erzeugt eine strukturierte E-Rechnung nach EN 16931 aus einem festgeschriebenen Dokument.
"""
from decimal import Decimal
from xml.etree import ElementTree as ET

from core.models import CompanySettings

NS_INV = "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
NS_CAC = "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
NS_CBC = "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"
ET.register_namespace("", NS_INV)
ET.register_namespace("cac", NS_CAC)
ET.register_namespace("cbc", NS_CBC)

CUSTOMIZATION_ID = "urn:cen.eu:en16931:2017#compliant#urn:xeinkauf.de:kosit:xrechnung_3.0"
PROFILE_ID = "urn:fdc:peppol.eu:2017:poacc:billing:01:1.0"

TYPE_CODES = {"invoice": "380", "final": "380", "partial": "326", "advance": "326", "credit": "381"}

UNIT_CODES = {
    "stk": "H87", "stück": "H87", "st": "H87", "pcs": "H87", "x": "H87",
    "tag": "DAY", "tage": "DAY", "tg": "DAY", "d": "DAY",
    "std": "HUR", "std.": "HUR", "h": "HUR", "stunde": "HUR", "stunden": "HUR",
    "min": "MIN", "woche": "WEE", "monat": "MON",
    "m": "MTR", "lfm": "MTR", "m²": "MTK", "qm": "MTK", "m2": "MTK", "km": "KMT",
    "kg": "KGM", "g": "GRM", "t": "TNE", "l": "LTR",
    "pauschal": "LS", "psch": "LS", "psch.": "LS", "pausch.": "LS", "set": "SET", "paar": "PR",
}


def unit_code(unit):
    return UNIT_CODES.get((unit or "").strip().lower(), "C62")


def amt(value):
    return f"{Decimal(value).quantize(Decimal('0.01')):.2f}"


def _sub(parent, ns, tag, text=None, **attrs):
    el = ET.SubElement(parent, f"{{{ns}}}{tag}", {k: str(v) for k, v in attrs.items()})
    if text is not None:
        el.text = str(text)
    return el


def cbc(parent, tag, text=None, **attrs):
    return _sub(parent, NS_CBC, tag, text, **attrs)


def cac(parent, tag):
    return _sub(parent, NS_CAC, tag)


def tax_category(parent, tag, rate, small_business):
    cat = cac(parent, tag)
    rate = Decimal(rate)
    if small_business:
        cbc(cat, "ID", "E")
        cbc(cat, "Percent", "0")
        if tag == "TaxCategory":
            cbc(cat, "TaxExemptionReason", "Kein Ausweis von Umsatzsteuer, da Kleinunternehmer gemäß § 19 UStG")
    elif rate == 0:
        cbc(cat, "ID", "Z")
        cbc(cat, "Percent", "0")
    else:
        cbc(cat, "ID", "S")
        cbc(cat, "Percent", f"{rate.normalize():f}")
    scheme = cac(cat, "TaxScheme")
    cbc(scheme, "ID", "VAT")
    return cat


def address(parent, street, zip_code, city, country):
    addr = cac(parent, "PostalAddress")
    if street:
        cbc(addr, "StreetName", street)
    cbc(addr, "CityName", city or "-")
    cbc(addr, "PostalZone", zip_code or "-")
    c = cac(addr, "Country")
    cbc(c, "IdentificationCode", (country or "DE").upper())
    return addr


def build_xrechnung(doc):
    if not doc.is_invoice:
        raise ValueError("XRechnung ist nur für Rechnungen verfügbar.")
    company = CompanySettings.get()
    totals = doc.totals()
    small = totals["small_business"]
    cur = company.currency or "EUR"
    customer = doc.customer

    root = ET.Element(f"{{{NS_INV}}}Invoice")
    cbc(root, "CustomizationID", CUSTOMIZATION_ID)
    cbc(root, "ProfileID", PROFILE_ID)
    cbc(root, "ID", doc.number or f"ENTWURF-{doc.pk}")
    cbc(root, "IssueDate", doc.date.isoformat())
    if doc.due_date:
        cbc(root, "DueDate", doc.due_date.isoformat())
    cbc(root, "InvoiceTypeCode", TYPE_CODES.get(doc.doc_type, "380"))
    notes = [n for n in [doc.subject, doc.intro] if n]
    if small:
        notes.append("Gemäß § 19 UStG wird keine Umsatzsteuer berechnet.")
    for n in notes:
        cbc(root, "Note", n)
    cbc(root, "DocumentCurrencyCode", cur)
    cbc(root, "BuyerReference", doc.buyer_reference or customer.leitweg_id or customer.number or "n/a")
    if doc.service_start or doc.service_end:
        period = cac(root, "InvoicePeriod")
        cbc(period, "StartDate", (doc.service_start or doc.service_end).isoformat())
        cbc(period, "EndDate", (doc.service_end or doc.service_start).isoformat())
    if doc.customer_order_ref:
        order = cac(root, "OrderReference")
        cbc(order, "ID", doc.customer_order_ref)
    refs = []
    if doc.doc_type == "credit" and doc.source and doc.source.number:
        refs.append(doc.source)
    refs.extend(d["document"] for d in totals["deductions"] if d["document"].number)
    for ref in refs:
        br = cac(root, "BillingReference")
        idr = cac(br, "InvoiceDocumentReference")
        cbc(idr, "ID", ref.number)
        cbc(idr, "IssueDate", ref.date.isoformat())
    if doc.job_id:
        pr = cac(root, "ProjectReference")
        cbc(pr, "ID", doc.job.number)

    # Verkäufer
    sp = cac(cac(root, "AccountingSupplierParty"), "Party")
    cbc(sp, "EndpointID", company.email or "rechnung@example.com", schemeID="EM")
    pn = cac(sp, "PartyName")
    cbc(pn, "Name", company.name)
    address(sp, company.street, company.zip_code, company.city, company.country)
    if company.vat_id:
        pts = cac(sp, "PartyTaxScheme")
        cbc(pts, "CompanyID", company.vat_id)
        cbc(cac(pts, "TaxScheme"), "ID", "VAT")
    if company.tax_number:
        pts = cac(sp, "PartyTaxScheme")
        cbc(pts, "CompanyID", company.tax_number)
        cbc(cac(pts, "TaxScheme"), "ID", "FC")
    ple = cac(sp, "PartyLegalEntity")
    cbc(ple, "RegistrationName", company.name)
    if company.register_number:
        cbc(ple, "CompanyID", f"{company.register_court} {company.register_number}".strip())
    contact = cac(sp, "Contact")
    cbc(contact, "Name", company.owner or company.name)
    cbc(contact, "Telephone", company.phone or "-")
    cbc(contact, "ElectronicMail", company.email or "-")

    # Käufer
    bp = cac(cac(root, "AccountingCustomerParty"), "Party")
    if customer.email:
        cbc(bp, "EndpointID", customer.email, schemeID="EM")
    elif customer.leitweg_id:
        cbc(bp, "EndpointID", customer.leitweg_id, schemeID="0204")
    else:
        cbc(bp, "EndpointID", "unbekannt@example.com", schemeID="EM")
    pi = cac(bp, "PartyIdentification")
    cbc(pi, "ID", customer.number)
    pn = cac(bp, "PartyName")
    cbc(pn, "Name", customer.name)
    address(bp, customer.street, customer.zip_code, customer.city, customer.country)
    if customer.vat_id:
        pts = cac(bp, "PartyTaxScheme")
        cbc(pts, "CompanyID", customer.vat_id)
        cbc(cac(pts, "TaxScheme"), "ID", "VAT")
    ple = cac(bp, "PartyLegalEntity")
    cbc(ple, "RegistrationName", customer.name)
    if customer.email or customer.phone:
        c = cac(bp, "Contact")
        person = customer.persons.filter(is_primary=True).first()
        if person:
            cbc(c, "Name", f"{person.first_name} {person.last_name}".strip())
        if customer.phone:
            cbc(c, "Telephone", customer.phone)
        if customer.email:
            cbc(c, "ElectronicMail", customer.email)

    # Zahlung
    if company.iban and doc.doc_type != "credit":
        pm = cac(root, "PaymentMeans")
        cbc(pm, "PaymentMeansCode", "58")
        cbc(pm, "PaymentID", doc.number or "")
        acc = cac(pm, "PayeeFinancialAccount")
        cbc(acc, "ID", company.iban.replace(" ", ""))
        cbc(acc, "Name", company.account_holder or company.name)
        if company.bic:
            cbc(cac(acc, "FinancialInstitutionBranch"), "ID", company.bic)
    else:
        pm = cac(root, "PaymentMeans")
        cbc(pm, "PaymentMeansCode", "1" if doc.doc_type != "credit" else "30")
    if doc.payment_term:
        pt = cac(root, "PaymentTerms")
        text = doc.payment_term.render(doc.due_date)
        if doc.payment_term.discount_percent and doc.payment_term.discount_days:
            text += (f"\n#SKONTO#TAGE={doc.payment_term.discount_days}#"
                     f"PROZENT={doc.payment_term.discount_percent:.2f}#\n")
        cbc(pt, "Note", text)

    # Belegrabatt je Steuersatz
    for b in totals["breakdown"]:
        if b["discount"]:
            ac = cac(root, "AllowanceCharge")
            cbc(ac, "ChargeIndicator", "false")
            cbc(ac, "AllowanceChargeReason", "Rabatt")
            cbc(ac, "MultiplierFactorNumeric", f"{doc.discount_percent:.2f}")
            cbc(ac, "Amount", amt(b["discount"]), currencyID=cur)
            cbc(ac, "BaseAmount", amt(b["net"]), currencyID=cur)
            tax_category(ac, "TaxCategory", b["rate"], small)

    tt = cac(root, "TaxTotal")
    cbc(tt, "TaxAmount", amt(totals["tax_total"]), currencyID=cur)
    for b in totals["breakdown"] or [{"rate": Decimal("0"), "taxable": Decimal("0"), "tax": Decimal("0")}]:
        st = cac(tt, "TaxSubtotal")
        cbc(st, "TaxableAmount", amt(b["taxable"]), currencyID=cur)
        cbc(st, "TaxAmount", amt(b["tax"]), currencyID=cur)
        tax_category(st, "TaxCategory", b["rate"], small)

    lmt = cac(root, "LegalMonetaryTotal")
    cbc(lmt, "LineExtensionAmount", amt(totals["lines_net"]), currencyID=cur)
    cbc(lmt, "TaxExclusiveAmount", amt(totals["net_total"]), currencyID=cur)
    cbc(lmt, "TaxInclusiveAmount", amt(totals["gross"]), currencyID=cur)
    if totals["discount_total"]:
        cbc(lmt, "AllowanceTotalAmount", amt(totals["discount_total"]), currencyID=cur)
    if totals["prepaid"]:
        cbc(lmt, "PrepaidAmount", amt(totals["prepaid"]), currencyID=cur)
    cbc(lmt, "PayableAmount", amt(totals["amount_due"]), currencyID=cur)

    line_no = 0
    for row in doc.rows():
        if row["type"] != "item":
            continue
        p = row["pos"]
        line_no += 1
        qty, price = p.quantity, p.net_unit_price
        if price < 0:
            qty, price = -qty, -price
        line = cac(root, "InvoiceLine")
        cbc(line, "ID", str(line_no))
        if p.details:
            cbc(line, "Note", p.details)
        cbc(line, "InvoicedQuantity", f"{qty.normalize():f}", unitCode=unit_code(p.unit))
        cbc(line, "LineExtensionAmount", amt(p.net_total), currencyID=cur)
        item = cac(line, "Item")
        if p.kind == "rental" and p.factor != 1:
            cbc(item, "Description", f"Miete, {p.factor.normalize():f} Tage")
        cbc(item, "Name", (p.title or p.get_kind_display())[:200])
        if p.article_id:
            cbc(cac(item, "SellersItemIdentification"), "ID", p.article.number)
        tax_category(item, "ClassifiedTaxCategory", p.tax_rate, small)
        pr = cac(line, "Price")
        cbc(pr, "PriceAmount", f"{price.quantize(Decimal('0.0001')).normalize():f}", currencyID=cur)

    ET.indent(root)
    return b'<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="utf-8")
