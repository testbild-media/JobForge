"""
Generisches CRUD-Gerüst: Eine Konfigurationsklasse erzeugt Liste, Detail, Anlegen,
Bearbeiten und Löschen inkl. Suche, Filter, Berechtigungen und Inline-Formularen.
"""
import datetime
import decimal

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import FieldDoesNotExist
from django.db import models, transaction
from django.db.models import ProtectedError, Q
from django.forms import modelform_factory
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import NoReverseMatch, path, reverse
from django.utils import formats, timezone
from django.utils.html import format_html
from django.views import View

from .forms import JFModelForm
from .models import Attachment, AuditLog, Note


def fmt(value):
    """Formatiert Werte für Tabellen und Detailansichten."""
    if value is None or value == "":
        return "–"
    if isinstance(value, bool):
        return "✓" if value else "–"
    if isinstance(value, datetime.datetime):
        return formats.date_format(timezone.localtime(value) if timezone.is_aware(value) else value, "d.m.Y H:i")
    if isinstance(value, datetime.date):
        return formats.date_format(value, "d.m.Y")
    if isinstance(value, decimal.Decimal):
        return formats.number_format(value.normalize() if value == value.to_integral() else value, use_l10n=True,
                                     force_grouping=True)
    if isinstance(value, models.Model):
        return str(value)
    return value


def resolve(obj, accessor):
    if callable(accessor):
        return accessor(obj)
    value = obj
    for part in accessor.split("__"):
        if value is None:
            return None
        display = getattr(value, f"get_{part}_display", None)
        value = display() if display else getattr(value, part, None)
        if callable(value) and not isinstance(value, models.Manager):
            value = value()
    return value


def color_badge(text, color):
    return format_html('<span class="badge" style="--badge:{}">{}</span>', color or "#64748b", text)


class Crud:
    model = None
    form_class = None
    fields = "__all__"
    exclude = None
    namespace = ""
    name = ""
    list_display = []
    search_fields = []
    list_filters = []
    ordering = None
    paginate_by = 50
    has_detail = True
    detail_template = "core/crud/detail.html"
    list_template = "core/crud/list.html"
    form_template = "core/crud/form.html"
    detail_exclude = ("id", "custom_data")
    inlines = []  # Liste von (FormSet-Klasse, Titel)
    show_notes = False
    show_attachments = False
    list_actions = []  # [(Label, URL-Name, Icon, Berechtigung)]
    help_text = ""

    # -- Hilfsfunktionen -------------------------------------------------
    @classmethod
    def opts(cls):
        return cls.model._meta

    @classmethod
    def title(cls):
        return cls.opts().verbose_name

    @classmethod
    def title_plural(cls):
        return cls.opts().verbose_name_plural

    @classmethod
    def perm(cls, action):
        o = cls.opts()
        return f"{o.app_label}.{action}_{o.model_name}"

    @classmethod
    def url(cls, action, *args):
        return reverse(f"{cls.namespace}:{cls.name}_{action}", args=args)

    @classmethod
    def get_queryset(cls, request):
        qs = cls.model._default_manager.all()
        if cls.ordering:
            qs = qs.order_by(*cls.ordering)
        return qs

    @classmethod
    def get_form_class(cls, request, obj=None):
        if cls.form_class:
            return cls.form_class
        return modelform_factory(cls.model, form=JFModelForm, fields=cls.fields, exclude=cls.exclude)

    @classmethod
    def get_initial(cls, request):
        initial = {}
        for key, value in request.GET.items():
            try:
                cls.model._meta.get_field(key)
                initial[key] = value
            except FieldDoesNotExist:
                pass
        return initial

    @classmethod
    def columns(cls):
        cols = []
        for item in cls.list_display:
            if isinstance(item, (tuple, list)):
                cols.append((item[0], item[1]))
            else:
                try:
                    label = cls.model._meta.get_field(item).verbose_name
                except FieldDoesNotExist:
                    label = item
                cols.append((label, item))
        return cols

    @classmethod
    def filter_specs(cls, request):
        specs = []
        for name in cls.list_filters:
            if isinstance(name, (tuple, list)):
                key, label, choices = name[0], name[1], name[2]
                specs.append({"key": key, "label": label, "choices": choices() if callable(choices) else choices,
                              "value": request.GET.get(key, "")})
                continue
            field = cls.model._meta.get_field(name)
            if field.choices:
                choices = list(field.choices)
            elif isinstance(field, models.BooleanField):
                choices = [("1", "Ja"), ("0", "Nein")]
            elif field.is_relation:
                choices = [(o.pk, str(o)) for o in field.related_model._default_manager.all()[:300]]
            else:
                continue
            specs.append({"key": name, "label": field.verbose_name, "choices": choices,
                          "value": request.GET.get(name, "")})
        return specs

    @classmethod
    def filter_queryset(cls, request, qs):
        q = request.GET.get("q", "").strip()
        if q and cls.search_fields:
            cond = Q()
            for term in q.split():
                part = Q()
                for f in cls.search_fields:
                    part |= Q(**{f"{f}__icontains": term})
                cond &= part
            qs = qs.filter(cond)
        for name in cls.list_filters:
            if isinstance(name, (tuple, list)):
                value = request.GET.get(name[0], "")
                if value and len(name) > 3:
                    qs = name[3](qs, value)
                continue
            value = request.GET.get(name, "")
            if value == "":
                continue
            field = cls.model._meta.get_field(name)
            if isinstance(field, models.BooleanField):
                qs = qs.filter(**{name: value == "1"})
            else:
                qs = qs.filter(**{name: value})
        return qs.distinct() if q else qs

    @classmethod
    def detail_fields(cls, obj):
        out = []
        for field in cls.model._meta.concrete_fields:
            if field.name in cls.detail_exclude:
                continue
            value = resolve(obj, field.name)
            if isinstance(field, models.FileField) and value:
                value = format_html('<a href="{}">{}</a>', value.url, value.name.rsplit("/", 1)[-1])
            out.append((field.verbose_name, fmt(value)))
        for field in cls.model._meta.many_to_many:
            out.append((field.verbose_name, ", ".join(str(x) for x in getattr(obj, field.name).all()) or "–"))
        if hasattr(obj, "custom_field_values"):
            out.extend(obj.custom_field_values())
        return out

    @classmethod
    def extra_context(cls, request, obj=None):
        return {}

    @classmethod
    def after_save(cls, request, obj, created):
        pass

    @classmethod
    def success_url(cls, obj):
        if cls.has_detail:
            return cls.url("detail", obj.pk)
        return cls.url("list")

    @classmethod
    def urls(cls):
        name = cls.name
        patterns = [
            path("", CrudList.as_view(crud=cls), name=f"{name}_list"),
            path("neu/", CrudCreate.as_view(crud=cls), name=f"{name}_create"),
            path("<int:pk>/bearbeiten/", CrudUpdate.as_view(crud=cls), name=f"{name}_update"),
            path("<int:pk>/loeschen/", CrudDelete.as_view(crud=cls), name=f"{name}_delete"),
        ]
        if cls.has_detail:
            detail_view = getattr(cls, "detail_view", None) or CrudDetail
            patterns.append(path("<int:pk>/", detail_view.as_view(crud=cls), name=f"{name}_detail"))
        return patterns


class CrudMixin(LoginRequiredMixin, PermissionRequiredMixin):
    crud = None
    action = "view"

    def get_permission_required(self):
        return [self.crud.perm(self.action)]

    def base_context(self, **kwargs):
        crud = self.crud
        ctx = {
            "crud": crud,
            "opts": crud.opts(),
            "title": crud.title_plural(),
            "can_add": self.request.user.has_perm(crud.perm("add")),
            "can_change": self.request.user.has_perm(crud.perm("change")),
            "can_delete": self.request.user.has_perm(crud.perm("delete")),
            "list_url": crud.url("list"),
            "create_url": crud.url("create"),
        }
        ctx.update(kwargs)
        return ctx

    def get_object(self):
        return get_object_or_404(self.crud.get_queryset(self.request), pk=self.kwargs["pk"])


class CrudList(CrudMixin, View):
    def get(self, request):
        from django.core.paginator import Paginator

        crud = self.crud
        qs = crud.filter_queryset(request, crud.get_queryset(request))
        page = Paginator(qs, crud.paginate_by).get_page(request.GET.get("page"))
        cols = crud.columns()
        rows = []
        for obj in page:
            cells = [fmt(resolve(obj, acc)) for _, acc in cols]
            if crud.has_detail:
                link = crud.url("detail", obj.pk)
            elif request.user.has_perm(crud.perm("change")):
                link = crud.url("update", obj.pk)
            else:
                link = None
            rows.append({"obj": obj, "cells": cells, "link": link})
        query = request.GET.copy()
        query.pop("page", None)
        ctx = self.base_context(
            page=page, rows=rows, columns=[c[0] for c in cols], filters=crud.filter_specs(request),
            q=request.GET.get("q", ""), querystring=query.urlencode(), total=page.paginator.count,
            list_actions=[a for a in crud.list_actions if not a[3] or request.user.has_perm(a[3])],
        )
        ctx.update(crud.extra_context(request))
        return render(request, crud.list_template, ctx)


class CrudDetail(CrudMixin, View):
    def get(self, request, pk):
        crud = self.crud
        obj = self.get_object()
        ctx = self.base_context(
            object=obj, title=str(obj), fields=crud.detail_fields(obj),
            update_url=crud.url("update", obj.pk), delete_url=crud.url("delete", obj.pk),
            history=object_history(obj),
        )
        if crud.show_notes or crud.show_attachments:
            ctx.update(notes_context(request, obj))
        ctx.update(crud.extra_context(request, obj))
        return render(request, crud.detail_template, ctx)


class CrudFormView(CrudMixin, View):
    def get_instance(self):
        return None

    def build(self, request, instance):
        crud = self.crud
        form_class = crud.get_form_class(request, instance)
        kwargs = {"instance": instance}
        if instance is None:
            kwargs["initial"] = crud.get_initial(request)
        if request.method == "POST":
            kwargs.update(data=request.POST, files=request.FILES)
        form = form_class(**kwargs)
        formsets = []
        for formset_class, title in crud.inlines:
            fs_kwargs = {"instance": instance or crud.model(), "prefix": formset_class.model._meta.model_name}
            if request.method == "POST":
                fs_kwargs.update(data=request.POST, files=request.FILES)
            formsets.append((formset_class(**fs_kwargs), title))
        return form, formsets

    def render_form(self, request, form, formsets, instance):
        ctx = self.base_context(
            form=form, formsets=formsets, object=instance,
            title=f"{self.crud.title()} bearbeiten" if instance else f"{self.crud.title()} anlegen",
            cancel_url=(self.crud.url("detail", instance.pk) if instance and self.crud.has_detail else self.crud.url("list")),
        )
        ctx.update(self.crud.extra_context(request, instance))
        return render(request, self.crud.form_template, ctx)

    def get(self, request, pk=None):
        instance = self.get_instance()
        form, formsets = self.build(request, instance)
        return self.render_form(request, form, formsets, instance)

    def post(self, request, pk=None):
        instance = self.get_instance()
        form, formsets = self.build(request, instance)
        if form.is_valid() and all(fs.is_valid() for fs, _ in formsets):
            with transaction.atomic():
                obj = form.save()
                for fs, _ in formsets:
                    fs.instance = obj
                    fs.save()
                self.crud.after_save(request, obj, instance is None)
            messages.success(request, f"{self.crud.title()} „{obj}“ wurde gespeichert.")
            nxt = request.POST.get("next") or request.GET.get("next")
            if nxt and nxt.startswith("/"):
                return HttpResponseRedirect(nxt)
            return HttpResponseRedirect(self.crud.success_url(obj))
        messages.error(request, "Bitte die markierten Felder prüfen.")
        return self.render_form(request, form, formsets, instance)


class CrudCreate(CrudFormView):
    action = "add"


class CrudUpdate(CrudFormView):
    action = "change"

    def get_instance(self):
        return self.get_object()


class CrudDelete(CrudMixin, View):
    action = "delete"

    def get(self, request, pk):
        obj = self.get_object()
        return render(request, "core/crud/confirm_delete.html", self.base_context(object=obj, title="Löschen"))

    def post(self, request, pk):
        obj = self.get_object()
        label = str(obj)
        try:
            obj.delete()
        except ProtectedError as e:
            refs = ", ".join(sorted({str(o) for o in list(e.protected_objects)[:5]}))
            messages.error(request, f"„{label}“ kann nicht gelöscht werden, da es noch verwendet wird: {refs}")
            target = self.crud.url("detail", pk) if self.crud.has_detail else self.crud.url("list")
            return HttpResponseRedirect(target)
        messages.success(request, f"„{label}“ wurde gelöscht.")
        return HttpResponseRedirect(self.crud.url("list"))


def object_history(obj, limit=30):
    ct = ContentType.objects.get_for_model(obj)
    return AuditLog.objects.filter(content_type=ct, object_id=str(obj.pk)).select_related("user")[:limit]


def notes_context(request, obj):
    ct = ContentType.objects.get_for_model(obj)
    try:
        return_url = request.get_full_path()
        note_url = reverse("core:note_add", args=[ct.pk, obj.pk])
        attach_url = reverse("core:attachment_add", args=[ct.pk, obj.pk])
    except NoReverseMatch:  # pragma: no cover
        return {}
    return {
        "notes": Note.objects.filter(content_type=ct, object_id=obj.pk).select_related("author"),
        "attachments": Attachment.objects.filter(content_type=ct, object_id=obj.pk).select_related("uploaded_by"),
        "note_url": note_url,
        "attachment_url": attach_url,
        "return_url": return_url,
    }
