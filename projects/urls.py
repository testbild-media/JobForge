from django.urls import include, path

from . import views

app_name = "projects"

urlpatterns = [
    path("", include(views.ProjectCrud.urls())),
    path("<int:pk>/duplizieren/", views.project_duplicate, name="project_duplicate"),
    path("jobs/", include(views.JobCrud.urls())),
    path("jobs/aus-vorlage/", views.job_from_template, name="job_from_template"),
    path("jobs/<int:pk>/positionen/", views.job_positions, name="job_positions"),
    path("jobs/<int:pk>/status/", views.job_status, name="job_status"),
    path("jobs/<int:pk>/duplizieren/", views.job_duplicate, name="job_duplicate"),
    path("jobs/<int:pk>/personal-uebernehmen/", views.job_staff_positions, name="job_staff_positions"),
    path("jobs/<int:pk>/packliste/", views.packlist, name="job_packlist"),
    path("jobs/<int:pk>/ausgabe/", views.job_scan, name="job_scan"),
    path("jobs/<int:pk>/verbrauch/", views.job_consume, name="job_consume"),
    path("aufgaben/", include(views.TaskCrud.urls())),
    path("aufgaben/<int:pk>/umschalten/", views.task_toggle, name="task_toggle"),
    path("termine/", include(views.AppointmentCrud.urls())),
    path("status/", include(views.StatusCrud.urls())),
]
