"""Grunddaten, die bei jeder Migration idempotent angelegt werden."""
from decimal import Decimal

from django.contrib.auth.models import Group, Permission

ROLE_DEFINITIONS = {
    # Rolle: {app_label: [Aktionen] oder "*"}
    "Administrator": "*",
    "Büro": {
        "contacts": "*",
        "projects": "*",
        "billing": "*",
        "staff": "*",
        "inventory": ["view"],
        "core": ["view_note", "add_note", "view_attachment", "add_attachment", "change_note",
                 "view_auditlog", "view_taxrate", "view_paymentterm"],
    },
    "Projektleitung": {
        "contacts": ["view", "add", "change"],
        "projects": "*",
        "billing": ["view", "add", "change"],
        "inventory": ["view", "add_movement", "view_movement"],
        "staff": ["view", "add_assignment", "change_assignment", "delete_assignment",
                  "add_timeentry", "change_timeentry", "view_all_timeentries", "approve_timeentry"],
        "core": ["view_note", "add_note", "view_attachment", "add_attachment"],
    },
    "Lager": {
        "inventory": "*",
        "projects": ["view"],
        "contacts": ["view"],
        "core": ["view_note", "add_note", "view_attachment", "add_attachment"],
        "staff": ["add_timeentry", "change_timeentry", "view_timeentry"],
    },
    "Mitarbeiter": {
        "projects": ["view_project", "view_job", "view_task", "change_task", "view_appointment", "view_jobposition"],
        "inventory": ["view_article", "view_unit", "view_location", "add_movement"],
        "staff": ["view_employee", "add_timeentry", "change_timeentry", "view_timeentry", "view_assignment"],
        "core": ["view_note", "add_note", "view_attachment"],
    },
}

JOB_STATUSES = [
    # name, farbe, reserviert Material, abgeschlossen, standard
    ("Anfrage", "#94a3b8", False, False, True),
    ("Angebot", "#60a5fa", True, False, False),
    ("Bestätigt", "#16a34a", True, False, False),
    ("In Vorbereitung", "#f59e0b", True, False, False),
    ("Läuft", "#e8590c", True, False, False),
    ("Abgeschlossen", "#64748b", False, True, False),
    ("Abgerechnet", "#6366f1", False, True, False),
    ("Storniert", "#ef4444", False, True, False),
]


def setup_roles():
    for role, spec in ROLE_DEFINITIONS.items():
        group, _ = Group.objects.get_or_create(name=role)
        if spec == "*":
            perms = Permission.objects.filter(
                content_type__app_label__in=[
                    "core", "contacts", "inventory", "projects", "billing", "staff", "planning", "auth", "authtoken"
                ]
            )
        else:
            perms = Permission.objects.none()
            for app_label, actions in spec.items():
                qs = Permission.objects.filter(content_type__app_label=app_label)
                if actions == "*":
                    perms = perms | qs
                    continue
                for action in actions:
                    if "_" in action:
                        perms = perms | qs.filter(codename=action)
                    else:
                        perms = perms | qs.filter(codename__startswith=f"{action}_")
        group.permissions.add(*perms.distinct())


def ensure_defaults(verbosity=1):
    from core.models import DEFAULT_SEQUENCES, CompanySettings, NumberSequence, PaymentTerm, TaxRate

    CompanySettings.get()
    for key, (pattern, reset) in DEFAULT_SEQUENCES.items():
        NumberSequence.objects.get_or_create(key=key, defaults={"pattern": pattern, "yearly_reset": reset})
    if not TaxRate.objects.exists():
        TaxRate.objects.create(name="Regelsteuersatz", rate=Decimal("19.00"), is_default=True)
        TaxRate.objects.create(name="Ermäßigt", rate=Decimal("7.00"))
        TaxRate.objects.create(name="Steuerfrei", rate=Decimal("0.00"))
    if not PaymentTerm.objects.exists():
        PaymentTerm.objects.create(name="14 Tage netto", days=14, is_default=True)
        PaymentTerm.objects.create(name="Sofort", days=0, text="Zahlbar sofort ohne Abzug.")
        PaymentTerm.objects.create(
            name="30 Tage, 2 % Skonto 10 Tage", days=30, discount_days=10, discount_percent=Decimal("2"),
            text="Zahlbar innerhalb von {discount_days} Tagen mit {discount_percent} % Skonto "
                 "oder innerhalb von {days} Tagen ohne Abzug bis zum {due_date}.",
        )

    from projects.models import JobStatus

    if not JobStatus.objects.exists():
        for i, (name, color, reserves, closed, default) in enumerate(JOB_STATUSES):
            JobStatus.objects.create(
                name=name, color=color, order=i * 10, reserves_inventory=reserves, is_closed=closed, is_default=default
            )

    from billing.models import DocumentLayout

    if not DocumentLayout.objects.exists():
        DocumentLayout.objects.create(name="Standard", is_default=True)

    setup_roles()
    if verbosity:
        print("  JobForge: Grunddaten und Rollen geprüft.")
