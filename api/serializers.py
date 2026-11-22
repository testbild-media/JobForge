from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from billing.models import Document, DocumentPosition, Payment
from contacts.models import Address, Contact, ContactPerson
from inventory.models import Article, ArticleGroup, Category, Location, Movement, SetComponent, Stock, Unit
from projects.models import Appointment, Job, JobPosition, JobStatus, Project, Task
from staff.models import Assignment, Availability, Employee, Qualification, TimeEntry


class ContactPersonSerializer(serializers.ModelSerializer):
    class Meta:
        model = ContactPerson
        fields = "__all__"


class AddressSerializer(serializers.ModelSerializer):
    class Meta:
        model = Address
        fields = "__all__"


class ContactSerializer(serializers.ModelSerializer):
    name = serializers.CharField(read_only=True)
    persons = ContactPersonSerializer(many=True, read_only=True)
    addresses = AddressSerializer(many=True, read_only=True)

    class Meta:
        model = Contact
        fields = "__all__"
        read_only_fields = ["created", "updated"]
        extra_kwargs = {"number": {"required": False}}


class LocationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Location
        fields = "__all__"
        read_only_fields = ["path"]
        extra_kwargs = {"code": {"required": False}}


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = "__all__"


class ArticleGroupSerializer(serializers.ModelSerializer):
    class Meta:
        model = ArticleGroup
        fields = "__all__"


class SetComponentSerializer(serializers.ModelSerializer):
    class Meta:
        model = SetComponent
        fields = ["id", "component", "quantity"]


class ArticleSerializer(serializers.ModelSerializer):
    usable_quantity = serializers.SerializerMethodField()
    total_quantity = serializers.SerializerMethodField()
    components = SetComponentSerializer(many=True, read_only=True)

    class Meta:
        model = Article
        fields = "__all__"
        read_only_fields = ["created", "updated"]
        extra_kwargs = {"number": {"required": False}}

    @extend_schema_field(OpenApiTypes.DECIMAL)
    def get_usable_quantity(self, obj):
        return obj.usable_quantity()

    @extend_schema_field(OpenApiTypes.DECIMAL)
    def get_total_quantity(self, obj):
        return obj.total_quantity()


class UnitSerializer(serializers.ModelSerializer):
    class Meta:
        model = Unit
        fields = "__all__"
        read_only_fields = ["current_job", "created"]
        extra_kwargs = {"code": {"required": False}}


class StockSerializer(serializers.ModelSerializer):
    class Meta:
        model = Stock
        fields = "__all__"


class MovementSerializer(serializers.ModelSerializer):
    class Meta:
        model = Movement
        fields = "__all__"


class JobStatusSerializer(serializers.ModelSerializer):
    class Meta:
        model = JobStatus
        fields = "__all__"


class ProjectSerializer(serializers.ModelSerializer):
    class Meta:
        model = Project
        fields = "__all__"
        read_only_fields = ["created", "updated"]
        extra_kwargs = {"number": {"required": False}}


class JobPositionSerializer(serializers.ModelSerializer):
    net_total = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)

    class Meta:
        model = JobPosition
        fields = "__all__"


class JobSerializer(serializers.ModelSerializer):
    positions = JobPositionSerializer(many=True, read_only=True)
    status_name = serializers.CharField(source="status.name", read_only=True, default=None)

    class Meta:
        model = Job
        fields = "__all__"
        read_only_fields = ["created", "updated"]
        extra_kwargs = {"number": {"required": False}}


class TaskSerializer(serializers.ModelSerializer):
    class Meta:
        model = Task
        fields = "__all__"


class AppointmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Appointment
        fields = "__all__"


class DocumentPositionSerializer(serializers.ModelSerializer):
    net_total = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)

    class Meta:
        model = DocumentPosition
        fields = "__all__"


class PaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Payment
        fields = "__all__"


class DocumentSerializer(serializers.ModelSerializer):
    positions = DocumentPositionSerializer(many=True, read_only=True)
    payments = PaymentSerializer(many=True, read_only=True)
    net_total = serializers.SerializerMethodField()
    tax_total = serializers.SerializerMethodField()
    gross_total = serializers.SerializerMethodField()
    open_amount = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)

    class Meta:
        model = Document
        fields = "__all__"
        read_only_fields = ["number", "finalized_at", "created", "updated", "created_by"]

    @extend_schema_field(OpenApiTypes.DECIMAL)
    def get_net_total(self, obj):
        return obj.totals()["net_total"]

    @extend_schema_field(OpenApiTypes.DECIMAL)
    def get_tax_total(self, obj):
        return obj.totals()["tax_total"]

    @extend_schema_field(OpenApiTypes.DECIMAL)
    def get_gross_total(self, obj):
        return obj.totals()["gross"]

    def validate(self, attrs):
        if self.instance is not None and self.instance.is_locked:
            raise serializers.ValidationError("Festgeschriebene Dokumente können nicht geändert werden.")
        return attrs


class QualificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Qualification
        fields = "__all__"


class EmployeeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Employee
        fields = "__all__"
        extra_kwargs = {"number": {"required": False}}


class AvailabilitySerializer(serializers.ModelSerializer):
    class Meta:
        model = Availability
        fields = "__all__"


class AssignmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Assignment
        fields = "__all__"


class TimeEntrySerializer(serializers.ModelSerializer):
    hours = serializers.DecimalField(max_digits=8, decimal_places=2, read_only=True)

    class Meta:
        model = TimeEntry
        fields = "__all__"


REGISTRY = {
    Contact: ContactSerializer, Article: ArticleSerializer, Unit: UnitSerializer, Movement: MovementSerializer,
    Project: ProjectSerializer, Job: JobSerializer, Document: DocumentSerializer, Payment: PaymentSerializer,
    Employee: EmployeeSerializer, TimeEntry: TimeEntrySerializer, Assignment: AssignmentSerializer,
}


def serializer_for(model):
    return REGISTRY.get(model)
