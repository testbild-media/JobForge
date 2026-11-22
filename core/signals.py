"""Änderungsprotokoll und Webhook-Auslösung über Django-Signale."""
import datetime
import decimal

from django.apps import apps
from django.contrib.contenttypes.models import ContentType
from django.db.models.fields.files import FieldFile
from django.db.models.signals import post_delete, post_save, pre_save

from .middleware import get_current_user

AUDITED_MODELS = [
    "core.CompanySettings", "core.NumberSequence", "core.TaxRate", "core.PaymentTerm", "core.Webhook",
    "contacts.Contact", "contacts.ContactPerson", "contacts.Address",
    "inventory.Location", "inventory.Article", "inventory.Unit", "inventory.Category",
    "projects.Project", "projects.Job", "projects.JobStatus", "projects.Task", "projects.Appointment",
    "billing.Document", "billing.Payment", "billing.DocumentLayout",
    "staff.Employee", "staff.Assignment", "staff.TimeEntry", "staff.Availability",
    "auth.User", "auth.Group",
]

WEBHOOK_MODELS = {
    "contacts.Contact": "contact",
    "inventory.Article": "article",
    "inventory.Unit": "unit",
    "inventory.Movement": "movement",
    "projects.Project": "project",
    "projects.Job": "job",
    "billing.Document": "document",
    "billing.Payment": "payment",
    "staff.Employee": "employee",
    "staff.TimeEntry": "timeentry",
    "staff.Assignment": "assignment",
}

SKIP_FIELDS = {"updated", "last_login", "password", "custom_data_cache"}


def _plain(value):
    if value is None:
        return None
    if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
        return value.isoformat()
    if isinstance(value, decimal.Decimal):
        return str(value.normalize()) if value == value.to_integral() else str(value)
    if isinstance(value, FieldFile):
        return value.name or ""
    return str(value) if not isinstance(value, (int, float, bool, str, list, dict)) else value


def _snapshot(instance):
    data = {}
    for field in instance._meta.concrete_fields:
        if field.name in SKIP_FIELDS:
            continue
        data[field.verbose_name if isinstance(field.verbose_name, str) else field.name] = _plain(
            getattr(instance, field.attname)
        )
    return data


def _pre_save(sender, instance, raw=False, **kwargs):
    if raw or not instance.pk:
        instance._audit_old = None
        return
    try:
        old = sender.objects.get(pk=instance.pk)
        instance._audit_old = _snapshot(old)
    except sender.DoesNotExist:
        instance._audit_old = None


def _post_save(sender, instance, created, raw=False, **kwargs):
    if raw:
        return
    from .models import AuditLog

    changes = {}
    if not created:
        old = getattr(instance, "_audit_old", None) or {}
        new = _snapshot(instance)
        changes = {k: [old.get(k), v] for k, v in new.items() if old.get(k) != v}
        if not changes:
            return
    AuditLog.objects.create(
        user=get_current_user(),
        action="create" if created else "update",
        content_type=ContentType.objects.get_for_model(sender),
        object_id=str(instance.pk),
        object_repr=str(instance)[:255],
        changes=changes,
    )


def _post_delete(sender, instance, **kwargs):
    from .models import AuditLog

    AuditLog.objects.create(
        user=get_current_user(),
        action="delete",
        content_type=ContentType.objects.get_for_model(sender),
        object_id=str(instance.pk),
        object_repr=str(instance)[:255],
    )


def _webhook_save(sender, instance, created, raw=False, **kwargs):
    if raw:
        return
    from .webhooks import trigger

    trigger(f"{WEBHOOK_MODELS[sender._meta.label]}.{'created' if created else 'updated'}", instance)


def _webhook_delete(sender, instance, **kwargs):
    from .webhooks import trigger

    trigger(f"{WEBHOOK_MODELS[sender._meta.label]}.deleted", instance, deleted=True)


def connect_all():
    for label in AUDITED_MODELS:
        model = apps.get_model(label)
        uid = f"audit-{label}"
        pre_save.connect(_pre_save, sender=model, dispatch_uid=uid + "-pre")
        post_save.connect(_post_save, sender=model, dispatch_uid=uid + "-post")
        post_delete.connect(_post_delete, sender=model, dispatch_uid=uid + "-del")
    for label in WEBHOOK_MODELS:
        model = apps.get_model(label)
        post_save.connect(_webhook_save, sender=model, dispatch_uid=f"wh-{label}-save")
        post_delete.connect(_webhook_delete, sender=model, dispatch_uid=f"wh-{label}-del")
