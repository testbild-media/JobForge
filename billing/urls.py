from django.urls import include, path

from . import views

app_name = "billing"

urlpatterns = [
    path("dokumente/", include(views.DocumentCrud.urls())),
    path("dokumente/<int:pk>/positionen/", views.document_positions, name="document_positions"),
    path("dokumente/<int:pk>/festschreiben/", views.document_finalize, name="document_finalize"),
    path("dokumente/<int:pk>/status/", views.document_set_status, name="document_status"),
    path("dokumente/<int:pk>/umwandeln/", views.document_convert, name="document_convert"),
    path("dokumente/<int:pk>/stornieren/", views.document_cancel, name="document_cancel"),
    path("dokumente/<int:pk>/pdf/", views.document_pdf, name="document_pdf"),
    path("dokumente/<int:pk>/vorschau/", views.document_preview, name="document_preview"),
    path("dokumente/<int:pk>/xrechnung/", views.document_xrechnung, name="document_xrechnung"),
    path("dokumente/<int:pk>/senden/", views.document_send, name="document_send"),
    path("dokumente/<int:pk>/zahlung/", views.payment_add, name="payment_add"),
    path("aus-job/<int:pk>/", views.document_from_job, name="document_from_job"),
    path("zahlungen/", include(views.PaymentCrud.urls())),
    path("offene-posten/", views.open_items, name="open_items"),
    path("layouts/", include(views.LayoutCrud.urls())),
]
