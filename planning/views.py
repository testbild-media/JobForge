import calendar
import datetime

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone

from projects.models import Appointment, Job, Task
from staff.models import Assignment, Availability

from .availability import material_conflicts, staff_conflicts

MONTHS = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober",
          "November", "Dezember"]
LAYERS = [("jobs", "Jobs"), ("appointments", "Termine"), ("assignments", "Personaleinsätze"),
          ("absences", "Abwesenheiten"), ("tasks", "Aufgaben")]


def _aware(d, end=False):
    return timezone.make_aware(datetime.datetime.combine(d, datetime.time.max if end else datetime.time.min))


def collect_events(user, first, last, layers):
    start, end = _aware(first), _aware(last, end=True)
    events = []
    if "jobs" in layers and user.has_perm("projects.view_job"):
        jobs = Job.objects.filter(is_template=False, start__lte=end).filter(end__gte=start).select_related(
            "status", "customer")
        for j in jobs:
            events.append({
                "start": timezone.localtime(j.start), "end": timezone.localtime(j.end or j.start),
                "title": f"{j.number} {j.title}", "color": j.status.color if j.status else "#64748b",
                "url": j.get_absolute_url(), "kind": "job",
                "sub": j.customer.name if j.customer else j.venue,
            })
    if "appointments" in layers and user.has_perm("projects.view_appointment"):
        for a in Appointment.objects.filter(start__lte=end).select_related("job"):
            a_end = a.end_or_start
            if a_end < start:
                continue
            events.append({"start": timezone.localtime(a.start), "end": timezone.localtime(a_end), "title": a.title,
                           "color": a.color, "kind": "appointment", "all_day": a.all_day,
                           "url": reverse("projects:appointment_update", args=[a.pk]), "sub": a.location})
    if "assignments" in layers and user.has_perm("staff.view_assignment"):
        for a in Assignment.objects.filter(start__lte=end, end__gte=start).exclude(status="declined").select_related(
                "employee", "job"):
            events.append({"start": timezone.localtime(a.start), "end": timezone.localtime(a.end),
                           "title": f"{a.employee}: {a.job.title}", "color": a.employee.color, "kind": "assignment",
                           "url": a.job.get_absolute_url() + "#tab-personal", "sub": a.role})
    if "absences" in layers and user.has_perm("staff.view_availability"):
        for ab in Availability.objects.filter(start__lte=last, end__gte=first).select_related("employee"):
            events.append({"start": _aware(ab.start), "end": _aware(ab.end, True), "all_day": True,
                           "title": f"{ab.employee}: {ab.get_kind_display()}", "color": ab.color,
                           "kind": "absence", "url": reverse("staff:availability_update", args=[ab.pk])})
    if "tasks" in layers and user.has_perm("projects.view_task"):
        for t in Task.objects.filter(due_date__range=(first, last), done=False):
            events.append({"start": _aware(t.due_date), "end": _aware(t.due_date), "all_day": True,
                           "title": f"☐ {t.title}", "color": "#f59e0b", "kind": "task",
                           "url": reverse("projects:task_update", args=[t.pk])})
    return events


@login_required
def calendar_view(request):
    today = timezone.localdate()
    try:
        year = int(request.GET.get("y", today.year))
        month = int(request.GET.get("m", today.month))
        datetime.date(year, month, 1)
    except ValueError:
        year, month = today.year, today.month
    layers = request.GET.getlist("l") or ["jobs", "appointments", "absences", "tasks"]
    weeks = calendar.Calendar(firstweekday=0).monthdatescalendar(year, month)
    first, last = weeks[0][0], weeks[-1][-1]
    events = collect_events(request.user, first, last, layers)
    grid = []
    for week in weeks:
        row = []
        for day in week:
            day_events = [e for e in events if e["start"].date() <= day <= e["end"].date()]
            day_events.sort(key=lambda e: (e["kind"] != "job", e["start"]))
            row.append({"date": day, "events": day_events, "in_month": day.month == month, "today": day == today})
        grid.append(row)
    prev_m = (datetime.date(year, month, 1) - datetime.timedelta(days=1))
    next_m = (datetime.date(year, month, 28) + datetime.timedelta(days=7)).replace(day=1)
    upcoming = sorted([e for e in events if e["end"].date() >= today], key=lambda e: e["start"])[:40]
    return render(request, "planning/calendar.html", {
        "grid": grid, "year": year, "month": month, "month_name": MONTHS[month - 1], "prev": prev_m, "next": next_m,
        "layers": LAYERS, "active_layers": layers, "upcoming": upcoming, "title": "Kalender",
        "weekdays": ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"],
    })


@login_required
def conflicts(request):
    today = timezone.localdate()
    try:
        start = datetime.date.fromisoformat(request.GET.get("start", ""))
    except ValueError:
        start = today
    try:
        end = datetime.date.fromisoformat(request.GET.get("end", ""))
    except ValueError:
        end = start + datetime.timedelta(days=60)
    material = material_conflicts(start, end) if request.user.has_perm("inventory.view_article") else []
    staff = staff_conflicts(start, end) if request.user.has_perm("staff.view_assignment") else []
    return render(request, "planning/conflicts.html", {"material": material, "staff": staff, "start": start,
                                                       "end": end, "title": "Konflikte & Doppelbuchungen"})


def _ics_escape(text):
    return str(text).replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


@login_required
def ics_export(request):
    """iCalendar-Export der kommenden 6 Monate (für Kalender-Apps)."""
    today = timezone.localdate()
    events = collect_events(request.user, today - datetime.timedelta(days=30), today + datetime.timedelta(days=183),
                            ["jobs", "appointments", "assignments", "absences"])
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//JobForge//DE", "CALSCALE:GREGORIAN"]
    stamp = timezone.now().strftime("%Y%m%dT%H%M%SZ")
    for i, e in enumerate(events):
        lines += ["BEGIN:VEVENT", f"UID:jobforge-{e['kind']}-{i}-{e['start']:%Y%m%d%H%M}@jobforge", f"DTSTAMP:{stamp}"]
        if e.get("all_day"):
            lines += [f"DTSTART;VALUE=DATE:{e['start']:%Y%m%d}",
                      f"DTEND;VALUE=DATE:{(e['end'].date() + datetime.timedelta(days=1)):%Y%m%d}"]
        else:
            s = e["start"].astimezone(datetime.timezone.utc)
            en = e["end"].astimezone(datetime.timezone.utc)
            lines += [f"DTSTART:{s:%Y%m%dT%H%M%SZ}", f"DTEND:{en:%Y%m%dT%H%M%SZ}"]
        lines += [f"SUMMARY:{_ics_escape(e['title'])}", f"URL:{request.build_absolute_uri(e['url'])}",
                  "END:VEVENT"]
    lines.append("END:VCALENDAR")
    resp = HttpResponse("\r\n".join(lines) + "\r\n", content_type="text/calendar; charset=utf-8")
    resp["Content-Disposition"] = 'attachment; filename="jobforge.ics"'
    return resp
