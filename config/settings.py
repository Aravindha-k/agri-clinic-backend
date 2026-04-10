from pathlib import Path
from datetime import timedelta
import os

import dj_database_url
from dotenv import load_dotenv

# --------------------------------------------------
# BASE DIR & ENV
# --------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv()


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


# --------------------------------------------------
# SECURITY
# --------------------------------------------------
SECRET_KEY = os.getenv("SECRET_KEY", "unsafe-secret")
DEBUG = env_bool("DEBUG", True)

DEFAULT_ALLOWED_HOSTS = [
    "*",
    "agri-clinic-backend.onrender.com",
    ".onrender.com",
    "localhost",
    "127.0.0.1",
    "192.168.29.18",
]
ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", DEFAULT_ALLOWED_HOSTS)

CSRF_TRUSTED_ORIGINS = [
    "https://agri-clinic-backend.onrender.com",
    "http://192.168.29.18:8000",
]

USE_X_FORWARDED_HOST = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", not DEBUG)
SECURE_HSTS_SECONDS = int(
    os.getenv("SECURE_HSTS_SECONDS", "31536000" if not DEBUG else "0")
)
SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool("SECURE_HSTS_INCLUDE_SUBDOMAINS", not DEBUG)
SECURE_HSTS_PRELOAD = env_bool("SECURE_HSTS_PRELOAD", not DEBUG)

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
    "visits",
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
CORS_ALLOW_ALL_ORIGINS = True
CORS_ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "https://agri-clinic-frontend.onrender.com",
]
# --------------------------------------------------
# DRF + JWT
# --------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
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

ROOT_URLCONF = "config.urls"

# --------------------------------------------------
# DATABASE CONFIG
# --------------------------------------------------
DATABASE_URL = os.getenv("DATABASE_URL")

if DATABASE_URL:
    DATABASES = {
        "default": dj_database_url.parse(
            DATABASE_URL,
            conn_max_age=600,
            ssl_require="localhost" not in DATABASE_URL,
        )
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

# --------------------------------------------------
# STATIC FILES
# --------------------------------------------------
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

# --------------------------------------------------
# MEDIA & STORAGE (ENTERPRISE FIX)
# --------------------------------------------------
USE_S3 = os.getenv("USE_S3", "false").lower() == "true"

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

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
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

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

# --------------------------------------------------
# CELERY
# --------------------------------------------------
CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", REDIS_URL)
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", REDIS_URL)
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
