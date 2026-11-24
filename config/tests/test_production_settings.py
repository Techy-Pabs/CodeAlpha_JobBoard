"""Production settings read from the environment, and how they behave."""

import json
import os
import runpy
import subprocess
import sys
from pathlib import Path

import pytest
from django.urls import reverse

BASE_DIR = Path(__file__).resolve().parents[2]

NEW_VARS = [
    "CSRF_TRUSTED_ORIGINS",
    "SECURE_SSL_REDIRECT",
    "SECURE_COOKIES",
    "NUM_PROXIES",
    "DATABASE_CONN_MAX_AGE",
    "R2_ACCOUNT_ID",
    "R2_ACCESS_KEY_ID",
    "R2_SECRET_ACCESS_KEY",
    "R2_BUCKET_NAME",
    "EMAIL_HOST",
    "EMAIL_PORT",
    "EMAIL_HOST_USER",
    "EMAIL_HOST_PASSWORD",
    "EMAIL_USE_TLS",
    "DEBUG",
]

SETTINGS_JSON = (
    "import json; from config import settings as s; "
    "db = s.DATABASES['default']; "
    "print(json.dumps({"
    "'csrf': s.CSRF_TRUSTED_ORIGINS, 'redirect': s.SECURE_SSL_REDIRECT, "
    "'exempt': s.SECURE_REDIRECT_EXEMPT, 'proxy': s.SECURE_PROXY_SSL_HEADER, "
    "'hsts': getattr(s, 'SECURE_HSTS_SECONDS', 0), "
    "'hsts_sub': getattr(s, 'SECURE_HSTS_INCLUDE_SUBDOMAINS', False), "
    "'preload': getattr(s, 'SECURE_HSTS_PRELOAD', False), "
    "'secure_cookies': getattr(s, 'SESSION_COOKIE_SECURE', False), "
    "'num_proxies': s.REST_FRAMEWORK['NUM_PROXIES'], "
    "'max_age': db['CONN_MAX_AGE'], 'health_checks': db['CONN_HEALTH_CHECKS'], "
    "'options': db.get('OPTIONS', {}), "
    "'storage': s.STORAGES['default'], 'static': s.STORAGES['staticfiles'], "
    "'email': s.EMAIL_BACKEND, 'email_port': getattr(s, 'EMAIL_PORT', None), "
    "'email_tls': getattr(s, 'EMAIL_USE_TLS', None), "
    "'middleware': s.MIDDLEWARE}))"
)


def run_settings(**overrides):
    """Import config.settings in a fresh process with the given env vars.

    Settings are read once at import time, so each case needs its own process.
    DEBUG defaults to False here, as in production.
    """
    env = {k: v for k, v in os.environ.items() if k not in NEW_VARS}
    env["DEBUG"] = "False"
    env.update(overrides)
    return subprocess.run(
        [sys.executable, "-c", SETTINGS_JSON], cwd=BASE_DIR, env=env, capture_output=True, text=True
    )


def load_settings(**overrides):
    result = run_settings(**overrides)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_local_defaults():
    s = load_settings()
    assert s["csrf"] == []
    assert s["redirect"] is False
    assert s["hsts"] == 0
    assert s["secure_cookies"] is False
    assert s["num_proxies"] is None
    assert s["max_age"] == 60
    assert s["health_checks"] is True
    assert s["proxy"] == ["HTTP_X_FORWARDED_PROTO", "https"]


def test_whitenoise_serves_static_files_right_after_security_middleware():
    s = load_settings()
    assert s["middleware"][:2] == [
        "django.middleware.security.SecurityMiddleware",
        "whitenoise.middleware.WhiteNoiseMiddleware",
    ]
    assert s["static"]["BACKEND"] == "whitenoise.storage.CompressedManifestStaticFilesStorage"


def test_empty_values_behave_like_unset():
    s = load_settings(CSRF_TRUSTED_ORIGINS="", NUM_PROXIES="", SECURE_SSL_REDIRECT="")
    assert s["csrf"] == []
    assert s["num_proxies"] is None
    assert s["redirect"] is False


def test_csrf_trusted_origins_is_a_list():
    s = load_settings(CSRF_TRUSTED_ORIGINS="https://a.onrender.com, https://b.example.com,")
    assert s["csrf"] == ["https://a.onrender.com", "https://b.example.com"]


@pytest.mark.parametrize(("value", "expected"), [("0", 0), ("1", 1), ("2", 2)])
def test_num_proxies(value, expected):
    assert load_settings(NUM_PROXIES=value)["num_proxies"] == expected


def test_ssl_redirect_turns_on_one_day_hsts_without_preload():
    s = load_settings(SECURE_SSL_REDIRECT="True")
    assert s["redirect"] is True
    assert s["hsts"] == 86400
    assert s["hsts_sub"] is False
    assert s["preload"] is False
    assert s["exempt"] == [r"^api/health/$"]


def test_secure_cookies():
    assert load_settings(SECURE_COOKIES="True")["secure_cookies"] is True


def test_neon_connection_string_keeps_ssl_options():
    url = (
        "postgresql://user:pw@ep-example-123.eu-central-1.aws.neon.tech/neondb"
        "?sslmode=require&channel_binding=require"
    )
    s = load_settings(DATABASE_URL=url, DATABASE_CONN_MAX_AGE="0")
    assert s["options"] == {"sslmode": "require", "channel_binding": "require"}
    assert s["max_age"] == 0


# --- File storage: local disk or Cloudflare R2 ---

R2_ENV = {
    "R2_ACCOUNT_ID": "0123456789abcdef0123456789abcdef",
    "R2_ACCESS_KEY_ID": "test-access-key-id",
    "R2_SECRET_ACCESS_KEY": "test-secret-access-key",
    "R2_BUCKET_NAME": "codealpha-jobboard",
}


def test_no_r2_vars_means_local_disk():
    assert load_settings()["storage"] == {"BACKEND": "django.core.files.storage.FileSystemStorage"}


def test_all_r2_vars_mean_private_r2_storage():
    storage = load_settings(**R2_ENV)["storage"]
    assert storage["BACKEND"] == "storages.backends.s3.S3Storage"
    options = storage["OPTIONS"]
    assert options["endpoint_url"] == (
        "https://0123456789abcdef0123456789abcdef.r2.cloudflarestorage.com"
    )
    assert options["bucket_name"] == "codealpha-jobboard"
    assert options["access_key"] == "test-access-key-id"
    assert options["secret_key"] == "test-secret-access-key"
    assert options["region_name"] == "auto"
    # Never public: no ACL is sent, URLs are signed, no public custom domain.
    assert options["default_acl"] is None
    assert options["querystring_auth"] is True
    assert options["custom_domain"] is None
    assert options["file_overwrite"] is False


@pytest.mark.parametrize("missing", list(R2_ENV))
def test_half_an_r2_configuration_is_an_error(missing):
    result = run_settings(**{**R2_ENV, missing: ""})
    assert result.returncode != 0
    assert "Set all four R2_* variables or none" in result.stderr
    assert missing in result.stderr
    # The error names variables, never their values.
    assert "test-secret-access-key" not in result.stderr


# --- Email ---


def test_email_is_printed_locally():
    assert load_settings(DEBUG="True")["email"] == "django.core.mail.backends.console.EmailBackend"


def test_email_is_logged_in_production_without_email_host():
    assert load_settings()["email"] == "config.email.LoggingEmailBackend"


def test_email_uses_smtp_when_email_host_is_set():
    s = load_settings(EMAIL_HOST="smtp.example.com", EMAIL_PORT="2525", EMAIL_USE_TLS="False")
    assert s["email"] == "django.core.mail.backends.smtp.EmailBackend"
    assert s["email_port"] == 2525
    assert s["email_tls"] is False


def test_smtp_defaults_to_port_587_with_tls():
    s = load_settings(EMAIL_HOST="smtp.example.com", DEBUG="True")
    assert s["email"] == "django.core.mail.backends.smtp.EmailBackend"
    assert s["email_port"] == 587
    assert s["email_tls"] is True


# --- HTTPS redirect behaviour (SecurityMiddleware reads settings per client) ---


@pytest.fixture
def https_on(settings):
    settings.SECURE_SSL_REDIRECT = True
    settings.SECURE_HSTS_SECONDS = 86400


@pytest.mark.django_db
def test_plain_http_is_redirected_to_https(https_on, api_client):
    response = api_client.get(reverse("job-list"))
    assert response.status_code == 301
    assert response["Location"].startswith("https://")


@pytest.mark.django_db
def test_health_check_is_not_redirected(https_on, api_client):
    response = api_client.get(reverse("health"))
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.django_db
def test_request_forwarded_as_https_is_served_with_hsts(https_on, api_client):
    response = api_client.get(reverse("job-list"), HTTP_X_FORWARDED_PROTO="https")
    assert response.status_code == 200
    assert response["Strict-Transport-Security"] == "max-age=86400"


# --- gunicorn.conf.py ---


def gunicorn_conf(monkeypatch, **env):
    for name in ("PORT", "WEB_CONCURRENCY"):
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    return runpy.run_path(str(BASE_DIR / "gunicorn.conf.py"))


def test_gunicorn_local_defaults(monkeypatch):
    conf = gunicorn_conf(monkeypatch)
    assert conf["bind"] == "0.0.0.0:8000"
    assert conf["workers"] == 2


def test_gunicorn_uses_render_port_and_web_concurrency(monkeypatch):
    conf = gunicorn_conf(monkeypatch, PORT="10000", WEB_CONCURRENCY="3")
    assert conf["bind"] == "0.0.0.0:10000"
    assert conf["workers"] == 3


@pytest.mark.parametrize("value", ["abc", "0", "-1"])
def test_gunicorn_rejects_bad_worker_count(monkeypatch, value):
    with pytest.raises(SystemExit, match="WEB_CONCURRENCY"):
        gunicorn_conf(monkeypatch, WEB_CONCURRENCY=value)
