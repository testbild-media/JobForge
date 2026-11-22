from django import forms
from django.forms import inlineformset_factory

from contacts.models import Contact
from core.forms import JFCustomModelForm, JFModelForm, StyledFormMixin

from .models import Article, Location, SetComponent, Unit


class ArticleForm(JFCustomModelForm):
    class Meta:
        model = Article
        exclude = ["custom_data"]
        help_texts = {"number": "Leer lassen für automatische Vergabe."}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["supplier"].queryset = Contact.objects.filter(contact_type__in=["supplier", "both"])


SetComponentFormSet = inlineformset_factory(
    Article, SetComponent, fk_name="set_article", form=JFModelForm, fields=["component", "quantity"], extra=2,
    can_delete=True,
)


class UnitForm(JFCustomModelForm):
    class Meta:
        model = Unit
        exclude = ["custom_data", "current_job"]
        help_texts = {"code": "Leer lassen für automatische Vergabe. Kann auch ein vorhandener Barcode sein."}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["article"].queryset = Article.objects.filter(kind="serial")
        self.fields["supplier"].queryset = Contact.objects.filter(contact_type__in=["supplier", "both"])


class LocationForm(JFModelForm):
    class Meta:
        model = Location
        fields = ["name", "kind", "parent", "code", "address", "notes", "active"]
        help_texts = {"code": "Leer lassen für automatische Vergabe.", "parent": "Leer = eigener Lagerstandort"}

    def clean_parent(self):
        parent = self.cleaned_data.get("parent")
        if parent and self.instance.pk and parent.pk in self.instance.descendant_ids():
            raise forms.ValidationError("Ein Lagerort kann nicht unter sich selbst einsortiert werden.")
        return parent


class ReceiveForm(StyledFormMixin, forms.Form):
    article = forms.ModelChoiceField(label="Artikel", queryset=Article.objects.filter(
        kind__in=["serial", "bulk", "consumable"], active=True))
    quantity = forms.DecimalField(label="Menge", min_value=0, initial=1)
    location = forms.ModelChoiceField(label="Lagerort", queryset=Location.objects.filter(active=True))
    supplier = forms.ModelChoiceField(label="Lieferant", required=False,
                                      queryset=Contact.objects.filter(contact_type__in=["supplier", "both"]))
    unit_price = forms.DecimalField(label="Einkaufspreis / Stk.", required=False)
    reference = forms.CharField(label="Lieferschein / Beleg", required=False)
    serials = forms.CharField(label="Seriennummern", required=False, widget=forms.Textarea(attrs={"rows": 4}),
                              help_text="Nur für Einzelgeräte: eine Seriennummer pro Zeile (ersetzt die Menge).")
    note = forms.CharField(label="Bemerkung", required=False)


class TransferForm(StyledFormMixin, forms.Form):
    article = forms.ModelChoiceField(label="Artikel (Mengenartikel)", required=False,
                                     queryset=Article.objects.filter(kind__in=["bulk", "consumable"]))
    unit = forms.ModelChoiceField(label="… oder Einzelgerät", required=False, queryset=Unit.objects.select_related(
        "article").exclude(condition__in=["lost", "retired"]))
    quantity = forms.DecimalField(label="Menge", min_value=0, initial=1, required=False)
    from_location = forms.ModelChoiceField(label="Von Lagerort", required=False, queryset=Location.objects.all())
    to_location = forms.ModelChoiceField(label="Nach Lagerort", queryset=Location.objects.filter(active=True))
    note = forms.CharField(label="Bemerkung", required=False)

    def clean(self):
        data = super().clean()
        if not data.get("article") and not data.get("unit"):
            raise forms.ValidationError("Bitte einen Artikel oder ein Gerät wählen.")
        if data.get("article") and not data.get("from_location"):
            self.add_error("from_location", "Für Mengenartikel bitte den Quell-Lagerort angeben.")
        return data


class AdjustForm(StyledFormMixin, forms.Form):
    article = forms.ModelChoiceField(label="Artikel", queryset=Article.objects.filter(kind__in=["bulk", "consumable"]))
    location = forms.ModelChoiceField(label="Lagerort", queryset=Location.objects.all())
    quantity = forms.DecimalField(label="Gezählter Bestand", min_value=0)
    note = forms.CharField(label="Bemerkung", required=False, initial="Inventur")


class BulkConditionForm(StyledFormMixin, forms.Form):
    ACTIONS = [("defect", "Als defekt markieren"), ("repair", "Repariert / wieder einsatzbereit"),
               ("lost", "Verloren / ausbuchen")]
    article = forms.ModelChoiceField(label="Artikel", queryset=Article.objects.filter(kind__in=["bulk", "consumable"]))
    location = forms.ModelChoiceField(label="Lagerort", queryset=Location.objects.all())
    quantity = forms.DecimalField(label="Menge", min_value=0, initial=1)
    action = forms.ChoiceField(label="Aktion", choices=ACTIONS)
    note = forms.CharField(label="Bemerkung", required=False)


class UnitConditionForm(StyledFormMixin, forms.Form):
    condition = forms.ChoiceField(label="Neuer Zustand", choices=Unit.CONDITIONS)
    note = forms.CharField(label="Bemerkung", required=False)


class AvailabilityForm(StyledFormMixin, forms.Form):
    start = forms.DateTimeField(label="Von")
    end = forms.DateTimeField(label="Bis")
    site = forms.ModelChoiceField(label="Lagerstandort", required=False,
                                  queryset=Location.objects.filter(parent__isnull=True))
    q = forms.CharField(label="Artikel suchen", required=False)
    only_booked = forms.BooleanField(label="Nur gebuchte Artikel", required=False)

    def clean(self):
        data = super().clean()
        if data.get("start") and data.get("end") and data["end"] <= data["start"]:
            raise forms.ValidationError("Das Ende muss nach dem Beginn liegen.")
        return data
