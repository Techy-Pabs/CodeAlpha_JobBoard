from io import StringIO

import pytest
from django.contrib.auth import authenticate, get_user_model
from django.core.management import CommandError, call_command

User = get_user_model()

pytestmark = pytest.mark.django_db

PASSWORD = "Strong-Admin-Pass-For-Tests-9"
VARS = ("DJANGO_SUPERUSER_USERNAME", "DJANGO_SUPERUSER_EMAIL", "DJANGO_SUPERUSER_PASSWORD")


@pytest.fixture
def admin_env(monkeypatch):
    monkeypatch.setenv("DJANGO_SUPERUSER_USERNAME", "site_admin")
    monkeypatch.setenv("DJANGO_SUPERUSER_EMAIL", "Admin@Example.com")
    monkeypatch.setenv("DJANGO_SUPERUSER_PASSWORD", PASSWORD)


def run():
    out = StringIO()
    call_command("ensure_superuser", stdout=out)
    return out.getvalue()


def test_creates_superuser(admin_env):
    output = run()
    assert "Created admin account 'site_admin'" in output
    assert PASSWORD not in output
    user = User.objects.get(username="site_admin")
    assert user.is_superuser and user.is_staff and user.is_active
    assert user.email == "admin@example.com"
    assert authenticate(username="site_admin", password=PASSWORD) == user


def test_second_run_leaves_existing_user_alone(admin_env, monkeypatch):
    run()
    monkeypatch.setenv("DJANGO_SUPERUSER_PASSWORD", "A-Different-Pass-77")
    output = run()
    assert "already exists; left unchanged" in output
    assert User.objects.count() == 1
    # The password isn't reset on restart (it may have been changed in the admin).
    assert authenticate(username="site_admin", password=PASSWORD) is not None


def test_existing_username_matches_ignoring_case(admin_env):
    User.objects.create_user("Site_Admin", "other@example.com", "pw-12345!", role="candidate")
    assert "left unchanged" in run()
    assert User.objects.count() == 1


def test_skips_when_nothing_is_set(monkeypatch):
    for name in VARS:
        monkeypatch.delenv(name, raising=False)
    assert "skipping" in run()
    assert not User.objects.exists()


@pytest.mark.parametrize("missing", VARS)
def test_partial_configuration_is_an_error(admin_env, monkeypatch, missing):
    monkeypatch.setenv(missing, "")
    with pytest.raises(CommandError, match=missing) as exc:
        run()
    assert PASSWORD not in str(exc.value)
    assert not User.objects.exists()


def test_weak_password_is_rejected_without_echoing_it(admin_env, monkeypatch):
    monkeypatch.setenv("DJANGO_SUPERUSER_PASSWORD", "password1")
    with pytest.raises(CommandError, match="rejected") as exc:
        run()
    assert "password1" not in str(exc.value)
    assert not User.objects.exists()


def test_invalid_email_is_rejected(admin_env, monkeypatch):
    monkeypatch.setenv("DJANGO_SUPERUSER_EMAIL", "not-an-email")
    with pytest.raises(CommandError, match="valid email"):
        run()


def test_email_used_by_another_user_is_rejected(admin_env):
    User.objects.create_user("someone_else", "admin@example.com", "pw-12345!", role="employer")
    with pytest.raises(CommandError, match="another user"):
        run()
    assert not User.objects.filter(username="site_admin").exists()


def test_superuser_needs_no_role(admin_env):
    """Staff accounts may have no role (the user_role_required_unless_staff check)."""
    run()
    assert User.objects.get(username="site_admin").role == ""
