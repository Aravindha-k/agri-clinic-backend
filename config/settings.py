from pathlib import Path
from datetime import timedelta
import os
import sys
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


def _is_render_env():
    """True only when explicitly running on Render (legacy sandbox)."""
    if os.getenv("RENDER", "").strip().lower() in {"1", "true", "yes", "on"}:
        return True
    return os.getenv("APP_ENV", "").strip().lower() == "render"

# Load .env when present; existing shell/platform env vars take precedence.
load_dotenv(override=False)


def env_bool(name, default=False):
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


# Placeholder tokens from *.example files — never treat as real hosts/origins.
_ENV_PLACEHOLDERS = {
    "YOUR_LAN_IP",
    "YOUR_EC2_PUBLIC_IP",
    "YOUR_DOMAIN.COM",
    "YOUR-DOMAIN.COM",
    "YOUR_STAGING_HOST",
}


def normalize_allowed_host(raw: str) -> str:
    """Return a Django ALLOWED_HOSTS entry (hostname only, no scheme/port)."""
    value = (raw or "").strip()
    if not value:
        return ""
    if value.upper() in _ENV_PLACEHOLDERS or value.upper().startswith("YOUR_"):
        return ""
    if "://" in value:
        parsed = urlsplit(value)
        value = parsed.hostname or ""
    elif value.startswith("[") and "]" in value:
        # [IPv6]:port → keep bracketed host without port
        end = value.find("]")
        host = value[: end + 1]
        rest = value[end + 1 :]
        value = host if rest.startswith(":") or rest == "" else value
    elif value.count(":") == 1:
        # hostname:port (not IPv6)
        host, maybe_port = value.rsplit(":", 1)
        if maybe_port.isdigit():
            value = host
    return value.strip()


def normalize_csrf_origin(raw: str) -> str:
    """Return a CSRF trusted origin (scheme://host[:port])."""
    value = (raw or "").strip().rstrip("/")
    if not value:
        return ""
    upper = value.upper()
    if any(token in upper for token in _ENV_PLACEHOLDERS) or "YOUR_" in upper:
        return ""
    if "://" not in value:
        # Allow bare host in env by assuming http for local-style hosts.
        value = f"http://{value}"
    parsed = urlsplit(value)
    if not parsed.scheme or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}"


def env_list(name, default=None):
    value = os.getenv(name)
    if value is None:
        return list(default or [])
    cleaned = [item.strip() for item in value.split(",") if item.strip()]
    return cleaned or list(default or [])


def env_host_list(name, default=None):
    """Comma-separated hosts for ALLOWED_HOSTS (ports/schemes stripped)."""
    raw_items = env_list(name, default)
    hosts = []
    seen = set()
    for item in raw_items:
        host = normalize_allowed_host(item)
        if host and host not in seen:
            seen.add(host)
            hosts.append(host)
    if hosts:
        return hosts
    # Re-normalize defaults if env was only placeholders.
    fallback = []
    for item in list(default or []):
        host = normalize_allowed_host(item)
        if host and host not in seen:
            seen.add(host)
            fallback.append(host)
    return fallback


def env_origin_list(name, default=None, *, csrf=False):
    """Comma-separated origins for CSRF_TRUSTED_ORIGINS or CORS_ALLOWED_ORIGINS."""
    raw_items = env_list(name, default)
    origins = []
    seen = set()
    for item in raw_items:
        origin = normalize_csrf_origin(item) if csrf else item.strip().rstrip("/")
        if not csrf and (
            origin.upper() in _ENV_PLACEHOLDERS or "YOUR_" in origin.upper()
        ):
            origin = ""
        if origin and origin not in seen:
            seen.add(origin)
            origins.append(origin)
    if origins:
        return origins
    fallback = []
    for item in list(default or []):
        origin = normalize_csrf_origin(item) if csrf else item.strip().rstrip("/")
        if origin and origin not in seen:
            seen.add(origin)
            fallback.append(origin)
    return fallback


def normalize_database_url(raw_url):
    """Normalize DATABASE_URL. Do not invent Render host suffixes for AWS."""
    if not raw_url:
        return raw_url

    parsed = urlsplit(raw_url)
    if parsed.scheme not in {"postgres", "postgresql"}:
        return raw_url

    host = parsed.hostname or ""
    # Legacy Render short hosts (dpg-xxx without domain) only expand when
    # explicitly running on Render (RENDER=true) and a suffix is configured.
    if not (host.startswith("dpg-") and "." not in host):
        return raw_url

    if not _is_render_env():
        return raw_url

    host_suffix = os.getenv("RENDER_POSTGRES_HOST_SUFFIX", "").strip()
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

# Hosts are env-driven. Local LAN IPs belong in `.env` (see LOCAL_NETWORK_CONFIGURATION.md).
# EXTRA_ALLOWED_HOSTS is merged so developers can append a LAN IP without rewriting the full list.
# Production defaults are intentionally empty — set ALLOWED_HOSTS on the AWS EC2 .env.
DEFAULT_ALLOWED_HOSTS = (
    []
    if IS_PRODUCTION
    else ["localhost", "127.0.0.1"]
)
ALLOWED_HOSTS = env_host_list("ALLOWED_HOSTS", DEFAULT_ALLOWED_HOSTS)
_extra_hosts = env_host_list("EXTRA_ALLOWED_HOSTS", [])
for _host in _extra_hosts:
    if _host not in ALLOWED_HOSTS:
        ALLOWED_HOSTS.append(_host)

DEFAULT_CSRF_TRUSTED_ORIGINS = (
    []
    if IS_PRODUCTION
    else ["http://localhost:8000", "http://127.0.0.1:8000"]
)
CSRF_TRUSTED_ORIGINS = env_origin_list(
    "CSRF_TRUSTED_ORIGINS", DEFAULT_CSRF_TRUSTED_ORIGINS, csrf=True
)
_extra_csrf = env_origin_list("EXTRA_CSRF_TRUSTED_ORIGINS", [], csrf=True)
for _origin in _extra_csrf:
    if _origin not in CSRF_TRUSTED_ORIGINS:
        CSRF_TRUSTED_ORIGINS.append(_origin)

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
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",
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

# --------------------------------------------------
# INTERNATIONALIZATION / TIMEZONE
# --------------------------------------------------
LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Kolkata"
USE_I18N = True
USE_TZ = True

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
    "config.request_id.RequestIdMiddleware",
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

# Mobile bootstrap / force-update hints (optional; null = no client gate)
MINIMUM_SUPPORTED_APP_VERSION = os.getenv("MINIMUM_SUPPORTED_APP_VERSION") or None
FORCE_APP_UPDATE = os.getenv("FORCE_APP_UPDATE", "false").lower() in (
    "1",
    "true",
    "yes",
)

# Admin Live Tracking: Online / Stale / Offline based on heartbeat freshness.
# Defaults: Online ≤ 7m, Stale ≤ 15m, then Offline.
LIVE_TRACKING_ONLINE_SECONDS = int(os.getenv("LIVE_TRACKING_ONLINE_SECONDS", str(7 * 60)))
LIVE_TRACKING_STALE_SECONDS = int(os.getenv("LIVE_TRACKING_STALE_SECONDS", str(15 * 60)))

# Visit media upload limits (images / voice notes / short videos).
VISIT_MEDIA_IMAGE_MAX_BYTES = int(
    os.getenv("VISIT_MEDIA_IMAGE_MAX_BYTES", str(10 * 1024 * 1024))
)
VISIT_MEDIA_AUDIO_MAX_BYTES = int(
    os.getenv("VISIT_MEDIA_AUDIO_MAX_BYTES", str(15 * 1024 * 1024))
)
VISIT_MEDIA_VIDEO_MAX_BYTES = int(
    os.getenv("VISIT_MEDIA_VIDEO_MAX_BYTES", str(75 * 1024 * 1024))
)
VISIT_MEDIA_BILL_MAX_BYTES = int(
    os.getenv("VISIT_MEDIA_BILL_MAX_BYTES", str(15 * 1024 * 1024))
)
VISIT_MEDIA_VIDEO_MAX_SECONDS = int(os.getenv("VISIT_MEDIA_VIDEO_MAX_SECONDS", "60"))

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
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
X_FRAME_OPTIONS = "DENY"
# Cap request body roughly above the largest visit media upload (video).
DATA_UPLOAD_MAX_MEMORY_SIZE = int(
    os.getenv("DATA_UPLOAD_MAX_MEMORY_SIZE", str(80 * 1024 * 1024))
)
FILE_UPLOAD_MAX_MEMORY_SIZE = int(
    os.getenv("FILE_UPLOAD_MAX_MEMORY_SIZE", str(10 * 1024 * 1024))
)
CORS_ALLOW_ALL_ORIGINS = env_bool("CORS_ALLOW_ALL_ORIGINS", not IS_PRODUCTION)
DEFAULT_CORS_ALLOWED_ORIGINS = [
    "http://localhost:5173",
]
CORS_ALLOWED_ORIGINS = env_origin_list(
    "CORS_ALLOWED_ORIGINS", DEFAULT_CORS_ALLOWED_ORIGINS, csrf=False
)
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
        "refresh": "30/minute",
        "password_change": "5/hour",
    },
}

# Relax login throttle under the test runner so suite logins are not 429'd.
if "test" in sys.argv:
    REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]["login"] = "1000/minute"
    REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]["anon"] = "1000/minute"
    REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]["user"] = "1000/minute"
    REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]["refresh"] = "1000/minute"
    REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]["password_change"] = "1000/minute"

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(hours=12),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": False,
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
# Render Postgres is obsolete for production. AWS EC2 uses local/private Postgres.
_BLOCKED_RENDER_DB_HOSTS = frozenset(
    {
        "dpg-d7ckj7dckfvc739s0frg-a",
        "dpg-d7ckj7dckfvc739s0frg-a.singapore-postgres.render.com",
        "dpg-d84t75d7vvec73fhlpfg-a",
        "dpg-d84t75d7vvec73fhlpfg-a.singapore-postgres.render.com",
    }
)


def _is_render_database_host(host: str) -> bool:
    host = (host or "").strip().lower()
    if not host:
        return False
    short = host.split(".")[0]
    if host in _BLOCKED_RENDER_DB_HOSTS or short in _BLOCKED_RENDER_DB_HOSTS:
        return True
    if host.endswith(".render.com") or "postgres.render.com" in host:
        return True
    if host.startswith("dpg-"):
        return True
    return False


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
        # Local / same-host Postgres: do not force SSL.
        # Remote private hosts: require SSL only when DB_SSL_REQUIRE=true (or default
        # true for non-local, non-Render hosts). Never force Render SSL on AWS.
        is_local = (
            db_host in {"localhost", "127.0.0.1", "::1"}
            or db_host.startswith("127.")
        )
        default_ssl_require = bool(db_host) and not is_local and not _is_render_database_host(
            db_host
        )
        if IS_PRODUCTION and not _is_render_env() and _is_render_database_host(db_host):
            raise RuntimeError(
                "DATABASE_URL points to Render Postgres "
                f"({db_host}). Production runs on AWS EC2 — set DATABASE_URL "
                "(or DB_HOST=127.0.0.1) to the AWS PostgreSQL instance in the "
                "EC2 .env / systemd EnvironmentFile. Do not use *.render.com."
            )
        databases = {
            "default": dj_database_url.parse(
                database_url,
                conn_max_age=600,
                ssl_require=env_bool("DB_SSL_REQUIRE", default_ssl_require if not is_local else False),
            )
        }
        databases["default"]["CONN_HEALTH_CHECKS"] = True
        if databases["default"].get("ENGINE") == "django.db.backends.postgresql":
            databases["default"].setdefault("OPTIONS", {})
            databases["default"]["OPTIONS"].setdefault("connect_timeout", 10)
            if is_local:
                # Ensure local EC2 Postgres is not stuck on sslmode=require from URL query.
                databases["default"]["OPTIONS"].setdefault("sslmode", "prefer")
                if not env_bool("DB_SSL_REQUIRE", False):
                    databases["default"]["OPTIONS"]["sslmode"] = "disable"
        return databases

    component_db = _database_from_components()
    if component_db:
        host = (component_db.get("HOST") or "").strip().lower()
        if IS_PRODUCTION and not _is_render_env() and _is_render_database_host(host):
            raise RuntimeError(
                "DB_HOST points to Render Postgres. Use the AWS EC2 PostgreSQL host "
                "(typically 127.0.0.1) instead."
            )
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


def _sanitize_pg_identifier(name: str) -> str:
    import re

    safe = re.sub(r"[^a-zA-Z0-9_]", "_", (name or "").strip())
    return safe[:63]


def _ci_test_database_name() -> str:
    explicit = _sanitize_pg_identifier(os.getenv("CI_TEST_DATABASE_NAME", ""))
    if explicit:
        return explicit
    run_id = os.getenv("GITHUB_RUN_ID", "").strip()
    run_attempt = os.getenv("GITHUB_RUN_ATTEMPT", "1").strip() or "1"
    if run_id:
        return _sanitize_pg_identifier(f"test_agri_test_{run_id}_{run_attempt}")
    return ""


def _configure_test_database() -> None:
    """Harden PostgreSQL settings for Django's test runner."""
    if "test" not in sys.argv:
        return

    for alias, db in DATABASES.items():
        db["CONN_MAX_AGE"] = 0
        db.pop("CONN_HEALTH_CHECKS", None)

    ci_test_name = _ci_test_database_name()
    if ci_test_name:
        if not ci_test_name.startswith("test_"):
            raise RuntimeError(
                f"CI test database name must start with test_: {ci_test_name!r}"
            )
        DATABASES["default"].setdefault("TEST", {})["NAME"] = ci_test_name

    if (
        os.getenv("CI", "").lower() in {"1", "true", "yes"}
        or os.getenv("GITHUB_ACTIONS", "").lower() in {"1", "true", "yes"}
        or ci_test_name
    ):
        globals()["TEST_RUNNER"] = "config.test_runner.CIPostgresTestRunner"


_configure_test_database()

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
_default_media_root = BASE_DIR / (".test_media" if "test" in sys.argv else "media")
MEDIA_ROOT = Path(os.getenv("MEDIA_ROOT", str(_default_media_root)))
# Profile photos: employee_photos/ and farmer_photos/ under MEDIA_ROOT.
# AWS EC2: set MEDIA_ROOT to a persistent path (e.g. /var/www/agri-backend/media)
# that survives git deploy. Do not use Render ephemeral disk.

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
CELERY_ENABLE_UTC = True
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 30 * 60  # 30 minutes hard limit
CELERY_TASK_SOFT_TIME_LIMIT = 25 * 60  # 25 minutes soft limit
CELERY_BEAT_SCHEDULE = {
    "expire-overdue-duties-every-5-minutes": {
        "task": "tracking.tasks.expire_overdue_duties_task",
        "schedule": timedelta(minutes=5),
    },
}
# When true, /readyz/ fails if broker is missing/memory-only (optional gate).
CELERY_REQUIRED_FOR_READY = os.getenv(
    "CELERY_REQUIRED_FOR_READY", "false"
).lower() in ("1", "true", "yes")

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

# Safe boot summary (no secrets). Runs after LOGGING is defined.
import logging as _logging

_logging.getLogger("agri_clinic").info(
    "Django boot APP_ENV=%s DEBUG=%s ALLOWED_HOSTS=%s",
    APP_ENV,
    DEBUG,
    ALLOWED_HOSTS,
)

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
