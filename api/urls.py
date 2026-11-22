from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
for prefix, vs in [
    ("contacts", views.ContactViewSet), ("contact-persons", views.ContactPersonViewSet),
    ("addresses", views.AddressViewSet), ("locations", views.LocationViewSet), ("categories", views.CategoryViewSet),
    ("article-groups", views.ArticleGroupViewSet), ("articles", views.ArticleViewSet), ("units", views.UnitViewSet),
    ("stock", views.StockViewSet), ("movements", views.MovementViewSet), ("job-statuses", views.JobStatusViewSet),
    ("projects", views.ProjectViewSet), ("jobs", views.JobViewSet), ("job-positions", views.JobPositionViewSet),
    ("tasks", views.TaskViewSet), ("appointments", views.AppointmentViewSet), ("documents", views.DocumentViewSet),
    ("document-positions", views.DocumentPositionViewSet), ("payments", views.PaymentViewSet),
    ("qualifications", views.QualificationViewSet), ("employees", views.EmployeeViewSet),
    ("availabilities", views.AvailabilityViewSet), ("assignments", views.AssignmentViewSet),
    ("time-entries", views.TimeEntryViewSet),
]:
    router.register(prefix, vs, basename=prefix)

urlpatterns = [
    path("v1/", include(router.urls)),
    path("v1/availability/", views.availability, name="api-availability"),
    path("v1/scan/", views.scan_lookup, name="api-scan"),
    path("v1/me/", views.me, name="api-me"),
    path("schema/", SpectacularAPIView.as_view(), name="api-schema"),
    path("docs/", SpectacularSwaggerView.as_view(url_name="api-schema"), name="api-docs"),
]
