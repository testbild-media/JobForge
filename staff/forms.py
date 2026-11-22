from django import forms

from core.forms import JFCustomModelForm, JFModelForm
from projects.models import Job

from .models import Assignment, Availability, Employee, TimeEntry


class EmployeeForm(JFCustomModelForm):
    class Meta:
        model = Employee
        exclude = ["custom_data"]
        widgets = {"color": forms.TextInput(attrs={"type": "color"}),
                   "qualifications": forms.CheckboxSelectMultiple}
        help_texts = {"number": "Leer lassen für automatische Vergabe.",
                      "user": "Verknüpftes Login für Zeiterfassung und „Meine Einsätze“."}


class AvailabilityForm(JFModelForm):
    class Meta:
        model = Availability
        fields = ["employee", "kind", "start", "end", "note", "approved"]

    def clean(self):
        data = super().clean()
        if data.get("start") and data.get("end") and data["end"] < data["start"]:
            self.add_error("end", "Das Ende liegt vor dem Beginn.")
        return data


class AssignmentForm(JFModelForm):
    class Meta:
        model = Assignment
        fields = ["job", "employee", "role", "qualification", "start", "end", "status", "rate_type", "rate", "note"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["job"].queryset = Job.objects.filter(is_template=False).order_by("-start")
        self.fields["employee"].queryset = Employee.objects.filter(active=True)
        job_id = self.initial.get("job")
        if job_id and not self.instance.pk:
            job = Job.objects.filter(pk=job_id).first()
            if job:
                self.initial.setdefault("start", job.start)
                self.initial.setdefault("end", job.end)

    def clean(self):
        data = super().clean()
        if data.get("start") and data.get("end") and data["end"] <= data["start"]:
            self.add_error("end", "Das Ende muss nach dem Beginn liegen.")
        q = data.get("qualification")
        emp = data.get("employee")
        if q and emp and not emp.qualifications.filter(pk=q.pk).exists():
            self.warning = f"{emp} hat die Qualifikation „{q}“ nicht hinterlegt."
        return data


class TimeEntryForm(JFModelForm):
    class Meta:
        model = TimeEntry
        fields = ["employee", "date", "job", "project", "start_time", "end_time", "break_minutes", "manual_hours",
                  "activity", "billable", "approved"]

    user = None
    can_all = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["job"].queryset = Job.objects.filter(is_template=False).order_by("-start")
        if not self.can_all:
            emp = getattr(self.user, "employee", None) if self.user else None
            self.fields["employee"].queryset = Employee.objects.filter(pk=emp.pk) if emp else Employee.objects.none()
            if emp:
                self.fields["employee"].initial = emp.pk
        if not (self.user and self.user.has_perm("staff.approve_timeentry")):
            self.fields.pop("approved")

    def clean(self):
        data = super().clean()
        if not data.get("manual_hours") and not data.get("start_time"):
            raise forms.ValidationError("Bitte Beginn/Ende oder manuelle Stunden angeben.")
        return data
