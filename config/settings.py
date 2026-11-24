"""
Django settings for the CodeAlpha Job Board.

Everything secret or machine-specific comes from environment variables, read
from .env via django-environ (see .env.example).
"""

from datetime import timedelta
from pathlib import Path

import environ
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DEBUG=(bool, False),
    ALLOWED_HOSTS=(list, []),
    SECURE_COOKIES=(bool, False),
    SECURE_SSL_REDIRECT=(bool, False),
    DATABASE_CONN_MAX_AGE=(int, 60),
    EMAIL_PORT=(int, 587),
    EMAIL_USE_TLS=(bool, True),
)
# Read key=value pairs from .env into the environment (real env vars win).
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("SECRET_KEY")
# Separate key for signing JWTs, so rotating it logs every API user out
# without touching sessions, password reset links or other SECRET_KEY uses.
JWT_SIGNING_KEY = env("JWT_SIGNING_KEY")
DEBUG = env("DEBUG")
ALLOWED_HOSTS = env("ALLOWED_HOSTS")


def env_list(name):
    """Comma-separated env var as a list, ignoring spaces and empty items."""
    return [item.strip() for item in env.str(name, default="").split(",") if item.strip()]


# Full origins (scheme + host) allowed to send POST forms, such as the admin
# login, e.g. https://your-app.onrender.com. Django checks this on HTTPS.
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS")

# Render's proxy terminates HTTPS and forwards plain HTTP, adding
# X-Forwarded-Proto: https. This tells Django to trust that header, so
# request.is_secure() is right and the HTTPS redirect doesn't loop.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# Redirect every HTTP request to HTTPS. Off by default for local use.
SECURE_SSL_REDIRECT = env("SECURE_SSL_REDIRECT")
# Render's health check calls the container directly over plain HTTP, so
# the health endpoint must answer instead of redirecting.
SECURE_REDIRECT_EXEMPT = [r"^api/health/$"]
if SECURE_SSL_REDIRECT:
    # Tell browsers to use HTTPS only for this host. One day to start, so a
    # mistake wears off quickly. No subdomains and no preload list.
    SECURE_HSTS_SECONDS = 60 * 60 * 24
    SECURE_HSTS_INCLUDE_SUBDOMAINS = False
    SECURE_HSTS_PRELOAD = False


# Application definition

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Full-text search lookups (SearchVector, SearchQuery) for job search.
    "django.contrib.postgres",
    # Third-party
    "rest_framework",
    "rest_framework_simplejwt.token_blacklist",
    "drf_spectacular",
    # Local apps
    "accounts",
    "companies",
    "candidates",
    "jobs",
    "applications",
    "notifications",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # Serves collected static files (admin CSS/JS) straight from gunicorn.
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"


# Database (PostgreSQL from docker-compose.yml locally, Neon in production)

# Works with Neon's connection string as given: query options such as
# sslmode=require and channel_binding=require are passed to the driver.
DATABASES = {
    "default": env.db("DATABASE_URL"),
}
# Reuse a connection for up to this many seconds instead of reconnecting on
# every request (a TLS handshake to Neon costs noticeable time). 0 closes
# it after each request.
DATABASES["default"]["CONN_MAX_AGE"] = env("DATABASE_CONN_MAX_AGE")
# Check a reused connection before using it. Neon closes idle connections
# when it pauses the database, and this replaces them instead of failing.
DATABASES["default"]["CONN_HEALTH_CHECKS"] = True


# Custom user model. Must be set before the first migration.
AUTH_USER_MODEL = "accounts.User"

# Username lookup at login ignores letter case.
AUTHENTICATION_BACKENDS = ["accounts.backends.CaseInsensitiveModelBackend"]


# Password validation

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]


# Internationalization

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True


# Static and uploaded files

STATIC_URL = "static/"
# collectstatic copies every app's static files here; WhiteNoise serves them.
STATIC_ROOT = BASE_DIR / "staticfiles"
# Uploaded files (resumes) when R2 isn't configured. Kept out of git by
# .gitignore, and never served at a public URL (see config/urls.py).
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

# Resumes go to Cloudflare R2 when all four R2_* variables are set, and to
# MEDIA_ROOT on local disk when none are. Half a configuration is an error,
# so a typo on the host can't silently fall back to the container's disk
# (which Render wipes on every deploy).
R2_VARS = ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET_NAME")
_r2 = {name: env.str(name, default="").strip() for name in R2_VARS}
if any(_r2.values()) and not all(_r2.values()):
    _missing = ", ".join(name for name, value in _r2.items() if not value)
    raise ImproperlyConfigured(f"Set all four R2_* variables or none. Missing: {_missing}.")
USE_R2 = all(_r2.values())

if USE_R2:
    _default_storage = {
        "BACKEND": "storages.backends.s3.S3Storage",
        "OPTIONS": {
            "endpoint_url": f"https://{_r2['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
            "access_key": _r2["R2_ACCESS_KEY_ID"],
            "secret_key": _r2["R2_SECRET_ACCESS_KEY"],
            "bucket_name": _r2["R2_BUCKET_NAME"],
            "region_name": "auto",  # R2 has no regions; "auto" is what it expects
            "signature_version": "s3v4",
            # Private objects: no ACL is ever sent, so each object stays as
            # private as the bucket (R2 buckets are private unless you turn
            # on public access, which this project never does).
            "default_acl": None,
            # Any URL the storage builds is signed and expires. The API
            # never hands one out: downloads go through the permission check.
            "querystring_auth": True,
            "querystring_expire": 300,
            "custom_domain": None,
            # Names are random already; never replace an existing object.
            "file_overwrite": False,
        },
    }
else:
    _default_storage = {"BACKEND": "django.core.files.storage.FileSystemStorage"}

STORAGES = {
    "default": _default_storage,
    # Adds a content hash to each file name and pre-compresses it, so
    # browsers can cache files forever and still get new versions.
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# Email (notifications). Tests always use Django's in-memory backend.
#   EMAIL_HOST set: sent over SMTP.
#   No EMAIL_HOST, DEBUG on (local): printed to the console.
#   No EMAIL_HOST, DEBUG off (production without a mail server): written to
#   the log instead, so nothing fails and you can still see what was sent.
EMAIL_HOST = env.str("EMAIL_HOST", default="").strip()
if EMAIL_HOST:
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    EMAIL_PORT = env("EMAIL_PORT")
    EMAIL_HOST_USER = env.str("EMAIL_HOST_USER", default="")
    EMAIL_HOST_PASSWORD = env.str("EMAIL_HOST_PASSWORD", default="")
    EMAIL_USE_TLS = env("EMAIL_USE_TLS")
    # Give up on a slow mail server instead of holding a worker for minutes.
    EMAIL_TIMEOUT = 10
elif DEBUG:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
else:
    EMAIL_BACKEND = "config.email.LoggingEmailBackend"
DEFAULT_FROM_EMAIL = env.str("DEFAULT_FROM_EMAIL", default="Job Board <noreply@jobboard.local>")

# Errors from code that must not fail a request (such as a failed
# notification email) are logged to the console, where Docker collects them.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "WARNING"},
    "loggers": {
        "notifications": {"level": "INFO"},
        "config.email": {"level": "INFO"},
    },
}


# Proxies in front of the app, for finding the client's IP when throttling.
# Unset (or empty) keeps DRF's default; 0 means "ignore X-Forwarded-For".
_num_proxies = env.str("NUM_PROXIES", default="").strip()
NUM_PROXIES = int(_num_proxies) if _num_proxies else None
if NUM_PROXIES is not None and NUM_PROXIES < 0:
    raise ValueError("NUM_PROXIES must be 0 or more.")

# Django REST Framework
# Every endpoint needs a valid JWT unless the view opts out explicitly
# (permission_classes = [AllowAny]).
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    # Only views that set throttle_scope are throttled.
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.ScopedRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "register": "5/minute",
        "login": "5/minute",
    },
    "NUM_PROXIES": NUM_PROXIES,
}


# Simple JWT
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=15),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "SIGNING_KEY": JWT_SIGNING_KEY,
}


# drf-spectacular (OpenAPI schema + Swagger UI)
SPECTACULAR_SETTINGS = {
    "TITLE": "CodeAlpha Job Board API",
    "DESCRIPTION": "Employers post jobs, candidates apply. Log in at /api/auth/token/, "
    "then click Authorize and paste the access token.",
    "VERSION": "0.1.0",
    "SERVE_INCLUDE_SCHEMA": False,
    # The schema and Swagger UI are public: no login, and a stale
    # Authorization header can't make them fail.
    "SERVE_PERMISSIONS": ["rest_framework.permissions.AllowAny"],
    "SERVE_AUTHENTICATION": [],
    "SWAGGER_UI_SETTINGS": {"persistAuthorization": True},
    # Separate request and response schemas: request bodies leave out
    # read-only fields, and file fields show as an upload button in Swagger.
    "COMPONENT_SPLIT_REQUEST": True,
    # Jobs and applications both have a "status" field: name each enum.
    "ENUM_NAME_OVERRIDES": {
        "JobStatusEnum": "jobs.models.JobStatus",
        "ApplicationStatusEnum": "applications.models.ApplicationStatus",
    },
}


# Production hardening (only when DEBUG is off)
if not DEBUG:
    # Browsers must trust the declared Content-Type, not guess it.
    SECURE_CONTENT_TYPE_NOSNIFF = True
    # No page of this site may be shown inside a frame (clickjacking).
    X_FRAME_OPTIONS = "DENY"
    # Cookies only over HTTPS. Off by default so the admin login still works
    # over plain HTTP locally (e.g. the Docker setup on localhost:8003).
    # Set SECURE_COOKIES=True once the site is served over HTTPS.
    SESSION_COOKIE_SECURE = env("SECURE_COOKIES")
    CSRF_COOKIE_SECURE = env("SECURE_COOKIES")
