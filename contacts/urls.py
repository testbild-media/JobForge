from django.urls import include, path

from .views import ContactCrud

app_name = "contacts"

urlpatterns = [
    path("", include(ContactCrud.urls())),
]
