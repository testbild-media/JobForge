from django import forms
from django.forms import inlineformset_factory

from contacts.models import Contact
from core.forms import JFModelForm, StyledFormMixin
from inventory.models import Article

from .models import Document, DocumentLayout, DocumentPosition, Payment


class DocumentForm(JFModelForm):
    class Meta:
        model = Document
        fields = ["doc_type", "customer", "job", "project", "date", "service_start", "service_end", "valid_until",
                  "due_date", "payment_term", "subject", "customer_order_ref", "buyer_reference", "recipient",
                  "intro", "outro", "discount_percent", "group_subtotals", "layout"]
        widgets = {"recipient": forms.Textarea(attrs={"rows": 4})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["customer"].queryset = Contact.objects.filter(contact_type__in=["customer", "both", "other"])
        if self.instance.pk and self.instance.is_locked:
            for name in ["doc_type", "customer", "date", "discount_percent"]:
                self.fields[name].disabled = True


class DocumentPositionForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = DocumentPosition
        fields = ["order", "kind", "article", "description", "quantity", "unit", "unit_price", "factor", "discount",
                  "tax_rate"]
        widgets = {"description": forms.Textarea(attrs={"rows": 1})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["article"].queryset = Article.objects.filter(active=True).only("id", "name", "number")
        self.fields["article"].required = False


DocumentPositionFormSet = inlineformset_factory(Document, DocumentPosition, form=DocumentPositionForm, extra=0,
                                                can_delete=True)


class PaymentForm(JFModelForm):
    class Meta:
        model = Payment
        fields = ["document", "date", "amount", "method", "reference", "note"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["document"].queryset = Document.objects.filter(
            doc_type__in=Document.INVOICE_TYPES, finalized_at__isnull=False).exclude(status="cancelled")


class LayoutForm(JFModelForm):
    class Meta:
        model = DocumentLayout
        fields = "__all__"
        widgets = {"accent_color": forms.TextInput(attrs={"placeholder": "#e8590c"}),
                   "custom_css": forms.Textarea(attrs={"rows": 6, "class": "mono"})}


class SendForm(StyledFormMixin, forms.Form):
    to = forms.EmailField(label="Empfänger")
    cc = forms.EmailField(label="CC", required=False)
    subject = forms.CharField(label="Betreff")
    body = forms.CharField(label="Nachricht", widget=forms.Textarea(attrs={"rows": 8}))
    attach_xml = forms.BooleanField(label="XRechnung (XML) anhängen", required=False)
