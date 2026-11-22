"""
Verfügbarkeitsprüfung und Konflikterkennung für Material und Personal.

Ein Job blockiert Material im Zeitraum [Vorbereitung ab | Beginn, Rückgabe bis | Ende],
sofern sein Status „Reserviert Material“ gesetzt hat. Für die Auslastung wird die
maximale gleichzeitige Belegung (Peak) per Sweep-Line berechnet – zwei Jobs, die sich
nicht überschneiden, addieren sich also nicht.
"""
import datetime
from decimal import Decimal

from django.db.models.functions import Coalesce
from django.utils import timezone

from inventory.models import Article
from projects.models import Job, JobPosition, expand_article

ZERO = Decimal("0")


def as_datetime(value, end=False):
    if isinstance(value, datetime.datetime):
        return value if timezone.is_aware(value) else timezone.make_aware(value)
    if isinstance(value, datetime.date):
        t = datetime.time.max if end else datetime.time.min
        return timezone.make_aware(datetime.datetime.combine(value, t))
    return value


def reserving_jobs(start, end, exclude_job=None):
    qs = (
        Job.objects.filter(is_template=False, status__reserves_inventory=True)
        .annotate(ps=Coalesce("prep_start", "start"), pe=Coalesce("return_end", "end"))
        .filter(ps__lt=end, pe__gt=start)
    )
    if exclude_job is not None:
        qs = qs.exclude(pk=exclude_job.pk)
    return qs


def bookings(start, end, exclude_job=None, article_ids=None):
    """{article_id: [(beginn, ende, menge, job), …]} für alle reservierenden Jobs im Zeitraum."""
    jobs = {j.pk: j for j in reserving_jobs(start, end, exclude_job)}
    if not jobs:
        return {}
    positions = JobPosition.objects.filter(
        job_id__in=jobs.keys(), kind__in=["rental", "sale"], article__isnull=False
    ).select_related("article")
    out = {}
    for pos in positions:
        job = jobs[pos.job_id]
        for article, qty in expand_article(pos.article, pos.quantity):
            if article_ids is not None and article.pk not in article_ids:
                continue
            out.setdefault(article.pk, []).append((job.ps, job.pe, qty, job))
    return out


def peak(intervals, start, end):
    events = []
    for s, e, q, _job in intervals:
        s, e = max(s, start), min(e, end)
        if s < e:
            events.append((s, 1, q))
            events.append((e, 0, -q))  # Enden vor Beginnen bei gleichem Zeitpunkt
    events.sort(key=lambda x: (x[0], x[1]))
    current = best = ZERO
    for _t, _o, q in events:
        current += q
        best = max(best, current)
    return best


def article_availability(article, start, end, exclude_job=None, site=None):
    start, end = as_datetime(start), as_datetime(end, end=True)
    loc_ids = site.descendant_ids() if site else None
    if article.kind == "set":
        comps = list(article.components.select_related("component"))
        results = [article_availability(c.component, start, end, exclude_job, site) for c in comps]
        avail = min(
            ((r["available"] / c.quantity).to_integral_value(rounding="ROUND_FLOOR") for r, c in zip(results, comps)
             if c.quantity > 0), default=ZERO,
        )
        cap = article.usable_quantity(loc_ids)
        return {"article": article, "capacity": cap, "booked": cap - avail, "available": avail, "jobs": [],
                "components": list(zip(comps, results))}
    capacity = article.usable_quantity(loc_ids)
    intervals = bookings(start, end, exclude_job, {article.pk}).get(article.pk, [])
    booked = peak(intervals, start, end)
    jobs = sorted({iv[3] for iv in intervals}, key=lambda j: j.ps)
    return {
        "article": article,
        "capacity": capacity,
        "total": article.total_quantity(loc_ids),
        "booked": booked,
        "available": capacity - booked,
        "jobs": jobs,
        "out_now": article.units.filter(current_job__isnull=False).count() if article.kind == "serial" else None,
    }


def job_material_check(job):
    """Prüft für jeden benötigten Artikel des Jobs, ob genug Material frei ist."""
    rows = []
    req = job.material_requirements()
    if not req:
        return rows
    start, end = job.period_start, job.period_end
    if not start or not end:
        for article, qty in req.items():
            rows.append({"article": article, "required": qty, "capacity": article.usable_quantity(), "other": None,
                         "available": None, "shortage": ZERO, "undated": True})
        return rows
    other = bookings(start, end, exclude_job=job, article_ids={a.pk for a in req})
    for article, qty in sorted(req.items(), key=lambda x: x[0].name):
        capacity = article.usable_quantity()
        other_peak = peak(other.get(article.pk, []), start, end)
        free = capacity - other_peak
        rows.append({
            "article": article, "required": qty, "capacity": capacity, "other": other_peak, "available": free,
            "shortage": max(qty - free, ZERO), "undated": False,
            "conflict_jobs": sorted({iv[3] for iv in other.get(article.pk, [])}, key=lambda j: j.ps),
        })
    return rows


def material_conflicts(start, end):
    start, end = as_datetime(start), as_datetime(end, end=True)
    data = bookings(start, end)
    articles = Article.objects.in_bulk(list(data.keys()))
    conflicts = []
    for aid, intervals in data.items():
        article = articles[aid]
        capacity = article.usable_quantity()
        booked = peak(intervals, start, end)
        if booked > capacity:
            conflicts.append({
                "article": article, "capacity": capacity, "booked": booked, "missing": booked - capacity,
                "jobs": sorted({iv[3] for iv in intervals}, key=lambda j: j.ps),
            })
    return sorted(conflicts, key=lambda c: -c["missing"])


def staff_conflicts(start, end):
    from staff.models import Assignment, Availability

    start, end = as_datetime(start), as_datetime(end, end=True)
    assignments = list(
        Assignment.objects.filter(start__lt=end, end__gt=start).exclude(status="declined")
        .select_related("employee", "job").order_by("employee_id", "start")
    )
    conflicts = []
    by_emp = {}
    for a in assignments:
        by_emp.setdefault(a.employee_id, []).append(a)
    for emp_assignments in by_emp.values():
        for i, a in enumerate(emp_assignments):
            for b in emp_assignments[i + 1:]:
                if b.start < a.end and a.start < b.end:
                    conflicts.append({"type": "double", "employee": a.employee, "a": a, "b": b,
                                      "text": "Doppelbuchung"})
    if assignments:
        absences = Availability.objects.exclude(kind="available").filter(
            employee_id__in=by_emp.keys(), start__lte=end.date(), end__gte=start.date()
        ).select_related("employee")
        for ab in absences:
            for a in by_emp.get(ab.employee_id, []):
                a_start, a_end = timezone.localtime(a.start).date(), timezone.localtime(a.end).date()
                if ab.start <= a_end and ab.end >= a_start:
                    conflicts.append({"type": "absence", "employee": a.employee, "a": a, "absence": ab,
                                      "text": f"Eingeplant trotz {ab.get_kind_display()}"})
    return conflicts


def employee_status(employee, start, end, exclude_assignment=None):
    """Gibt eine Liste von Gründen zurück, warum die Person im Zeitraum nicht frei ist."""
    from staff.models import Assignment, Availability

    start, end = as_datetime(start), as_datetime(end, end=True)
    reasons = []
    qs = Assignment.objects.filter(employee=employee, start__lt=end, end__gt=start).exclude(status="declined")
    if exclude_assignment is not None and exclude_assignment.pk:
        qs = qs.exclude(pk=exclude_assignment.pk)
    for a in qs.select_related("job"):
        reasons.append(f"bereits eingeplant: {a.job} ({timezone.localtime(a.start):%d.%m. %H:%M}–"
                       f"{timezone.localtime(a.end):%H:%M})")
    for ab in Availability.objects.filter(employee=employee, start__lte=timezone.localtime(end).date(),
                                          end__gte=timezone.localtime(start).date()).exclude(kind="available"):
        reasons.append(f"{ab.get_kind_display()} {ab.start:%d.%m.}–{ab.end:%d.%m.%Y}")
    return reasons


def free_employees(start, end, qualification=None):
    from staff.models import Employee

    qs = Employee.objects.filter(active=True)
    if qualification is not None:
        qs = qs.filter(qualifications=qualification)
    out = []
    for emp in qs:
        reasons = employee_status(emp, start, end)
        out.append((emp, reasons))
    return out


def upcoming_window(days=30):
    now = timezone.now()
    return now, now + datetime.timedelta(days=days)
