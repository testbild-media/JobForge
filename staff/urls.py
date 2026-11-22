from django.urls import include, path

from . import views

app_name = "staff"

urlpatterns = [
    path("", include(views.EmployeeCrud.urls())),
    path("qualifikationen/", include(views.QualificationCrud.urls())),
    path("abwesenheiten/", include(views.AvailabilityCrud.urls())),
    path("einsaetze/", include(views.AssignmentCrud.urls())),
    path("einsaetze/<int:pk>/status/", views.assignment_status, name="assignment_status"),
    path("zeiten/", include(views.TimeEntryCrud.urls())),
    path("zeiten/stempeluhr/", views.timer, name="timer"),
    path("zeiten/freigeben/", views.approve_entries, name="approve_entries"),
    path("planung/", views.planner, name="planner"),
    path("meine-einsaetze/", views.my_assignments, name="my_assignments"),
    path("verfuegbar/", views.free_staff, name="free_staff"),
]
