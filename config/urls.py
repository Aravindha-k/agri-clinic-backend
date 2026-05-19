from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.http import JsonResponse

from rest_framework_simplejwt.views import TokenRefreshView
from accounts.views import LogoutAPI, LoginAPI
from tracking.views import StartWorkDayAPI, EndWorkDayAPI
from visits.dashboard_views import MapFarmersAPI
from dashboard.views import DashboardView

from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularSwaggerView,
    SpectacularRedocView,
)


def health_check(_request):
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path("admin/", admin.site.urls),
    path("healthz/", health_check, name="health-check"),
    # Auth endpoints
    path("api/v1/auth/login/", LoginAPI.as_view(), name="token-obtain"),
    path("api/v1/auth/logout/", LogoutAPI.as_view(), name="logout"),
    path("api/v1/auth/refresh/", TokenRefreshView.as_view(), name="token-refresh"),
    # Work session endpoints
    path("api/v1/work/start/", StartWorkDayAPI.as_view(), name="work-start"),
    path("api/v1/work/stop/", EndWorkDayAPI.as_view(), name="work-stop"),
    # Dashboard + Map
    path("api/v1/dashboard/", DashboardView.as_view(), name="dashboard"),
    path("api/v1/dashboard/", include("dashboard.urls")),
    path("api/v1/map/farmers/", MapFarmersAPI.as_view(), name="map-farmers"),
    # Visits endpoints (CRUD, stats, attachments, media)
    path("api/v1/visits/", include("visits.urls")),
    # Reports endpoints (daily, monthly, etc.)
    path("api/v1/reports/", include("reports.urls")),
    # Employees endpoints
    path("api/v1/employees/", include("accounts.urls")),
    # Tracking endpoints (live, dashboard, geojson, etc.)
    path("api/v1/tracking/", include("tracking.urls")),
    # Masters, notifications, system settings, audit logs
    path("api/v1/masters/", include("masters.urls")),
    # Farmer-centric APIs (central entity)
    path("api/v1/", include("farmers.urls")),
    path("api/v1/notifications/", include("notifications.urls")),
    path("api/v1/system/", include("system_settings.urls")),
    path("api/v1/audit/", include("audit_logs.urls")),
    # ── OpenAPI schema + documentation ─────────────────────────
    # Raw OpenAPI schema (JSON/YAML)
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    # Swagger UI
    path(
        "api/docs/",
        SpectacularSwaggerView.as_view(url_name="schema"),
        name="swagger-ui",
    ),
    # ReDoc UI
    path(
        "api/redoc/",
        SpectacularRedocView.as_view(url_name="schema"),
        name="redoc",
    ),
    # Legacy v1 aliases (kept for backwards-compat)
    path("api/v1/schema/", SpectacularAPIView.as_view(), name="schema-v1"),
    path(
        "api/v1/docs/",
        SpectacularSwaggerView.as_view(url_name="schema"),
        name="swagger-ui-v1",
    ),
    # Admin dashboard ViewSets (router: fields/, dashboard/stats/, etc.)
    path("api/v1/", include("api.admin.urls")),
    path("api/v1/admin/", include("api.admin.urls")),
    path("api/v1/mobile/", include("mobile_api.urls")),
]

# Serve uploaded media from disk when not using S3 (local dev + Render disk).
if not settings.USE_S3:
    urlpatterns += static(
        settings.MEDIA_URL,
        document_root=settings.MEDIA_ROOT,
    )
