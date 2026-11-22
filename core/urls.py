from django.urls import include, path

from . import views

app_name = "core"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("suche/", views.search, name="search"),
    path("notiz/<int:ct_id>/<int:obj_id>/", views.note_add, name="note_add"),
    path("notiz/<int:pk>/loeschen/", views.note_delete, name="note_delete"),
    path("datei/<int:ct_id>/<int:obj_id>/", views.attachment_add, name="attachment_add"),
    path("datei/<int:pk>/loeschen/", views.attachment_delete, name="attachment_delete"),
    path("einstellungen/", views.settings_index, name="settings"),
    path("einstellungen/firma/", views.company_settings, name="company"),
    path("einstellungen/nummernkreise/", include(views.SequenceCrud.urls())),
    path("einstellungen/steuersaetze/", include(views.TaxRateCrud.urls())),
    path("einstellungen/zahlungsbedingungen/", include(views.PaymentTermCrud.urls())),
    path("einstellungen/zusatzfelder/", include(views.CustomFieldCrud.urls())),
    path("einstellungen/webhooks/", include(views.WebhookCrud.urls())),
    path("einstellungen/webhooks/<int:pk>/test/", views.webhook_test, name="webhook_test"),
    path("einstellungen/benutzer/", include(views.UserCrud.urls())),
    path("einstellungen/rollen/", include(views.GroupCrud.urls())),
    path("einstellungen/protokoll/", include(views.AuditCrud.urls())),
    path("einstellungen/api/", views.api_access, name="api_access"),
    path("einstellungen/import-export/", views.import_export, name="import_export"),
    path("einstellungen/export/<str:key>/", views.export, name="export"),
    path("einstellungen/backup/", views.backup, name="backup"),
]
