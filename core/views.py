import datetime
import mimetypes
from decimal import Decimal
from pathlib import Path

from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required, user_passes_test
from django.contrib.auth.models import Group, User
from django.contrib.auth.views import redirect_to_login
from django.contrib.contenttypes.models import ContentType
from django.db.models import Q
from django.http import FileResponse, Http404, HttpResponse, HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.utils import timezone
from django.views.decorators.cache import cache_control

from .crud import Crud
from .forms import CompanySettingsForm, ImportForm, JFModelForm, UserForm
from .models import (Attachment, AuditLog, CompanySettings, CustomFieldDefinition, Note, NumberSequence, PaymentTerm,
                     TaxRate, Webhook)

superuser_required = user_passes_test(lambda u: u.is_superuser)


@login_required
def dashboard(request):
    from billing.models import Document
    from inventory.models import Article, Stock, Unit
    from planning.availability import material_conflicts, staff_conflicts
    from projects.models import Job, Task
    from staff.models import Assignment

    now = timezone.now()
    week = now + datetime.timedelta(days=7)
    user = request.user
    ctx = {"title": "Übersicht",
           "needs_url": user.has_perm("core.change_companysettings") and not CompanySettings.get().public_url}
    if user.has_perm("projects.view_job"):
        ctx["jobs_running"] = Job.objects.filter(is_template=False, start__lte=now, end__gte=now).select_related(
            "status", "customer")
        ctx["jobs_upcoming"] = Job.objects.filter(is_template=False, start__gt=now, start__lte=now + datetime.timedelta(
            days=14)).exclude(status__is_closed=True).select_related("status", "customer").order_by("start")[:12]
        ctx["tasks"] = Task.objects.filter(done=False).filter(Q(assignee=user) | Q(assignee__isnull=True)).order_by(
            "due_date")[:10]
    if user.has_perm("billing.view_document"):
        open_docs = list(Document.objects.filter(
            doc_type__in=["invoice", "partial", "advance", "final"], status__in=["final", "sent", "partially_paid"]
        ).prefetch_related("positions", "payments"))
        ctx["open_total"] = sum((d.open_amount for d in open_docs), Decimal("0"))
        ctx["overdue"] = [d for d in open_docs if d.is_overdue]
        ctx["overdue_total"] = sum((d.open_amount for d in ctx["overdue"]), Decimal("0"))
        ctx["open_quotes"] = Document.objects.filter(doc_type="quote", status__in=["final", "sent"]).count()
        ctx["drafts"] = Document.objects.filter(status="draft").count()
        month_start = timezone.localdate().replace(day=1)
        month_docs = Document.objects.filter(doc_type__in=["invoice", "partial", "advance", "final"],
                                             finalized_at__isnull=False, date__gte=month_start).exclude(
            status="cancelled").prefetch_related("positions")
        ctx["month_revenue"] = sum((d.totals()["net_total"] for d in month_docs), Decimal("0"))
    if user.has_perm("inventory.view_article"):
        ctx["material_conflicts"] = material_conflicts(now, now + datetime.timedelta(days=30))
        ctx["defects"] = Unit.objects.exclude(condition__in=["ok", "retired", "lost"]).count() + \
            Stock.objects.filter(defective__gt=0).count()
        ctx["units_out"] = Unit.objects.filter(current_job__isnull=False).count()
        ctx["low_stock"] = [a for a in Article.objects.filter(kind="consumable", active=True, min_stock__gt=0)
                            if a.usable_quantity() < a.min_stock][:8]
    if user.has_perm("staff.view_assignment"):
        ctx["staff_conflicts"] = staff_conflicts(now, now + datetime.timedelta(days=30))
        ctx["assignments_today"] = Assignment.objects.filter(
            start__date__lte=timezone.localdate(), end__date__gte=timezone.localdate()
        ).exclude(status="declined").select_related("employee", "job")
    emp = getattr(user, "employee", None)
    if emp:
        ctx["my_assignments"] = emp.assignments.filter(end__gte=now, start__lte=week).select_related("job")
    if user.has_perm("core.view_auditlog"):
        ctx["activity"] = AuditLog.objects.select_related("user")[:12]
    return render(request, "core/dashboard.html", ctx)


@login_required
def search(request):
    from billing.models import Document
    from contacts.models import Contact
    from inventory.models import Article, Location, Unit
    from inventory.services import resolve_code
    from projects.models import Job, Project
    from staff.models import Employee

    q = request.GET.get("q", "").strip()
    results = []
    if q:
        kind, obj = resolve_code(q)
        if obj is not None and request.GET.get("exact") != "0":
            return redirect(obj.get_absolute_url())
        user = request.user
        specs = [
            ("contacts.view_contact", "Kontakte", Contact.objects.filter(
                Q(number__icontains=q) | Q(company_name__icontains=q) | Q(last_name__icontains=q) |
                Q(first_name__icontains=q) | Q(email__icontains=q) | Q(city__icontains=q))),
            ("projects.view_job", "Jobs", Job.objects.filter(is_template=False).filter(
                Q(number__icontains=q) | Q(title__icontains=q) | Q(venue__icontains=q))),
            ("projects.view_project", "Projekte", Project.objects.filter(Q(number__icontains=q) | Q(name__icontains=q))),
            ("billing.view_document", "Dokumente", Document.objects.filter(
                Q(number__icontains=q) | Q(subject__icontains=q))),
            ("inventory.view_article", "Artikel", Article.objects.filter(
                Q(number__icontains=q) | Q(name__icontains=q) | Q(barcode__icontains=q) |
                Q(manufacturer__icontains=q))),
            ("inventory.view_unit", "Geräte", Unit.objects.select_related("article").filter(
                Q(code__icontains=q) | Q(serial_number__icontains=q))),
            ("inventory.view_location", "Lagerorte", Location.objects.filter(Q(name__icontains=q) | Q(code__icontains=q))),
            ("staff.view_employee", "Personal", Employee.objects.filter(
                Q(first_name__icontains=q) | Q(last_name__icontains=q) | Q(email__icontains=q))),
        ]
        for perm, label, qs in specs:
            if user.has_perm(perm):
                items = list(qs[:15])
                if items:
                    results.append((label, items))
    return render(request, "core/search.html", {"q": q, "results": results, "title": "Suche"})


# -- Notizen & Dateien ------------------------------------------------------

def _target(ct_id, obj_id):
    ct = get_object_or_404(ContentType, pk=ct_id)
    try:
        return ct, ct.get_object_for_this_type(pk=obj_id)
    except ct.model_class().DoesNotExist:
        raise Http404


def _back(request, fallback="/"):
    nxt = request.POST.get("next", "")
    return HttpResponseRedirect(nxt if nxt.startswith("/") else fallback)


@login_required
@permission_required("core.add_note", raise_exception=True)
def note_add(request, ct_id, obj_id):
    ct, obj = _target(ct_id, obj_id)
    text = request.POST.get("text", "").strip()
    if request.method == "POST" and text:
        Note.objects.create(content_type=ct, object_id=obj.pk, text=text, author=request.user)
        messages.success(request, "Notiz gespeichert.")
    return _back(request, obj.get_absolute_url())


@login_required
def note_delete(request, pk):
    note = get_object_or_404(Note, pk=pk)
    if request.method == "POST" and (note.author_id == request.user.pk or request.user.has_perm("core.delete_note")):
        note.delete()
        messages.success(request, "Notiz gelöscht.")
    return _back(request)


@login_required
@permission_required("core.add_attachment", raise_exception=True)
def attachment_add(request, ct_id, obj_id):
    ct, obj = _target(ct_id, obj_id)
    if request.method == "POST":
        files = request.FILES.getlist("file")
        for f in files:
            Attachment.objects.create(content_type=ct, object_id=obj.pk, file=f,
                                      name=request.POST.get("name", "").strip() or f.name, uploaded_by=request.user)
        if files:
            messages.success(request, f"{len(files)} Datei(en) hochgeladen.")
    return _back(request, obj.get_absolute_url())


@login_required
def attachment_delete(request, pk):
    att = get_object_or_404(Attachment, pk=pk)
    if request.method == "POST" and (att.uploaded_by_id == request.user.pk or
                                     request.user.has_perm("core.delete_attachment")):
        att.file.delete(save=False)
        att.delete()
        messages.success(request, "Datei gelöscht.")
    return _back(request)


def media(request, path):
    """Geschützte Auslieferung hochgeladener Dateien (Branding ist öffentlich)."""
    if not path.startswith("branding/") and not request.user.is_authenticated:
        return redirect_to_login(request.get_full_path())
    full = (Path(settings.MEDIA_ROOT) / path).resolve()
    if not str(full).startswith(str(Path(settings.MEDIA_ROOT).resolve())) or not full.is_file():
        raise Http404
    if path.startswith("attachments/") and not request.user.has_perm("core.view_attachment"):
        raise Http404
    resp = FileResponse(open(full, "rb"), content_type=mimetypes.guess_type(str(full))[0] or "application/octet-stream")
    if request.GET.get("download"):
        resp["Content-Disposition"] = f'attachment; filename="{full.name}"'
    return resp


# -- Einstellungen ----------------------------------------------------------

@login_required
def settings_index(request):
    return render(request, "core/settings_index.html", {"title": "Einstellungen"})


@login_required
@permission_required("core.change_companysettings", raise_exception=True)
def company_settings(request):
    obj = CompanySettings.get()
    form = CompanySettingsForm(request.POST or None, request.FILES or None, instance=obj)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Firmeneinstellungen gespeichert.")
        return redirect("core:company")
    return render(request, "core/crud/form.html", {"form": form, "title": "Firma & Branding",
                                                   "cancel_url": "/einstellungen/", "formsets": []})


class SequenceCrud(Crud):
    model = NumberSequence
    namespace = "core"
    name = "sequence"
    fields = ["key", "pattern", "next_value", "yearly_reset"]
    list_display = ["key", "pattern", ("Nächste Nummer", "preview"), "yearly_reset"]
    has_detail = False
    help_text = "Platzhalter: {YYYY} Jahr, {YY} Jahr kurz, {MM} Monat, {DD} Tag, {NNNN} laufende Nummer (Anzahl N = Stellen)."


class TaxRateCrud(Crud):
    model = TaxRate
    namespace = "core"
    name = "taxrate"
    fields = ["name", "rate", "is_default", "active"]
    list_display = ["name", "rate", "is_default", "active"]
    has_detail = False

    @classmethod
    def after_save(cls, request, obj, created):
        if obj.is_default:
            TaxRate.objects.exclude(pk=obj.pk).update(is_default=False)


class PaymentTermCrud(Crud):
    model = PaymentTerm
    namespace = "core"
    name = "paymentterm"
    fields = ["name", "days", "discount_days", "discount_percent", "text", "is_default"]
    list_display = ["name", "days", "discount_days", "discount_percent", "is_default"]
    has_detail = False

    @classmethod
    def after_save(cls, request, obj, created):
        if obj.is_default:
            PaymentTerm.objects.exclude(pk=obj.pk).update(is_default=False)


class CustomFieldCrud(Crud):
    model = CustomFieldDefinition
    namespace = "core"
    name = "customfield"
    fields = ["target", "label", "key", "field_type", "choices", "required", "show_in_list", "order", "active"]
    list_display = ["target", "label", "key", "field_type", "required", "active"]
    list_filters = ["target"]
    has_detail = False


class WebhookForm(JFModelForm):
    class Meta:
        model = Webhook
        fields = ["name", "url", "events", "secret", "active"]


class WebhookCrud(Crud):
    model = Webhook
    form_class = WebhookForm
    namespace = "core"
    name = "webhook"
    list_display = ["name", "url", "events", "active"]
    detail_template = "core/webhook_detail.html"

    @classmethod
    def extra_context(cls, request, obj=None):
        return {"deliveries": obj.deliveries.all()[:50]} if obj else {}


@login_required
@permission_required("core.change_webhook", raise_exception=True)
def webhook_test(request, pk):
    from .webhooks import send_test

    hook = get_object_or_404(Webhook, pk=pk)
    if request.method == "POST":
        send_test(hook)
        last = hook.deliveries.first()
        if last and last.success:
            messages.success(request, f"Test erfolgreich (HTTP {last.status_code}).")
        else:
            messages.error(request, f"Test fehlgeschlagen: {last.response[:200] if last else 'keine Antwort'}")
    return redirect("core:webhook_detail", pk=pk)


def role_names(u):
    names = [g.name for g in u.groups.all()]
    if u.is_superuser:
        names.insert(0, "Superuser")
    return ", ".join(names) or "–"


class UserCrud(Crud):
    model = User
    form_class = UserForm
    namespace = "core"
    name = "user"
    list_display = ["username", ("Name", lambda u: u.get_full_name() or "–"), "email", ("Rollen", role_names),
                    ("Aktiv", "is_active"), ("Letzte Anmeldung", "last_login")]
    search_fields = ["username", "first_name", "last_name", "email"]
    list_filters = ["is_active", ("rolle", "Rolle", lambda: [(g.pk, g.name) for g in Group.objects.all()],
                                  lambda qs, v: qs.filter(groups__pk=v))]
    has_detail = False
    ordering = ["username"]

    @classmethod
    def get_queryset(cls, request):
        return User.objects.prefetch_related("groups").order_by("username")


class GroupForm(JFModelForm):
    class Meta:
        model = Group
        fields = ["name", "permissions"]
        widgets = {"permissions": forms.SelectMultiple(attrs={"size": 25})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["permissions"].queryset = self.fields["permissions"].queryset.filter(
            content_type__app_label__in=["core", "contacts", "inventory", "projects", "billing", "staff", "auth"]
        ).select_related("content_type")
        self.fields["permissions"].label_from_instance = lambda p: (
            f"{p.content_type.model_class()._meta.verbose_name_plural if p.content_type.model_class() else p.content_type}"
            f" – {p.name}")
        self.fields["permissions"].help_text = "Strg/Cmd gedrückt halten für Mehrfachauswahl."


class GroupCrud(Crud):
    model = Group
    form_class = GroupForm
    namespace = "core"
    name = "group"
    list_display = ["name", ("Benutzer", lambda g: g.user_set.count()), ("Rechte", lambda g: g.permissions.count())]
    has_detail = False
    ordering = ["name"]


class AuditCrud(Crud):
    model = AuditLog
    namespace = "core"
    name = "audit"
    list_display = ["timestamp", ("Benutzer", "user"), "action",
                    ("Bereich", lambda a: a.content_type.model_class()._meta.verbose_name
                     if a.content_type and a.content_type.model_class() else "–"),
                    ("Objekt", "object_repr"), ("Details", lambda a: a.message or _changes_text(a))]
    search_fields = ["object_repr", "message", "user__username"]
    list_filters = ["action", "user"]
    detail_template = "core/audit_detail.html"
    paginate_by = 100

    @classmethod
    def get_queryset(cls, request):
        return AuditLog.objects.select_related("user", "content_type")


def _changes_text(entry):
    if not entry.changes:
        return ""
    keys = list(entry.changes.keys())
    text = ", ".join(keys[:4])
    return text + (f" (+{len(keys) - 4})" if len(keys) > 4 else "")


# -- API-Token ----------------------------------------------------------

@login_required
def api_access(request):
    from rest_framework.authtoken.models import Token

    token = Token.objects.filter(user=request.user).first()
    if request.method == "POST":
        if token:
            token.delete()
        token = None
        if request.POST.get("action") == "create":
            token = Token.objects.create(user=request.user)
            messages.success(request, "Neuer API-Token wurde erzeugt.")
        else:
            messages.success(request, "API-Token wurde widerrufen.")
        return redirect("core:api_access")
    return render(request, "core/api_access.html", {"token": token, "title": "API-Zugang",
                                                    "api_base": request.build_absolute_uri("/api/v1/")})


# -- Import / Export ----------------------------------------------------

@login_required
def import_export(request):
    from .io import EXPORTS, run_import

    form = ImportForm(request.POST or None, request.FILES or None)
    report = None
    if request.method == "POST":
        if not request.user.has_perm("inventory.add_article") and not request.user.has_perm("contacts.add_contact"):
            raise Http404
        if form.is_valid():
            report = run_import(form.cleaned_data["target"], form.cleaned_data["file"],
                                form.cleaned_data["update_existing"], request.user)
            if report["errors"]:
                messages.warning(request, f"Import mit {len(report['errors'])} Fehler(n) abgeschlossen.")
            else:
                messages.success(request, f"Import abgeschlossen: {report['created']} neu, {report['updated']} aktualisiert.")
    return render(request, "core/import_export.html", {"form": form, "report": report, "exports": EXPORTS,
                                                       "title": "Import & Export"})


@login_required
def export(request, key):
    from .io import EXPORTS, export_csv

    if key not in EXPORTS or not request.user.has_perm(EXPORTS[key]["perm"]):
        raise Http404
    return export_csv(key)


@login_required
@superuser_required
def backup(request):
    """Vollständige Datensicherung als JSON (ohne Dateien)."""
    import io

    from django.core.management import call_command

    buf = io.StringIO()
    call_command("dumpdata", "--natural-foreign", "--natural-primary", "-e", "contenttypes", "-e",
                 "auth.permission", "-e", "sessions", "-e", "admin.logentry", indent=1, stdout=buf)
    resp = HttpResponse(buf.getvalue(), content_type="application/json")
    resp["Content-Disposition"] = f'attachment; filename="jobforge-backup-{timezone.now():%Y%m%d-%H%M}.json"'
    return resp


# -- PWA ------------------------------------------------------------------

@cache_control(max_age=3600)
def manifest(request):
    company = CompanySettings.get()
    data = {
        "name": f"JobForge – {company.name}",
        "short_name": "JobForge",
        "description": "Forge your workflow – Aufträge, Lager, Personal und Rechnungen",
        "start_url": "/?source=pwa",
        "scope": "/",
        "display": "standalone",
        "background_color": "#ffffff",
        "theme_color": company.primary_color,
        "lang": "de",
        "icons": [
            {"src": "/static/icons/icon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "/static/icons/icon-512.png", "sizes": "512x512", "type": "image/png"},
            {"src": "/static/icons/icon-maskable-512.png", "sizes": "512x512", "type": "image/png",
             "purpose": "maskable"},
        ],
        "shortcuts": [
            {"name": "Scanner", "url": "/lager/scanner/"},
            {"name": "Kalender", "url": "/planung/kalender/"},
            {"name": "Zeiterfassung", "url": "/personal/zeiten/"},
        ],
    }
    return JsonResponse(data, content_type="application/manifest+json")


def service_worker(request):
    js = render_to_string("core/sw.js", {"version": settings.VERSION})
    resp = HttpResponse(js, content_type="application/javascript")
    resp["Service-Worker-Allowed"] = "/"
    resp["Cache-Control"] = "no-cache"
    return resp


def offline(request):
    return render(request, "core/offline.html", {"title": "Offline"})


def health(request):
    return JsonResponse({"status": "ok", "version": settings.VERSION})
