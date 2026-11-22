from core.crud import Crud, color_badge

from .forms import AddressFormSet, ContactForm, PersonFormSet
from .models import Contact


def type_badge(c):
    colors = {"customer": "#0ea5e9", "supplier": "#a855f7", "both": "#6366f1", "other": "#64748b"}
    return color_badge(c.get_contact_type_display(), colors.get(c.contact_type))


class ContactCrud(Crud):
    model = Contact
    form_class = ContactForm
    namespace = "contacts"
    name = "contact"
    list_display = ["number", ("Name", "name"), ("Typ", type_badge), "city", "email", "phone"]
    search_fields = ["number", "company_name", "first_name", "last_name", "email", "city", "phone",
                     "persons__last_name"]
    list_filters = ["contact_type", "active"]
    inlines = [(PersonFormSet, "Ansprechpartner"), (AddressFormSet, "Weitere Adressen")]
    detail_template = "contacts/contact_detail.html"
    show_notes = True
    show_attachments = True

    @classmethod
    def get_queryset(cls, request):
        return Contact.objects.all().prefetch_related("persons")

    @classmethod
    def extra_context(cls, request, obj=None):
        if obj is None:
            return {}
        return {
            "persons": obj.persons.all(),
            "addresses": obj.addresses.all(),
            "projects": obj.projects.select_related("status")[:50],
            "jobs": obj.jobs.filter(is_template=False).select_related("status")[:50],
            "documents": obj.documents.all()[:50],
            "open_amount": sum((d.open_amount for d in obj.documents.filter(
                doc_type__in=["invoice", "partial", "advance", "final"],
                status__in=["final", "sent", "partially_paid"])), 0),
        }
