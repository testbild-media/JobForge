from django.urls import path

from . import views

app_name = "planning"

urlpatterns = [
    path("kalender/", views.calendar_view, name="calendar"),
    path("kalender.ics", views.ics_export, name="ics"),
    path("konflikte/", views.conflicts, name="conflicts"),
]
