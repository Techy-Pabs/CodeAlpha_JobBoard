"""
Django settings for the CodeAlpha Job Board.

Everything secret or machine-specific comes from environment variables, read
from .env via django-environ (see .env.example).
"""

from datetime import timedelta
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DEBUG=(bool, False),
    ALLOWED_HOSTS=(list, []),
    DATABASE_CONN_MAX_AGE=(int, 60),
)
# Read key=value pairs from .env into the environment (real env vars win).
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("SECRET_KEY")
# Separate key for signing JWTs, so rotating it logs every API user out
# without touching sessions, password reset links or other SECRET_KEY uses.
JWT_SIGNING_KEY = env("JWT_SIGNING_KEY")
DEBUG = env("DEBUG")
ALLOWED_HOSTS = env("ALLOWED_HOSTS")


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


# Database (PostgreSQL from docker-compose.yml locally)

DATABASES = {
    "default": env.db("DATABASE_URL"),
}
DATABASES["default"]["CONN_MAX_AGE"] = env("DATABASE_CONN_MAX_AGE")
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
STATIC_ROOT = BASE_DIR / "staticfiles"
# Uploaded files (resumes). Kept out of git by .gitignore.
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# Email (notifications). Locally every email is printed to the console
# instead of being sent. Tests swap in Django's in-memory backend.
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
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
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = "DENY"
