"""Vorlagen, Duplizieren und Personalübernahme für Projekte und Jobs."""
from decimal import Decimal

from django.db import transaction

from .models import Job, JobPosition, Project, Task

JOB_COPY_FIELDS = ["title", "customer", "contact_person", "manager", "warehouse", "venue", "venue_address",
                   "rental_days", "description", "internal_notes", "custom_data"]
POS_FIELDS = ["order", "kind", "article", "description", "quantity", "unit", "unit_price", "factor", "discount",
              "tax_rate"]


@transaction.atomic
def duplicate_job(job, as_template=False, project=None, title=None, start=None):
    new = Job(**{f: getattr(job, f) for f in JOB_COPY_FIELDS})
    new.is_template = as_template
    new.project = project if project is not None else (None if as_template else job.project)
    if title:
        new.title = title
    if job.start and start:
        delta = start - job.start
        for f in ("prep_start", "start", "end", "return_end"):
            value = getattr(job, f)
            setattr(new, f, value + delta if value else None)
    elif not as_template and not job.is_template:
        for f in ("prep_start", "start", "end", "return_end"):
            setattr(new, f, getattr(job, f))
    new.status = None
    new.save()
    JobPosition.objects.bulk_create([JobPosition(job=new, **{f: getattr(p, f) for f in POS_FIELDS})
                                     for p in job.positions.all()])
    Task.objects.bulk_create([Task(job=new, title=t.title, description=t.description, priority=t.priority)
                              for t in job.tasks.all()])
    return new


@transaction.atomic
def duplicate_project(project, as_template=False, name=None):
    new = Project.objects.create(
        name=name or project.name, customer=project.customer, manager=project.manager,
        description=project.description, budget=project.budget, is_template=as_template,
        custom_data=project.custom_data,
    )
    for job in project.jobs.all():
        duplicate_job(job, as_template=as_template, project=new)
    Task.objects.bulk_create([Task(project=new, title=t.title, description=t.description, priority=t.priority)
                              for t in project.tasks.filter(job__isnull=True)])
    return new


@transaction.atomic
def add_staff_positions(job, source="assignments"):
    """Übernimmt geplantes Personal oder erfasste Zeiten als Positionen in den Job."""
    from core.models import TaxRate

    rate = TaxRate.default_rate()
    order = (job.positions.order_by("-order").values_list("order", flat=True).first() or 0) + 10
    created = 0
    if source == "assignments":
        for a in job.assignments.exclude(status="declined").select_related("employee"):
            if a.rate_type == "daily":
                qty, unit = Decimal("1"), "Tag"
            elif a.rate_type == "flat":
                qty, unit = Decimal("1"), "pauschal"
            else:
                qty, unit = a.hours, "Std"
            JobPosition.objects.create(
                job=job, order=order, kind="staff", unit=unit, quantity=qty, unit_price=a.effective_rate,
                description=f"{a.role or 'Personal'}: {a.employee}", tax_rate=rate,
            )
            order += 10
            created += 1
    else:
        entries = job.time_entries.filter(billable=True, billed=False).select_related("employee")
        by_emp = {}
        for e in entries:
            by_emp.setdefault(e.employee, []).append(e)
        for emp, items in by_emp.items():
            hours = sum((e.hours for e in items), Decimal("0"))
            JobPosition.objects.create(
                job=job, order=order, kind="staff", unit="Std", quantity=hours,
                unit_price=emp.hourly_rate or Decimal("0"), description=f"Arbeitszeit: {emp}", tax_rate=rate,
            )
            order += 10
            created += 1
            for e in items:
                e.billed = True
                e.save(update_fields=["billed"])
    return created
