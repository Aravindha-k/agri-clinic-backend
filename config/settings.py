from pathlib import Path
from datetime import timedelta
import os
from urllib.parse import quote, urlsplit, urlunsplit

import dj_database_url
from dotenv import load_dotenv

# --------------------------------------------------
# BASE DIR & ENV
# --------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent


def _is_production_env():
    app_env = os.getenv("APP_ENV", "local").strip().lower()
    if app_env in {"prod", "production", "render", "staging", "aws"}:
        return True
    return os.getenv("RENDER", "").strip().lower() in {"1", "true", "yes", "on"}


# Load .env when present; existing shell/platform env vars take precedence.
load_dotenv(override=False)


def env_bool(name, default=False):
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_list(name, default=None):
    value = os.getenv(name)
    if value is None:
        return list(default or [])
    cleaned = [item.strip() for item in value.split(",") if item.strip()]
    return cleaned or list(default or [])


def normalize_database_url(raw_url):
    if not raw_url:
        return raw_url

    parsed = urlsplit(raw_url)
    if parsed.scheme not in {"postgres", "postgresql"}:
        return raw_url

    host = parsed.hostname or ""
    if not (host.startswith("dpg-") and "." not in host):
        return raw_url

    host_suffix = os.getenv("RENDER_POSTGRES_HOST_SUFFIX", "").strip()
    if not host_suffix and _is_production_env():
        host_suffix = "singapore-postgres.render.com"
    if not host_suffix:
        return raw_url

    full_host = f"{host}.{host_suffix.lstrip('.')}"

    username = quote(parsed.username or "", safe="")
    password = quote(parsed.password or "", safe="")
    auth = username
    if password:
        auth = f"{auth}:{password}"
    if auth:
        auth = f"{auth}@"

    port = parsed.port or 5432
    query = parsed.query

    fixed_netloc = f"{auth}{full_host}:{port}"
    return urlunsplit(
        (parsed.scheme, fixed_netloc, parsed.path, query, parsed.fragment)
    )


# --------------------------------------------------
# SECURITY
# --------------------------------------------------
APP_ENV = os.getenv("APP_ENV", "local").strip().lower()
IS_PRODUCTION = APP_ENV in {"prod", "production", "render", "staging", "aws"}

SECRET_KEY = os.getenv("SECRET_KEY", "unsafe-secret")
DEBUG = env_bool("DEBUG", not IS_PRODUCTION)

_INSECURE_SECRET_KEYS = {
    "",
    "unsafe-secret",
    "change-me-to-a-long-random-string",
}
if IS_PRODUCTION and SECRET_KEY in _INSECURE_SECRET_KEYS:
    raise RuntimeError(
        "SECRET_KEY must be set to a long random value when APP_ENV is production-like."
    )

DEFAULT_ALLOWED_HOSTS = (
    ["agri-clinic-backend.onrender.com", ".onrender.com"]
    if IS_PRODUCTION
    else ["localhost", "127.0.0.1", "192.168.29.18"]
)
ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", DEFAULT_ALLOWED_HOSTS)

DEFAULT_CSRF_TRUSTED_ORIGINS = (
    ["https://agri-clinic-backend.onrender.com"]
    if IS_PRODUCTION
    else ["http://localhost:8000", "http://127.0.0.1:8000", "http://192.168.29.18:8000"]
)
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS", DEFAULT_CSRF_TRUSTED_ORIGINS)

USE_X_FORWARDED_HOST = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", IS_PRODUCTION)
SECURE_HSTS_SECONDS = int(
    os.getenv("SECURE_HSTS_SECONDS", "31536000" if IS_PRODUCTION else "0")
)
SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool(
    "SECURE_HSTS_INCLUDE_SUBDOMAINS", IS_PRODUCTION
)
SECURE_HSTS_PRELOAD = env_bool("SECURE_HSTS_PRELOAD", IS_PRODUCTION)

# --------------------------------------------------
# APPLICATIONS
# --------------------------------------------------

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # third party
    "rest_framework",
    "corsheaders",
    "storages",  # ✅ REQUIRED FOR S3
    "django_filters",
    # local apps
    "accounts",
    "tracking",
    "visits.apps.VisitsConfig",
    "notifications",
    "masters",
    "farmers",
    "audit_logs",
    "system_settings.apps.SystemSettingsConfig",
    "reports.apps.ReportsConfig",
    "drf_spectacular",
    "django_extensions",
    "mobile_api",
]

# Add django_celery_results only when celery is installed
try:
    import celery  # noqa: F401

    INSTALLED_APPS += ["django_celery_results"]
except ImportError:
    pass

# --------------------------------------------------
# MIDDLEWARE
# --------------------------------------------------
MIDDLEWARE = [
    "mobile_api.logging.MobileAPILoggingMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

# --------------------------------------------------
# TEMPLATES (REQUIRED FOR ADMIN)
# --------------------------------------------------
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],  # you can add BASE_DIR / "templates" later if needed
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

CSRF_COOKIE_SECURE = not DEBUG
SESSION_COOKIE_SECURE = not DEBUG
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
CORS_ALLOW_ALL_ORIGINS = env_bool("CORS_ALLOW_ALL_ORIGINS", not IS_PRODUCTION)
DEFAULT_CORS_ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "https://agri-clinic-frontend.onrender.com",
]
CORS_ALLOWED_ORIGINS = env_list("CORS_ALLOWED_ORIGINS", DEFAULT_CORS_ALLOWED_ORIGINS)
# --------------------------------------------------
# DRF + JWT
# --------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "accounts.authentication.AdminJWTAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ),
    "EXCEPTION_HANDLER": "config.exception_handler.custom_exception_handler",
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 50,
    "DEFAULT_PARSER_CLASSES": [
        "rest_framework.parsers.JSONParser",
        "rest_framework.parsers.MultiPartParser",
        "rest_framework.parsers.FormParser",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    # Rate limiting
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": "60/minute",
        "user": "300/minute",
        "login": "10/minute",
    },
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(hours=12),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "AUTH_HEADER_TYPES": ("Bearer",),
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
}

# Admin panel security (configurable via environment)
ADMIN_SESSION_TIMEOUT_MINUTES = int(os.getenv("ADMIN_SESSION_TIMEOUT_MINUTES", "30"))
ADMIN_LOGIN_MAX_ATTEMPTS = int(os.getenv("ADMIN_LOGIN_MAX_ATTEMPTS", "5"))
ADMIN_LOGIN_LOCKOUT_MINUTES = int(os.getenv("ADMIN_LOGIN_LOCKOUT_MINUTES", "15"))
ADMIN_IP_WHITELIST_ENABLED = env_bool("ADMIN_IP_WHITELIST_ENABLED", False)
ADMIN_ALLOWED_IPS = env_list("ADMIN_ALLOWED_IPS", [])

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 10},
    },
    {
        "NAME": "accounts.password_policy.StrongPasswordValidator",
    },
]

ROOT_URLCONF = "config.urls"

# --------------------------------------------------
# DATABASE CONFIG
# --------------------------------------------------
# Retired Render Postgres (suspended) — refuse if still set in Render env.
_BLOCKED_RENDER_DB_HOSTS = frozenset(
    {
        "dpg-d7ckj7dckfvc739s0frg-a",
        "dpg-d7ckj7dckfvc739s0frg-a.singapore-postgres.render.com",
    }
)


def _database_from_components() -> dict | None:
    """Build PostgreSQL config from DB_NAME, DB_USER, DB_PASSWORD, DB_HOST, DB_PORT."""
    name = os.getenv("DB_NAME", "").strip()
    user = os.getenv("DB_USER", "").strip()
    host = os.getenv("DB_HOST", "").strip()
    if not (name and user and host):
        return None
    port = os.getenv("DB_PORT", "5432").strip() or "5432"
    options = {"connect_timeout": 10}
    if env_bool("DB_SSL_REQUIRE", False):
        options["sslmode"] = "require"
    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": name,
        "USER": user,
        "PASSWORD": os.getenv("DB_PASSWORD", ""),
        "HOST": host,
        "PORT": port,
        "CONN_MAX_AGE": 600,
        "CONN_HEALTH_CHECKS": True,
        "OPTIONS": options,
    }


def _configure_databases() -> dict:
    database_url = normalize_database_url(os.getenv("DATABASE_URL", "").strip())
    if database_url:
        db_host = (urlsplit(database_url).hostname or "").strip().lower()
        default_ssl_require = bool(db_host) and not (
            db_host == "localhost"
            or db_host.startswith("127.")
            or db_host.startswith("dpg-")
        )
        databases = {
            "default": dj_database_url.parse(
                database_url,
                conn_max_age=600,
                ssl_require=env_bool("DB_SSL_REQUIRE", default_ssl_require),
            )
        }
        databases["default"]["CONN_HEALTH_CHECKS"] = True
        databases["default"].setdefault("OPTIONS", {})
        databases["default"]["OPTIONS"].setdefault("connect_timeout", 10)

        if IS_PRODUCTION:
            resolved_host = (urlsplit(database_url).hostname or "").strip().lower()
            short_host = resolved_host.split(".")[0] if resolved_host else ""
            if resolved_host in _BLOCKED_RENDER_DB_HOSTS or short_host in _BLOCKED_RENDER_DB_HOSTS:
                raise RuntimeError(
                    "DATABASE_URL points to a retired Render Postgres instance "
                    f"({short_host or resolved_host}). Update Render Dashboard → "
                    "agri-clinic-backend → Environment: set DATABASE_URL to the "
                    "agri_clinic_db instance (dpg-d84t75d7vvec73fhlpfg-a) and "
                    "RENDER_POSTGRES_HOST_SUFFIX=singapore-postgres.render.com, "
                    "then clear build cache and redeploy."
                )
        return databases

    component_db = _database_from_components()
    if component_db:
        return {"default": component_db}

    if IS_PRODUCTION:
        raise RuntimeError(
            "Production requires DATABASE_URL or DB_NAME, DB_USER, DB_HOST "
            "(and DB_PASSWORD, DB_PORT) in the environment."
        )

    return {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }


DATABASE_URL = normalize_database_url(os.getenv("DATABASE_URL", "").strip())
DATABASES = _configure_databases()

# --------------------------------------------------
# STATIC FILES
# --------------------------------------------------
STATIC_URL = os.getenv("STATIC_URL", "/static/")
STATIC_ROOT = Path(os.getenv("STATIC_ROOT", str(BASE_DIR / "staticfiles")))
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

# --------------------------------------------------
# MEDIA & STORAGE (ENTERPRISE FIX)
# --------------------------------------------------
USE_S3 = os.getenv("USE_S3", "false").lower() == "true"

MEDIA_URL = os.getenv("MEDIA_URL", "/media/")
MEDIA_ROOT = Path(os.getenv("MEDIA_ROOT", str(BASE_DIR / "media")))
# Profile photos: employee_photos/ and farmer_photos/ under MEDIA_ROOT.
# On Render without S3, files live on ephemeral disk — use a persistent disk or S3 for production.

if USE_S3:
    DEFAULT_FILE_STORAGE = "storages.backends.s3boto3.S3Boto3Storage"

    AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
    AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
    AWS_STORAGE_BUCKET_NAME = os.getenv("AWS_STORAGE_BUCKET_NAME")
    AWS_S3_REGION_NAME = os.getenv("AWS_S3_REGION_NAME", "ap-south-1")

    AWS_QUERYSTRING_AUTH = False
    AWS_DEFAULT_ACL = None
    AWS_S3_FILE_OVERWRITE = False
else:
    DEFAULT_FILE_STORAGE = "django.core.files.storage.FileSystemStorage"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --------------------------------------------------
# REDIS / CACHE
# --------------------------------------------------
REDIS_URL = os.getenv("REDIS_URL", "").strip()

if REDIS_URL:
    try:
        import redis  # noqa: F401

        CACHES = {
            "default": {
                "BACKEND": "django.core.cache.backends.redis.RedisCache",
                "LOCATION": REDIS_URL,
                "TIMEOUT": 300,
                "KEY_PREFIX": "agri_clinic",
            }
        }
    except ImportError:
        CACHES = {
            "default": {
                "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            }
        }
else:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        }
    }

# --------------------------------------------------
# CELERY
# --------------------------------------------------
CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", REDIS_URL or "memory://")
CELERY_RESULT_BACKEND = os.getenv(
    "CELERY_RESULT_BACKEND", REDIS_URL or "cache+memory://"
)
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = "Asia/Kolkata"
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 30 * 60  # 30 minutes hard limit
CELERY_TASK_SOFT_TIME_LIMIT = 25 * 60  # 25 minutes soft limit
CELERY_BEAT_SCHEDULE = {}

# --------------------------------------------------
# STRUCTURED LOGGING
# --------------------------------------------------
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "json": {
            "()": "logging.Formatter",
            "fmt": '{"time":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","message":"%(message)s"}',
            "datefmt": "%Y-%m-%dT%H:%M:%S",
        },
        "verbose": {
            "format": "[%(asctime)s] %(levelname)s [%(name)s:%(lineno)s] %(message)s",
            "datefmt": "%Y-%m-%dT%H:%M:%S",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "json" if not DEBUG else "verbose",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": LOG_LEVEL,
    },
    "loggers": {
        "django": {"handlers": ["console"], "level": "WARNING", "propagate": False},
        "django.request": {
            "handlers": ["console"],
            "level": "ERROR",
            "propagate": False,
        },
        "celery": {"handlers": ["console"], "level": LOG_LEVEL, "propagate": False},
        "agri_clinic": {"handlers": ["console"], "level": "DEBUG", "propagate": False},
    },
}

# --------------------------------------------------
# DRF SPECTACULAR (OpenAPI / Swagger)
# --------------------------------------------------
SPECTACULAR_SETTINGS = {
    "TITLE": "Agri Clinic API",
    "DESCRIPTION": (
        "Production-ready REST API for the Agri Clinic SaaS platform.\n\n"
        "## Authentication\n"
        "All protected endpoints require a **Bearer JWT** token.  \n"
        "Obtain tokens via `POST /api/v1/auth/login/` then pass:  \n"
        "`Authorization: Bearer <access_token>`\n\n"
        "## Standard Response Envelope\n"
        "**Success:** `{ success: true, message: string, data: object }`  \n"
        "**Error:**   `{ success: false, message: string, errors: object, code: string }`\n\n"
        "## Pagination\n"
        "All list endpoints return `{ count, next, previous, results }` under `data`.\n"
        "Use `?page=N&page_size=N` query params."
    ),
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    # JWT Bearer auth button in Swagger UI
    "SECURITY": [{"jwtAuth": []}],
    "COMPONENTS": {
        "securitySchemes": {
            "jwtAuth": {
                "type": "http",
                "scheme": "bearer",
                "bearerFormat": "JWT",
            }
        }
    },
    # Tag ordering in Swagger UI sidebar
    "TAGS": [
        {"name": "Auth", "description": "Login, logout, token refresh"},
        {"name": "Employees", "description": "Employee management (admin only)"},
        {"name": "Farmers", "description": "Farmer CRUD and profile APIs"},
        {"name": "Visits", "description": "Field visit creation, updates, media"},
        {"name": "Crop Issues", "description": "Crop issue reporting and tracking"},
        {"name": "Tracking", "description": "GPS tracking, work-day management"},
        {"name": "Dashboard", "description": "Summary stats, trends, heatmap"},
        {"name": "Notifications", "description": "User notification feeds"},
        {"name": "Audit Logs", "description": "Admin audit trail"},
        {"name": "Reports", "description": "Scheduled and on-demand reports"},
        {
            "name": "Masters",
            "description": "Reference data (crops, districts, villages)",
        },
        {"name": "System", "description": "System settings and administration"},
        {"name": "Mobile", "description": "Mobile app-specific endpoints"},
    ],
    # Schema generation options
    "ENUM_GENERATE_CHOICE_DESCRIPTION": True,
    "COMPONENT_SPLIT_REQUEST": True,
    "SORT_OPERATIONS": True,
    # Disambiguate status enum collisions across models
    "ENUM_NAME_OVERRIDES": {
        "VisitStatusEnum": "visits.models.Visit.STATUS_CHOICES",
        "CropIssueStatusEnum": "masters.models.CropIssue.STATUS_CHOICES",
        "ReportStatusEnum": "reports.models.Report.STATUS_CHOICES",
    },
    # Postman / redoc / swagger extras
    "SWAGGER_UI_SETTINGS": {
        "deepLinking": True,
        "persistAuthorization": True,
        "displayRequestDuration": True,
        "docExpansion": "none",
        "filter": True,
        "showExtensions": True,
        "tryItOutEnabled": True,
    },
    "REDOC_UI_SETTINGS": {
        "hideDownloadButton": False,
        "pathInMiddlePanel": True,
    },
    "PREPROCESSING_HOOKS": ["drf_spectacular.hooks.preprocess_exclude_path_format"],
    "POSTPROCESSING_HOOKS": ["drf_spectacular.hooks.postprocess_schema_enums"],
}

if IS_PRODUCTION:
    if DATABASE_URL:
        _resolved_db_host = urlsplit(DATABASE_URL).hostname or "(unknown)"
        print(f"[agri-clinic] DATABASE_URL host={_resolved_db_host}", flush=True)
    else:
        _db = DATABASES.get("default", {})
        print(
            f"[agri-clinic] DB host={_db.get('HOST', '(unknown)')} "
            f"name={_db.get('NAME', '(unknown)')}",
            flush=True,
        )
