from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from core.crud import Crud, color_badge, fmt
from core.models import TaxRate
from inventory import services as inv
from inventory.models import Article, Unit
from planning.availability import job_material_check

from . import services
from .forms import (AdvanceForm, AppointmentForm, FromTemplateForm, JobForm, JobPositionFormSet, JobStatusForm,
                    ProjectForm, ScanForm, StatusForm, TaskForm)
from .models import Appointment, Job, JobStatus, Project, Task


def status_badge(obj):
    return color_badge(obj.status.name, obj.status.color) if obj.status else "–"


def period(job):
    if not job.start:
        return "–"
    s = timezone.localtime(job.start)
    if not job.end:
        return f"{s:%d.%m.%Y %H:%M}"
    e = timezone.localtime(job.end)
    if s.date() == e.date():
        return f"{s:%d.%m.%Y %H:%M}–{e:%H:%M}"
    return f"{s:%d.%m.%Y} – {e:%d.%m.%Y}"


class ProjectCrud(Crud):
    model = Project
    form_class = ProjectForm
    namespace = "projects"
    name = "project"
    list_display = ["number", "name", ("Kunde", "customer__name"), ("Status", status_badge), "start_date",
                    "end_date", ("Leitung", "manager")]
    search_fields = ["number", "name", "customer__company_name", "customer__last_name", "description"]
    list_filters = ["status", "manager", ("vorlagen", "Ansicht", [("1", "Vorlagen")], lambda qs, v: qs)]
    detail_template = "projects/project_detail.html"
    show_notes = True
    show_attachments = True

    @classmethod
    def get_queryset(cls, request):
        templates = request.GET.get("vorlagen") == "1"
        return Project.objects.filter(is_template=templates).select_related("customer", "status", "manager")

    @classmethod
    def extra_context(cls, request, obj=None):
        if obj is None:
            return {}
        jobs = obj.jobs.select_related("status", "customer")
        docs = obj.documents.select_related("customer")
        invoiced = sum((d.totals()["net_total"] for d in docs if d.is_invoice and d.is_locked and
                        d.status != "cancelled" and d.doc_type != "credit"), Decimal("0"))
        hours = obj.time_entries.all()
        job_hours = sum((t.hours for j in jobs for t in j.time_entries.all()), Decimal("0"))
        return {
            "jobs": jobs, "documents": docs, "tasks": obj.tasks.select_related("assignee", "job"),
            "appointments": obj.appointments.all(), "invoiced": invoiced,
            "volume": sum((j.positions_total() for j in jobs), Decimal("0")),
            "hours": sum((t.hours for t in hours), Decimal("0")) + job_hours,
        }


class JobCrud(Crud):
    model = Job
    form_class = JobForm
    namespace = "projects"
    name = "job"
    list_display = ["number", "title", ("Kunde", "customer__name"), ("Zeitraum", period), ("Status", status_badge),
                    ("Einsatzort", "venue"), ("Projekt", "project")]
    search_fields = ["number", "title", "customer__company_name", "customer__last_name", "venue", "description"]
    list_filters = ["status", "manager", "warehouse",
                    ("zeit", "Zeitraum", [("upcoming", "Kommende"), ("past", "Vergangene"), ("open", "Offene")],
                     lambda qs, v: {
                         "upcoming": lambda: qs.filter(end__gte=timezone.now()),
                         "past": lambda: qs.filter(end__lt=timezone.now()),
                         "open": lambda: qs.filter(status__is_closed=False),
                     }[v]()),
                    ("vorlagen", "Ansicht", [("1", "Vorlagen")], lambda qs, v: qs)]
    detail_template = "projects/job_detail.html"
    show_notes = True
    show_attachments = True

    @classmethod
    def get_queryset(cls, request):
        templates = request.GET.get("vorlagen") == "1"
        return Job.objects.filter(is_template=templates).select_related("customer", "status", "project", "manager")

    @classmethod
    def get_initial(cls, request):
        initial = super().get_initial(request)
        project_id = request.GET.get("project")
        if project_id:
            project = Project.objects.filter(pk=project_id).first()
            if project and project.customer_id:
                initial.setdefault("customer", project.customer_id)
        return initial

    @classmethod
    def extra_context(cls, request, obj=None):
        if obj is None:
            return {}
        positions = list(obj.positions.select_related("article"))
        balance = inv.job_balance(obj)
        material = job_material_check(obj)
        for row in material:
            b = balance.get(row["article"].pk, {})
            row["out"] = b.get("out", Decimal("0"))
            row["returned"] = b.get("returned", Decimal("0"))
            row["consumed"] = b.get("consumed", Decimal("0"))
            row["open"] = b.get("open", Decimal("0"))
            if row["article"].is_serial:
                row["out"] = Decimal(Unit.objects.filter(current_job=obj, article=row["article"]).count()) + \
                    b.get("returned", Decimal("0"))
                row["open"] = Decimal(Unit.objects.filter(current_job=obj, article=row["article"]).count())
        from planning.availability import employee_status

        assignments = list(obj.assignments.select_related("employee", "qualification"))
        for a in assignments:
            a.issues = employee_status(a.employee, a.start, a.end, exclude_assignment=a)
        net = sum((p.net_total for p in positions), Decimal("0"))
        tax = sum((p.net_total * p.tax_rate / 100 for p in positions), Decimal("0")).quantize(Decimal("0.01"))
        times = obj.time_entries.select_related("employee")
        hours = sum((t.hours for t in times), Decimal("0"))
        cost = sum((t.cost for t in times), Decimal("0"))
        return {
            "positions": positions, "net": net, "tax": tax, "gross": net + tax,
            "material": material, "shortages": [m for m in material if m["shortage"] > 0],
            "units_out": obj.units_out.select_related("article"),
            "assignments": assignments,
            "tasks": obj.tasks.select_related("assignee"),
            "appointments": obj.appointments.all(),
            "documents": obj.documents.select_related("customer"),
            "time_entries": times, "hours": hours, "labour_cost": cost,
            "statuses": JobStatus.objects.all(),
            "advance_form": AdvanceForm(initial={"percent": 30}),
        }


class TaskCrud(Crud):
    model = Task
    form_class = TaskForm
    namespace = "projects"
    name = "task"
    list_display = ["title", ("Fällig", "due_date"), "priority", ("Zuständig", "assignee"), ("Job", "job"),
                    ("Projekt", "project"), ("Erledigt", "done")]
    search_fields = ["title", "description"]
    list_filters = ["done", "assignee", "priority",
                    ("mine", "Ansicht", [("1", "Meine Aufgaben")], lambda qs, v: qs)]
    has_detail = False

    @classmethod
    def get_queryset(cls, request):
        qs = Task.objects.select_related("assignee", "job", "project")
        if request.GET.get("mine") == "1":
            qs = qs.filter(assignee=request.user)
        return qs


class AppointmentCrud(Crud):
    model = Appointment
    form_class = AppointmentForm
    namespace = "projects"
    name = "appointment"
    list_display = ["title", "start", "end", ("Job", "job"), ("Projekt", "project"), "location"]
    search_fields = ["title", "location", "description"]
    has_detail = False
    ordering = ["-start"]


class StatusCrud(Crud):
    model = JobStatus
    form_class = JobStatusForm
    namespace = "projects"
    name = "status"
    list_display = [("Status", lambda s: color_badge(s.name, s.color)), "order", "reserves_inventory", "is_closed",
                    "is_default"]
    has_detail = False


# -- Positionen -----------------------------------------------------------

def article_options():
    return Article.objects.filter(active=True).select_related("tax_rate").order_by("name")


def tax_rates():
    return TaxRate.objects.filter(active=True)


@login_required
@permission_required("projects.change_job", raise_exception=True)
def job_positions(request, pk):
    job = get_object_or_404(Job, pk=pk)
    formset = JobPositionFormSet(request.POST or None, instance=job, prefix="pos")
    if request.method == "POST":
        if formset.is_valid():
            formset.save()
            messages.success(request, "Positionen gespeichert.")
            if "continue" in request.POST:
                return redirect("projects:job_positions", pk=job.pk)
            return redirect(job.get_absolute_url())
        messages.error(request, "Bitte die markierten Positionen prüfen.")
    return render(request, "projects/job_positions.html", {
        "job": job, "formset": formset, "title": f"Positionen – {job}", "articles": article_options(),
        "default_factor": job.calc_days, "default_tax": TaxRate.default_rate(),
        "back_url": job.get_absolute_url(),
    })


@login_required
@permission_required("projects.change_job", raise_exception=True)
def job_status(request, pk):
    job = get_object_or_404(Job, pk=pk)
    form = StatusForm(request.POST)
    if form.is_valid():
        job.status = form.cleaned_data["status"]
        job.save()
        messages.success(request, f"Status auf „{job.status}“ gesetzt.")
    return redirect(job.get_absolute_url())


@login_required
@permission_required("projects.add_job", raise_exception=True)
def job_duplicate(request, pk):
    job = get_object_or_404(Job, pk=pk)
    if request.method != "POST":
        return redirect(job.get_absolute_url())
    as_template = request.POST.get("template") == "1"
    new = services.duplicate_job(job, as_template=as_template)
    messages.success(request, "Als Vorlage gespeichert." if as_template else "Job dupliziert.")
    return redirect(reverse("projects:job_update", args=[new.pk]))


@login_required
@permission_required("projects.add_job", raise_exception=True)
def job_from_template(request):
    form = FromTemplateForm(request.POST or None, initial={"template": request.GET.get("template")})
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        job = services.duplicate_job(d["template"], as_template=False, title=d["title"] or d["template"].title,
                                     start=d["start"])
        if d["customer"]:
            job.customer = d["customer"]
        if d["start"] and not job.start:
            job.start = d["start"]
        job.save()
        messages.success(request, "Job aus Vorlage erstellt.")
        return redirect(reverse("projects:job_update", args=[job.pk]))
    return render(request, "inventory/action_form.html", {"form": form, "title": "Job aus Vorlage", "icon": "copy"})


@login_required
@permission_required("projects.add_project", raise_exception=True)
def project_duplicate(request, pk):
    project = get_object_or_404(Project, pk=pk)
    if request.method != "POST":
        return redirect(project.get_absolute_url())
    as_template = request.POST.get("template") == "1"
    new = services.duplicate_project(project, as_template=as_template)
    messages.success(request, "Projekt als Vorlage gespeichert." if as_template else "Projekt erstellt.")
    return redirect(new.get_absolute_url())


@login_required
@permission_required("projects.change_job", raise_exception=True)
def job_staff_positions(request, pk):
    job = get_object_or_404(Job, pk=pk)
    if request.method == "POST":
        n = services.add_staff_positions(job, request.POST.get("source", "assignments"))
        messages.success(request, f"{n} Personalposition(en) übernommen.") if n else messages.info(
            request, "Keine passenden Einsätze bzw. Zeiten gefunden.")
    return redirect(job.get_absolute_url() + "#tab-positionen")


@login_required
@permission_required("projects.change_task", raise_exception=True)
def task_toggle(request, pk):
    task = get_object_or_404(Task, pk=pk)
    if request.method == "POST":
        task.done = not task.done
        task.save()
    nxt = request.POST.get("next", "")
    return redirect(nxt if nxt.startswith("/") else reverse("projects:task_list"))


# -- Packliste & Scan-Ausgabe ---------------------------------------------

def packlist_rows(job):
    rows = []
    balance = inv.job_balance(job)
    for row in job_material_check(job):
        article = row["article"]
        b = balance.get(article.pk, {})
        units = list(Unit.objects.filter(current_job=job, article=article)) if article.is_serial else []
        out = Decimal(len(units)) if article.is_serial else b.get("open", Decimal("0"))
        locations = [s for s in article.stock.select_related("location") if s.usable > 0] if not article.is_serial \
            else []
        rows.append({**row, "units": units, "out_open": out, "done": out >= row["required"],
                     "returned": b.get("returned", Decimal("0")), "locations": locations,
                     "group": article.group.name if article.group else "Ohne Gruppe"})
    rows.sort(key=lambda r: (r["group"], r["article"].name))
    return rows


@login_required
@permission_required("projects.view_job", raise_exception=True)
def packlist(request, pk):
    job = get_object_or_404(Job, pk=pk)
    return render(request, "projects/packlist.html", {"job": job, "rows": packlist_rows(job),
                                                      "title": f"Packliste {job.number}"})


@login_required
@permission_required("inventory.add_movement", raise_exception=True)
def job_scan(request, pk):
    job = get_object_or_404(Job, pk=pk)
    mode = request.POST.get("mode") or request.GET.get("mode") or "out"
    form = ScanForm(request.POST or None, initial={"mode": mode})
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        code = d["code"].strip()
        unit = article = None
        if code:
            kind, obj = inv.resolve_code(code)
            if kind == "unit":
                unit = obj
            elif kind == "article":
                article = obj
            else:
                messages.error(request, f"Code „{code}“ nicht gefunden.")
        elif d["article"]:
            article = d["article"]
        if unit or article:
            try:
                with transaction.atomic():
                    if d["mode"] == "out":
                        inv.checkout(job, unit=unit, article=article, quantity=d["quantity"], location=d["location"],
                                     user=request.user)
                        label = "ausgegeben"
                    else:
                        inv.checkin(job, unit=unit, article=article, quantity=d["quantity"], location=d["location"],
                                    defective=d["defective"], user=request.user)
                        label = "zurückgenommen"
                what = str(unit) if unit else f"{fmt(d['quantity'])} × {article.name}"
                messages.success(request, f"{what} {label}.")
            except inv.InventoryError as e:
                messages.error(request, str(e))
        return redirect(reverse("projects:job_scan", args=[job.pk]) + f"?mode={d['mode']}")
    return render(request, "projects/job_scan.html", {
        "job": job, "form": form, "mode": mode, "rows": packlist_rows(job),
        "recent": job.movements.select_related("article", "unit", "user")[:15],
        "title": f"Materialausgabe {job.number}",
    })


@login_required
@permission_required("inventory.add_movement", raise_exception=True)
def job_consume(request, pk):
    """Offenes Verbrauchsmaterial eines Jobs als verbraucht verbuchen."""
    job = get_object_or_404(Job, pk=pk)
    if request.method == "POST":
        article = get_object_or_404(Article, pk=request.POST.get("article"))
        try:
            inv.consume(job, article, Decimal(request.POST.get("quantity", "0").replace(",", ".")), request.user)
            messages.success(request, f"Verbrauch von „{article.name}“ gebucht.")
        except (inv.InventoryError, ArithmeticError) as e:
            messages.error(request, str(e))
    return redirect(reverse("projects:job_scan", args=[job.pk]) + "?mode=return")
