from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path, re_path

from core import views as core_views

admin.site.site_header = "JobForge Administration"
admin.site.site_title = "JobForge"

urlpatterns = [
    path("login/", auth_views.LoginView.as_view(redirect_authenticated_user=True), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("passwort/", auth_views.PasswordChangeView.as_view(success_url="/"), name="password_change"),
    path("manifest.webmanifest", core_views.manifest, name="manifest"),
    path("sw.js", core_views.service_worker, name="service_worker"),
    path("offline/", core_views.offline, name="offline"),
    path("health/", core_views.health, name="health"),
    re_path(r"^media/(?P<path>.+)$", core_views.media, name="media"),
    path("admin/", admin.site.urls),
    path("api/", include("api.urls")),
    path("kontakte/", include("contacts.urls")),
    path("lager/", include("inventory.urls")),
    path("projekte/", include("projects.urls")),
    path("finanzen/", include("billing.urls")),
    path("personal/", include("staff.urls")),
    path("planung/", include("planning.urls")),
    path("", include("core.urls")),
]
