from django.forms import inlineformset_factory

from core.forms import JFCustomModelForm, JFModelForm

from .models import Address, Contact, ContactPerson


class ContactForm(JFCustomModelForm):
    class Meta:
        model = Contact
        exclude = ["custom_data"]
        help_texts = {"number": "Leer lassen für automatische Vergabe."}


PersonFormSet = inlineformset_factory(
    Contact, ContactPerson, form=JFModelForm, extra=1, can_delete=True,
    fields=["salutation", "first_name", "last_name", "position", "email", "phone", "mobile", "is_primary"],
)
AddressFormSet = inlineformset_factory(
    Contact, Address, form=JFModelForm, extra=0, can_delete=True,
    fields=["kind", "label", "street", "zip_code", "city", "country", "notes"],
)
