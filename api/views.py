from django.shortcuts import get_object_or_404
from django.utils.dateparse import parse_datetime
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from billing.models import Document, DocumentPosition, Payment
from contacts.models import Address, Contact, ContactPerson
from inventory import services as inv
from inventory.models import Article, ArticleGroup, Category, Location, Movement, Stock, Unit
from planning.availability import article_availability, job_material_check
from projects.models import Appointment, Job, JobPosition, JobStatus, Project, Task
from staff.models import Assignment, Availability, Employee, Qualification, TimeEntry

from . import serializers as s


def viewset(model, serializer, search=(), filters=(), ordering=None, select=()):
    attrs = {
        "queryset": model.objects.select_related(*select).all(),
        "serializer_class": serializer,
        "search_fields": list(search),
        "ordering": ordering or model._meta.ordering or ["pk"],
        "filter_fields": list(filters),
    }

    def get_queryset(self):
        qs = super(cls, self).get_queryset()
        for f in self.filter_fields:
            value = self.request.query_params.get(f)
            if value not in (None, ""):
                qs = qs.filter(**{f: value})
        return qs

    attrs["get_queryset"] = get_queryset
    cls = type(f"{model.__name__}ViewSet", (viewsets.ModelViewSet,), attrs)
    return cls


ContactViewSet = viewset(Contact, s.ContactSerializer, ["number", "company_name", "last_name", "email", "city"],
                         ["contact_type", "active"])
ContactPersonViewSet = viewset(ContactPerson, s.ContactPersonSerializer, ["last_name", "email"], ["contact"])
AddressViewSet = viewset(Address, s.AddressSerializer, ["street", "city"], ["contact", "kind"])
LocationViewSet = viewset(Location, s.LocationSerializer, ["name", "code", "path"], ["parent", "kind"])
CategoryViewSet = viewset(Category, s.CategorySerializer, ["name"], ["parent"])
ArticleGroupViewSet = viewset(ArticleGroup, s.ArticleGroupSerializer, ["name"])
ArticleViewSet = viewset(Article, s.ArticleSerializer, ["number", "name", "barcode", "manufacturer"],
                         ["kind", "group", "category", "active"])
UnitViewSet = viewset(Unit, s.UnitSerializer, ["code", "serial_number", "article__name"],
                      ["article", "condition", "location", "current_job"], select=["article"])
StockViewSet = viewset(Stock, s.StockSerializer, ["article__name"], ["article", "location"])
JobStatusViewSet = viewset(JobStatus, s.JobStatusSerializer)
ProjectViewSet = viewset(Project, s.ProjectSerializer, ["number", "name"], ["customer", "status", "is_template"])
JobPositionViewSet = viewset(JobPosition, s.JobPositionSerializer, ["description"], ["job", "kind", "article"])
TaskViewSet = viewset(Task, s.TaskSerializer, ["title"], ["job", "project", "assignee", "done"])
AppointmentViewSet = viewset(Appointment, s.AppointmentSerializer, ["title"], ["job", "project"])
DocumentPositionViewSet = viewset(DocumentPosition, s.DocumentPositionSerializer, ["description"], ["document"])
PaymentViewSet = viewset(Payment, s.PaymentSerializer, ["reference"], ["document", "method"])
QualificationViewSet = viewset(Qualification, s.QualificationSerializer, ["name"])
EmployeeViewSet = viewset(Employee, s.EmployeeSerializer, ["first_name", "last_name", "email"], ["kind", "active"])
AvailabilityViewSet = viewset(Availability, s.AvailabilitySerializer, [], ["employee", "kind"])
AssignmentViewSet = viewset(Assignment, s.AssignmentSerializer, ["role"], ["job", "employee", "status"])
TimeEntryViewSet = viewset(TimeEntry, s.TimeEntrySerializer, ["activity"], ["employee", "job", "approved", "date"])


class MovementViewSet(viewsets.ReadOnlyModelViewSet):
    """Lagerbewegungen (nur lesend – Buchungen über die Aktionen von Jobs bzw. /scan)."""

    queryset = Movement.objects.select_related("article", "unit").all()
    serializer_class = s.MovementSerializer
    search_fields = ["article__name", "unit__code", "note"]


class JobViewSet(viewset(Job, s.JobSerializer, ["number", "title", "venue"], ["customer", "status", "project",
                                                                              "is_template"])):
    @extend_schema(description="Materialprüfung: benötigte Mengen und Engpässe im Jobzeitraum.")
    @action(detail=True, methods=["get"])
    def material(self, request, pk=None):
        job = self.get_object()
        return Response([
            {"article": r["article"].pk, "name": r["article"].name, "required": r["required"],
             "capacity": r["capacity"], "available": r["available"], "shortage": r["shortage"]}
            for r in job_material_check(job)
        ])

    @extend_schema(description="Material ausgeben (checkout) bzw. zurücknehmen (checkin) per Code oder Artikel-ID.")
    @action(detail=True, methods=["post"])
    def scan(self, request, pk=None):
        job = self.get_object()
        if not request.user.has_perm("inventory.add_movement"):
            return Response({"detail": "Keine Berechtigung."}, status=403)
        mode = request.data.get("mode", "out")
        code = request.data.get("code", "")
        qty = request.data.get("quantity", 1)
        unit = article = None
        if code:
            kind, obj = inv.resolve_code(code)
            unit = obj if kind == "unit" else None
            article = obj if kind == "article" else None
        elif request.data.get("article"):
            article = get_object_or_404(Article, pk=request.data["article"])
        if not unit and not article:
            raise ValidationError({"code": "Unbekannter Code."})
        try:
            if mode == "out":
                moves = inv.checkout(job, unit=unit, article=article, quantity=qty, user=request.user)
            else:
                moves = inv.checkin(job, unit=unit, article=article, quantity=qty, user=request.user,
                                    defective=bool(request.data.get("defective")))
        except inv.InventoryError as e:
            raise ValidationError({"detail": str(e)})
        return Response(s.MovementSerializer(moves, many=True).data, status=201)


class DocumentViewSet(viewset(Document, s.DocumentSerializer, ["number", "subject"],
                              ["doc_type", "status", "customer", "job"])):
    def perform_destroy(self, instance):
        if instance.is_locked:
            raise ValidationError("Festgeschriebene Dokumente können nicht gelöscht werden.")
        instance.delete()

    @action(detail=True, methods=["post"])
    def finalize(self, request, pk=None):
        doc = self.get_object()
        if not request.user.has_perm("billing.finalize_document"):
            return Response({"detail": "Keine Berechtigung."}, status=403)
        doc.finalize(request.user)
        return Response(self.get_serializer(doc).data)


@extend_schema(parameters=[OpenApiParameter("article", int), OpenApiParameter("start", str),
                           OpenApiParameter("end", str)],
               description="Verfügbarkeit eines Artikels im Zeitraum (ISO-8601).", responses=OpenApiTypes.OBJECT)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def availability(request):
    article = get_object_or_404(Article, pk=request.query_params.get("article"))
    start = parse_datetime(request.query_params.get("start", ""))
    end = parse_datetime(request.query_params.get("end", ""))
    if not start or not end:
        raise ValidationError("start und end im ISO-Format angeben, z. B. 2026-05-01T08:00:00")
    r = article_availability(article, start, end)
    return Response({"article": article.pk, "capacity": r["capacity"], "booked": r["booked"],
                     "available": r["available"], "jobs": [j.pk for j in r.get("jobs", [])]})


@extend_schema(parameters=[OpenApiParameter("code", str)], description="Code (QR/Barcode) auflösen.",
               responses=OpenApiTypes.OBJECT)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def scan_lookup(request):
    kind, obj = inv.resolve_code(request.query_params.get("code", ""))
    if obj is None:
        return Response({"found": False}, status=404)
    ser = {"unit": s.UnitSerializer, "article": s.ArticleSerializer, "location": s.LocationSerializer}[kind]
    return Response({"found": True, "type": kind, "data": ser(obj).data})


@extend_schema(responses=OpenApiTypes.OBJECT, description="Angemeldeter Benutzer.")
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def me(request):
    u = request.user
    return Response({"id": u.pk, "username": u.username, "name": u.get_full_name(), "email": u.email,
                     "groups": [g.name for g in u.groups.all()], "is_superuser": u.is_superuser})
