from django import forms
from django.contrib.auth.models import Group, User

from .models import CompanySettings, CustomFieldDefinition


class StyledFormMixin:
    """Setzt HTML5-Widgets für Datum/Zeit und kleine Komfortattribute."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            widget = field.widget
            if isinstance(widget, (forms.HiddenInput, forms.MultipleHiddenInput)):
                continue
            new = None
            if isinstance(field, forms.DateTimeField):
                new = forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M")
            elif isinstance(field, forms.DateField):
                new = forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")
            elif isinstance(field, forms.TimeField):
                new = forms.TimeInput(attrs={"type": "time"}, format="%H:%M")
            if new is not None:
                new.is_required = field.required
                new.attrs.update({k: v for k, v in widget.attrs.items() if k not in ("type",)})
                field.widget = new
            elif isinstance(widget, forms.Textarea):
                widget.attrs.setdefault("rows", 3)
            if isinstance(field, forms.DecimalField):
                field.widget.attrs.setdefault("step", "any")


class CustomFieldFormMixin:
    """Ergänzt ein ModelForm um die konfigurierten Zusatzfelder (custom_data)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._custom_defs = list(CustomFieldDefinition.for_model(self._meta.model))
        data = getattr(self.instance, "custom_data", None) or {}
        for d in self._custom_defs:
            name = f"cf_{d.key}"
            kw = {"label": d.label, "required": d.required, "initial": data.get(d.key)}
            if d.field_type == "number":
                field = forms.DecimalField(**kw)
                field.widget.attrs["step"] = "any"
            elif d.field_type == "date":
                field = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"), **kw)
            elif d.field_type == "bool":
                kw["required"] = False
                field = forms.BooleanField(**kw)
            elif d.field_type == "choice":
                field = forms.ChoiceField(choices=[("", "–")] + [(c, c) for c in d.choice_list()], **kw)
            elif d.field_type == "textarea":
                field = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}), **kw)
            elif d.field_type == "url":
                field = forms.URLField(**kw)
            else:
                field = forms.CharField(**kw)
            field.custom = True
            self.fields[name] = field

    def save(self, commit=True):
        instance = super().save(commit=False)
        data = dict(getattr(instance, "custom_data", None) or {})
        for d in self._custom_defs:
            value = self.cleaned_data.get(f"cf_{d.key}")
            if hasattr(value, "isoformat"):
                value = value.isoformat()
            elif value is not None and d.field_type == "number":
                value = float(value)
            data[d.key] = value
        instance.custom_data = data
        if commit:
            instance.save()
            self.save_m2m()
        return instance


class JFModelForm(StyledFormMixin, forms.ModelForm):
    pass


class JFCustomModelForm(CustomFieldFormMixin, StyledFormMixin, forms.ModelForm):
    pass


class CompanySettingsForm(JFModelForm):
    class Meta:
        model = CompanySettings
        fields = "__all__"
        widgets = {
            "primary_color": forms.TextInput(attrs={"type": "color"}),
            "secondary_color": forms.TextInput(attrs={"type": "color"}),
        }


class UserForm(StyledFormMixin, forms.ModelForm):
    password1 = forms.CharField(label="Neues Passwort", widget=forms.PasswordInput, required=False,
                                help_text="Leer lassen, um das Passwort nicht zu ändern.")
    groups = forms.ModelMultipleChoiceField(
        label="Rollen", queryset=Group.objects.order_by("name"), required=False,
        widget=forms.CheckboxSelectMultiple,
    )

    class Meta:
        model = User
        fields = ["username", "first_name", "last_name", "email", "is_active", "is_superuser", "groups"]
        labels = {"is_superuser": "Vollzugriff (Superuser)"}
        help_texts = {"username": "", "is_superuser": "Hat alle Rechte unabhängig von Rollen."}

    def clean_password1(self):
        pw = self.cleaned_data.get("password1")
        if not self.instance.pk and not pw:
            raise forms.ValidationError("Für neue Benutzer ist ein Passwort erforderlich.")
        if pw:
            from django.contrib.auth.password_validation import validate_password

            validate_password(pw, self.instance)
        return pw

    def save(self, commit=True):
        user = super().save(commit=False)
        if self.cleaned_data.get("password1"):
            user.set_password(self.cleaned_data["password1"])
        user.is_staff = user.is_superuser
        if commit:
            user.save()
            self.save_m2m()
        return user


class ImportForm(forms.Form):
    TARGETS = [("contacts", "Kontakte"), ("articles", "Artikel"), ("units", "Einzelgeräte"), ("stock", "Lagerbestände")]
    target = forms.ChoiceField(label="Daten", choices=TARGETS)
    file = forms.FileField(label="CSV-Datei", help_text="Semikolon- oder kommagetrennt, UTF-8. Spalten wie im Export.")
    update_existing = forms.BooleanField(label="Vorhandene Einträge aktualisieren (anhand der Nummer)", required=False,
                                         initial=True)
