from django import forms
from django.forms import inlineformset_factory

from contacts.models import Contact, ContactPerson
from core.forms import JFCustomModelForm, JFModelForm, StyledFormMixin
from inventory.models import Article, Location

from .models import Appointment, Job, JobPosition, JobStatus, Project, Task


def customer_qs():
    return Contact.objects.filter(contact_type__in=["customer", "both", "other"], active=True)


class ProjectForm(JFCustomModelForm):
    class Meta:
        model = Project
        exclude = ["custom_data", "number"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["customer"].queryset = customer_qs()


class JobForm(JFCustomModelForm):
    class Meta:
        model = Job
        exclude = ["custom_data", "number"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["customer"].queryset = customer_qs()
        self.fields["project"].queryset = Project.objects.filter(is_template=False)
        self.fields["warehouse"].queryset = Location.objects.filter(parent__isnull=True)
        cust = self.initial.get("customer") or (self.instance.customer_id if self.instance.pk else None)
        qs = ContactPerson.objects.select_related("contact")
        self.fields["contact_person"].queryset = qs.filter(contact_id=cust) if cust else qs

    def clean(self):
        data = super().clean()
        start, end = data.get("start"), data.get("end")
        if start and end and end < start:
            self.add_error("end", "Das Ende liegt vor dem Beginn.")
        if data.get("prep_start") and start and data["prep_start"] > start:
            self.add_error("prep_start", "Die Vorbereitung muss vor dem Beginn liegen.")
        if data.get("return_end") and end and data["return_end"] < end:
            self.add_error("return_end", "Die Rückgabe muss nach dem Ende liegen.")
        return data


class PositionForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = JobPosition
        fields = ["order", "kind", "article", "description", "quantity", "unit", "unit_price", "factor", "discount",
                  "tax_rate"]
        widgets = {"description": forms.Textarea(attrs={"rows": 1})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["article"].queryset = Article.objects.filter(active=True).only("id", "name", "number")
        self.fields["article"].required = False


JobPositionFormSet = inlineformset_factory(Job, JobPosition, form=PositionForm, extra=0, can_delete=True)


class TaskForm(JFModelForm):
    class Meta:
        model = Task
        fields = ["title", "description", "project", "job", "assignee", "due_date", "priority", "done"]


class AppointmentForm(JFModelForm):
    class Meta:
        model = Appointment
        fields = ["title", "start", "end", "all_day", "job", "project", "location", "participants", "description",
                  "color"]
        widgets = {"color": forms.TextInput(attrs={"type": "color"}),
                   "participants": forms.CheckboxSelectMultiple}


class StatusForm(forms.Form):
    status = forms.ModelChoiceField(queryset=JobStatus.objects.all())


class JobStatusForm(JFModelForm):
    class Meta:
        model = JobStatus
        fields = "__all__"
        widgets = {"color": forms.TextInput(attrs={"type": "color"})}


class ScanForm(StyledFormMixin, forms.Form):
    MODES = [("out", "Ausgabe"), ("return", "Rücknahme")]
    code = forms.CharField(label="Code", required=False, widget=forms.TextInput(attrs={"autofocus": True,
                                                                                       "autocomplete": "off"}))
    article = forms.ModelChoiceField(label="… oder Artikel wählen", required=False,
                                     queryset=Article.objects.filter(kind__in=["bulk", "consumable"]))
    quantity = forms.DecimalField(label="Menge", initial=1, min_value=0)
    mode = forms.ChoiceField(label="Modus", choices=MODES, widget=forms.RadioSelect, initial="out")
    location = forms.ModelChoiceField(label="Lagerort", required=False, queryset=Location.objects.filter(active=True),
                                      help_text="Optional: Entnahme- bzw. Rückgabeort")
    defective = forms.BooleanField(label="Defekt zurück", required=False)


class FromTemplateForm(StyledFormMixin, forms.Form):
    template = forms.ModelChoiceField(label="Vorlage", queryset=Job.objects.filter(is_template=True))
    title = forms.CharField(label="Bezeichnung des neuen Jobs", required=False)
    customer = forms.ModelChoiceField(label="Kunde", required=False, queryset=Contact.objects.all())
    start = forms.DateTimeField(label="Beginn", required=False)


class AdvanceForm(StyledFormMixin, forms.Form):
    percent = forms.DecimalField(label="Prozent vom Auftragswert", required=False, min_value=0, max_value=100)
    amount = forms.DecimalField(label="… oder Nettobetrag", required=False, min_value=0)

    def clean(self):
        data = super().clean()
        if data.get("percent") is None and data.get("amount") is None:
            raise forms.ValidationError("Bitte Prozentsatz oder Betrag angeben.")
        return data
