import datetime
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from core.crud import Crud, color_badge
from planning.availability import employee_status

from .forms import AssignmentForm, AvailabilityForm, EmployeeForm, TimeEntryForm
from .models import Assignment, Availability, Employee, Qualification, TimeEntry


class EmployeeCrud(Crud):
    model = Employee
    form_class = EmployeeForm
    namespace = "staff"
    name = "employee"
    list_display = ["number", ("Name", str), "kind", "position", "phone", "email",
                    ("Qualifikationen", lambda e: ", ".join(q.name for q in e.qualifications.all()) or "–"),
                    "active"]
    search_fields = ["first_name", "last_name", "email", "position", "qualifications__name", "number"]
    list_filters = ["kind", "qualifications", "active"]
    detail_template = "staff/employee_detail.html"
    show_notes = True
    show_attachments = True

    @classmethod
    def get_queryset(cls, request):
        return Employee.objects.prefetch_related("qualifications")

    @classmethod
    def extra_context(cls, request, obj=None):
        if obj is None:
            return {}
        today = timezone.localdate()
        month_start = today.replace(day=1)
        month_entries = obj.time_entries.filter(date__gte=month_start)
        return {
            "upcoming": obj.assignments.filter(end__gte=timezone.now()).select_related("job")[:30],
            "past": obj.assignments.filter(end__lt=timezone.now()).select_related("job").order_by("-start")[:15],
            "availabilities": obj.availabilities.filter(end__gte=today - datetime.timedelta(days=60))[:30],
            "entries": obj.time_entries.select_related("job")[:20],
            "month_hours": sum((e.hours for e in month_entries), Decimal("0")),
        }


class QualificationCrud(Crud):
    model = Qualification
    namespace = "staff"
    name = "qualification"
    fields = ["name", "description"]
    list_display = ["name", "description"]
    has_detail = False


class AvailabilityCrud(Crud):
    model = Availability
    form_class = AvailabilityForm
    namespace = "staff"
    name = "availability"
    list_display = [("Person", "employee"), ("Art", lambda a: color_badge(a.get_kind_display(), a.color)), "start",
                    "end", "note", "approved"]
    search_fields = ["employee__first_name", "employee__last_name", "note"]
    list_filters = ["kind", "employee", "approved"]
    has_detail = False

    @classmethod
    def get_queryset(cls, request):
        return Availability.objects.select_related("employee")


class AssignmentCrud(Crud):
    model = Assignment
    form_class = AssignmentForm
    namespace = "staff"
    name = "assignment"
    list_display = ["start", "end", ("Person", "employee"), ("Job", "job"), "role",
                    ("Status", lambda a: color_badge(a.get_status_display(), a.status_color))]
    search_fields = ["employee__first_name", "employee__last_name", "job__title", "job__number", "role"]
    list_filters = ["status", "employee",
                    ("zeit", "Zeitraum", [("upcoming", "Kommende"), ("past", "Vergangene")],
                     lambda qs, v: qs.filter(end__gte=timezone.now()) if v == "upcoming"
                     else qs.filter(end__lt=timezone.now()))]
    has_detail = False
    ordering = ["-start"]

    @classmethod
    def get_queryset(cls, request):
        return Assignment.objects.select_related("employee", "job")

    @classmethod
    def after_save(cls, request, obj, created):
        issues = employee_status(obj.employee, obj.start, obj.end, exclude_assignment=obj)
        for issue in issues:
            messages.warning(request, f"Konflikt für {obj.employee}: {issue}")

    @classmethod
    def success_url(cls, obj):
        return obj.job.get_absolute_url() + "#tab-personal"


def _can_all(user):
    return user.has_perm("staff.view_all_timeentries")


class TimeEntryCrud(Crud):
    model = TimeEntry
    namespace = "staff"
    name = "timeentry"
    list_display = ["date", ("Person", "employee"), ("Job", "job"), "start_time", "end_time", "break_minutes",
                    ("Stunden", "hours"), "activity", "billable", "approved"]
    search_fields = ["activity", "employee__last_name", "job__number", "job__title"]
    list_filters = ["employee", "approved", "billable", "billed",
                    ("monat", "Monat", lambda: _month_choices(),
                     lambda qs, v: qs.filter(date__year=int(v[:4]), date__month=int(v[5:7])))]
    list_template = "staff/timeentry_list.html"
    has_detail = False

    @classmethod
    def get_queryset(cls, request):
        qs = TimeEntry.objects.select_related("employee", "job")
        if not _can_all(request.user):
            qs = qs.filter(employee__user=request.user)
        return qs

    @classmethod
    def get_form_class(cls, request, obj=None):
        return type("BoundTimeEntryForm", (TimeEntryForm,), {"user": request.user, "can_all": _can_all(request.user)})

    @classmethod
    def after_save(cls, request, obj, created):
        if created:
            obj.created_by = request.user
            obj.save(update_fields=["created_by"])

    @classmethod
    def extra_context(cls, request, obj=None):
        if obj is not None:
            return {}
        qs = cls.filter_queryset(request, cls.get_queryset(request))
        emp = getattr(request.user, "employee", None)
        running = TimeEntry.objects.filter(employee=emp, end_time__isnull=True, manual_hours__isnull=True,
                                           start_time__isnull=False).first() if emp else None
        from projects.models import Job

        return {
            "sum_hours": sum((e.hours for e in qs[:2000]), Decimal("0")),
            "my_employee": emp, "running": running,
            "timer_jobs": Job.objects.filter(is_template=False, status__is_closed=False).order_by("-start")[:100],
            "can_approve": request.user.has_perm("staff.approve_timeentry"),
        }


def _month_choices():
    today = timezone.localdate().replace(day=1)
    out = []
    for i in range(12):
        y, m = today.year, today.month - i
        while m <= 0:
            m += 12
            y -= 1
        out.append((f"{y:04d}-{m:02d}", f"{m:02d}/{y}"))
    return out


@login_required
@permission_required("staff.add_timeentry", raise_exception=True)
def timer(request):
    """Stempeluhr: Start/Stopp für die angemeldete Person."""
    emp = getattr(request.user, "employee", None)
    if emp is None:
        messages.error(request, "Ihr Benutzerkonto ist keiner Person im Personalstamm zugeordnet.")
        return redirect("staff:timeentry_list")
    if request.method == "POST":
        now = timezone.localtime()
        running = TimeEntry.objects.filter(employee=emp, end_time__isnull=True, manual_hours__isnull=True,
                                           start_time__isnull=False).first()
        if running:
            running.end_time = now.time().replace(second=0, microsecond=0)
            if running.date != now.date():  # über Mitternacht
                running.end_time = datetime.time(23, 59)
            running.break_minutes = int(request.POST.get("break_minutes") or running.break_minutes or 0)
            running.save()
            messages.success(request, f"Zeit gestoppt: {running.hours:g} Std.")
        else:
            from projects.models import Job

            job = Job.objects.filter(pk=request.POST.get("job") or 0).first()
            TimeEntry.objects.create(employee=emp, job=job, date=now.date(),
                                     start_time=now.time().replace(second=0, microsecond=0),
                                     activity=request.POST.get("activity", "")[:200], created_by=request.user)
            messages.success(request, "Zeiterfassung gestartet.")
    nxt = request.POST.get("next", "")
    return redirect(nxt if nxt.startswith("/") else "staff:timeentry_list")


@login_required
@permission_required("staff.approve_timeentry", raise_exception=True)
def approve_entries(request):
    if request.method == "POST":
        ids = [i for i in request.POST.getlist("ids") if i.isdigit()]
        n = TimeEntry.objects.filter(pk__in=ids).update(approved=True)
        messages.success(request, f"{n} Zeiteinträge freigegeben.")
    nxt = request.POST.get("next", "")
    return redirect(nxt if nxt.startswith("/") else "staff:timeentry_list")


@login_required
@permission_required("staff.view_assignment", raise_exception=True)
def planner(request):
    """Wochenplan: Personen × Tage mit Einsätzen und Abwesenheiten."""
    try:
        start = datetime.date.fromisoformat(request.GET.get("start", ""))
    except ValueError:
        start = timezone.localdate()
    start = start - datetime.timedelta(days=start.weekday())
    days = [start + datetime.timedelta(days=i) for i in range(7)]
    tz_start = timezone.make_aware(datetime.datetime.combine(days[0], datetime.time.min))
    tz_end = timezone.make_aware(datetime.datetime.combine(days[-1], datetime.time.max))
    employees = list(Employee.objects.filter(active=True))
    q = request.GET.get("q", "").strip()
    if q:
        employees = [e for e in employees if q.lower() in str(e).lower() or q.lower() in e.position.lower()]
    assignments = Assignment.objects.filter(start__lt=tz_end, end__gt=tz_start).select_related("job", "employee")
    absences = Availability.objects.filter(start__lte=days[-1], end__gte=days[0])
    grid = {e.pk: {d: {"assignments": [], "absences": []} for d in days} for e in employees}
    for a in assignments:
        if a.employee_id not in grid:
            continue
        s, e = timezone.localtime(a.start).date(), timezone.localtime(a.end).date()
        for d in days:
            if s <= d <= e:
                grid[a.employee_id][d]["assignments"].append(a)
    for ab in absences:
        if ab.employee_id not in grid:
            continue
        for d in days:
            if ab.start <= d <= ab.end:
                grid[ab.employee_id][d]["absences"].append(ab)
    rows = [{"employee": e, "cells": [(d, grid[e.pk][d]) for d in days]} for e in employees]
    from projects.models import Job

    jobs = Job.objects.filter(is_template=False, start__lt=tz_end, end__gt=tz_start).select_related("status")
    unstaffed = [j for j in jobs if not j.assignments.exclude(status="declined").exists()]
    return render(request, "staff/planner.html", {
        "days": days, "rows": rows, "prev": days[0] - datetime.timedelta(days=7),
        "next": days[0] + datetime.timedelta(days=7), "today": timezone.localdate(), "jobs": jobs,
        "unstaffed": unstaffed, "title": "Personalplanung", "q": q,
    })


@login_required
def my_assignments(request):
    emp = getattr(request.user, "employee", None)
    items = Assignment.objects.filter(employee=emp, end__gte=timezone.now()).select_related("job") if emp else []
    return render(request, "staff/my_assignments.html", {"items": items, "employee": emp,
                                                         "title": "Meine Einsätze"})


@login_required
def assignment_status(request, pk):
    """Status ändern – durch Disposition oder die eingeplante Person selbst (Zu-/Absage)."""
    a = get_object_or_404(Assignment.objects.select_related("employee"), pk=pk)
    own = a.employee.user_id == request.user.pk
    if not (request.user.has_perm("staff.change_assignment") or own):
        raise PermissionDenied
    status = request.POST.get("status")
    if own and not request.user.has_perm("staff.change_assignment") and status not in ("confirmed", "declined"):
        raise PermissionDenied
    if request.method == "POST" and status in dict(Assignment.STATUSES):
        a.status = status
        a.save()
        messages.success(request, f"Einsatz von {a.employee}: {a.get_status_display()}")
    nxt = request.POST.get("next", "")
    return redirect(nxt if nxt.startswith("/") else a.job.get_absolute_url())


@login_required
@permission_required("staff.view_employee", raise_exception=True)
def free_staff(request):
    """Freie Personen für einen Zeitraum (optional mit Qualifikation)."""
    from planning.availability import free_employees

    result, start, end = [], request.GET.get("start"), request.GET.get("end")
    qual = Qualification.objects.filter(pk=request.GET.get("qualification") or 0).first()
    if start and end:
        try:
            s = datetime.datetime.fromisoformat(start)
            e = datetime.datetime.fromisoformat(end)
            result = free_employees(s, e, qual)
        except ValueError:
            messages.error(request, "Ungültiger Zeitraum.")
    return render(request, "staff/free_staff.html", {
        "result": result, "start": start or "", "end": end or "", "qualifications": Qualification.objects.all(),
        "qualification": qual, "title": "Personal-Verfügbarkeit",
        "job": request.GET.get("job", ""),
    })
