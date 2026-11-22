from django.urls import include, path

from . import views

app_name = "inventory"

urlpatterns = [
    path("artikel/", include(views.ArticleCrud.urls())),
    path("geraete/", include(views.UnitCrud.urls())),
    path("geraete/<int:pk>/zustand/", views.unit_condition, name="unit_condition"),
    path("lagerorte/", include(views.LocationCrud.urls())),
    path("kategorien/", include(views.CategoryCrud.urls())),
    path("gruppen/", include(views.GroupCrud.urls())),
    path("bestaende/", include(views.StockCrud.urls())),
    path("bewegungen/", include(views.MovementCrud.urls())),
    path("wareneingang/", views.receive, name="receive"),
    path("umlagerung/", views.transfer, name="transfer"),
    path("inventur/", views.adjust, name="adjust"),
    path("defekt/", views.bulk_condition, name="bulk_condition"),
    path("defekte/", views.defects, name="defects"),
    path("scanner/", views.scan, name="scan"),
    path("etiketten/", views.labels, name="labels"),
    path("etiketten/ptouch/", views.labels_ptouch, name="labels_ptouch"),
    path("qr/<path:code>.svg", views.qr_svg, name="qr"),
    path("verfuegbarkeit/", views.availability, name="availability"),
    path("artikel-info/", views.article_lookup, name="article_lookup"),
]
