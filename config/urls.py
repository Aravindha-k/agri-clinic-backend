from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.http import JsonResponse

from rest_framework.permissions import IsAdminUser

from accounts.views import LogoutAPI, LoginAPI
from accounts.token_refresh import AgriWebTokenRefreshView
from tracking.views import StartWorkDayAPI, EndWorkDayAPI
from visits.dashboard_views import MapFarmersAPI

from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularSwaggerView,
    SpectacularRedocView,
)
from masters.problem_item_views import (
    CropListAPI,
    CropProblemItemListAPI,
    ProblemItemListAPI,
)


class StaffSpectacularAPIView(SpectacularAPIView):
    permission_classes = [IsAdminUser]


class StaffSpectacularSwaggerView(SpectacularSwaggerView):
    permission_classes = [IsAdminUser]


class StaffSpectacularRedocView(SpectacularRedocView):
    permission_classes = [IsAdminUser]


def health_check(_request):
    """Liveness + basic DB probe (legacy /healthz/)."""
    from django.db import connection

    payload = {"status": "ok", "database": "ok"}
    http_status = 200
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except Exception:
        payload["status"] = "degraded"
        payload["database"] = "error"
        http_status = 503
    return JsonResponse(payload, status=http_status)


def liveness(_request):
    """Process is up (no dependency checks)."""
    return JsonResponse({"status": "alive"})


def readiness(_request):
    """
    Readiness for load balancers.

    Checks database. Celery/Redis are reported when configured but do not
    fail readiness unless CELERY_REQUIRED_FOR_READY=true (production beat/worker
    may be separate services).
    """
    from django.conf import settings
    from django.db import connection

    payload = {
        "status": "ready",
        "database": "ok",
        "celery_broker": "unverified",
        "notes": (
            "Celery worker/beat physical deployment is not verified by this "
            "endpoint unless CELERY_REQUIRED_FOR_READY=true."
        ),
    }
    http_status = 200
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except Exception:
        payload["status"] = "not_ready"
        payload["database"] = "error"
        http_status = 503

    broker = getattr(settings, "CELERY_BROKER_URL", "") or ""
    if broker.startswith("memory://"):
        payload["celery_broker"] = "memory_dev_only"
    elif broker:
        payload["celery_broker"] = "configured"
    else:
        payload["celery_broker"] = "missing"

    require_celery = str(
        getattr(settings, "CELERY_REQUIRED_FOR_READY", False)
    ).lower() in ("1", "true", "yes")
    if require_celery and payload["celery_broker"] in ("missing", "memory_dev_only"):
        payload["status"] = "not_ready"
        http_status = 503

    return JsonResponse(payload, status=http_status)


urlpatterns = [
    path("admin/", admin.site.urls),
    path("healthz/", health_check, name="health-check"),
    path("livez/", liveness, name="liveness"),
    path("readyz/", readiness, name="readiness"),
    # Auth endpoints
    path("api/v1/auth/login/", LoginAPI.as_view(), name="token-obtain"),
    path("api/v1/auth/logout/", LogoutAPI.as_view(), name="logout"),
    path("api/v1/auth/refresh/", AgriWebTokenRefreshView.as_view(), name="token-refresh"),
    # Work session endpoints
    path("api/v1/work/start/", StartWorkDayAPI.as_view(), name="work-start"),
    path("api/v1/work/stop/", EndWorkDayAPI.as_view(), name="work-stop"),
    # Duty tracking (canonical paths without v1 prefix)
    path("api/tracking/", include("tracking.duty_urls")),
    path("api/admin/tracking/", include("tracking.admin_tracking_urls")),
    path("api/admin/visits/", include("tracking.admin_report_urls")),
    path("api/admin/employees/", include("tracking.admin_employee_report_urls")),
    # Dashboard + Map (root alias + nested routes share one mount)
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
    # Problem Items + crops (web/mobile aliases)
    path("api/v1/problem-items/", ProblemItemListAPI.as_view(), name="problem-items-list"),
    path("api/v1/crops/", CropListAPI.as_view(), name="crops-list"),
    path(
        "api/v1/crops/<int:crop_id>/problem-items/",
        CropProblemItemListAPI.as_view(),
        name="crop-problem-items-list",
    ),
    # Farmer-centric APIs (central entity)
    path("api/v1/", include("farmers.urls")),
    path("api/v1/notifications/", include("notifications.urls")),
    path("api/v1/system/", include("system_settings.urls")),
    path("api/v1/audit/", include("audit_logs.urls")),
    # ── OpenAPI schema + documentation (staff-only) ─────────────
    path("api/schema/", StaffSpectacularAPIView.as_view(), name="schema"),
    path(
        "api/docs/",
        StaffSpectacularSwaggerView.as_view(url_name="schema"),
        name="swagger-ui",
    ),
    path(
        "api/redoc/",
        StaffSpectacularRedocView.as_view(url_name="schema"),
        name="redoc",
    ),
    path("api/v1/schema/", StaffSpectacularAPIView.as_view(), name="schema-v1"),
    path(
        "api/v1/docs/",
        StaffSpectacularSwaggerView.as_view(url_name="schema"),
        name="swagger-ui-v1",
    ),
    # Admin dashboard ViewSets (router: fields/, dashboard/stats/, etc.)
    path("api/v1/", include("api.admin.urls")),
    path("api/v1/admin/", include("api.admin.urls")),
    path("api/v1/mobile/", include("mobile_api.urls")),
]

# Serve uploaded media from Django only in DEBUG. Production must use Nginx
# (with auth / private access) or signed S3 URLs — never anonymous public /media/.
if settings.DEBUG and not settings.USE_S3:
    urlpatterns += static(
        settings.MEDIA_URL,
        document_root=settings.MEDIA_ROOT,
    )
