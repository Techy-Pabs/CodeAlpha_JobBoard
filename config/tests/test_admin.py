"""Every admin page loads, so a typo in list_display or search_fields fails here."""

import pytest
from django.contrib import admin
from django.urls import reverse

from applications.models import Application, ApplicationStatusChange

pytestmark = pytest.mark.django_db

MODELS = sorted(admin.site._registry, key=lambda m: m._meta.label)


@pytest.fixture
def admin_client_logged_in(client, django_user_model):
    root = django_user_model.objects.create_superuser("root", "root@example.com", "pw-12345!")
    client.force_login(root)
    return client


@pytest.mark.parametrize("model", MODELS, ids=lambda m: m._meta.label)
def test_changelist_and_search_load(admin_client_logged_in, model, job, resume):
    opts = model._meta
    url = reverse(f"admin:{opts.app_label}_{opts.model_name}_changelist")
    assert admin_client_logged_in.get(url).status_code == 200
    assert admin_client_logged_in.get(url, {"q": "acme"}).status_code == 200


# Third-party admins such as simplejwt's tokens deliberately disable "add".
LOCAL_APPS = {"accounts", "companies", "candidates", "jobs", "applications", "notifications"}
LOCAL_MODELS = [m for m in MODELS if m._meta.app_label in LOCAL_APPS]


@pytest.mark.parametrize("model", LOCAL_MODELS, ids=lambda m: m._meta.label)
def test_add_page_loads(admin_client_logged_in, model):
    opts = model._meta
    url = reverse(f"admin:{opts.app_label}_{opts.model_name}_add")
    assert admin_client_logged_in.get(url).status_code == 200


def test_application_page_shows_status_history(admin_client_logged_in, job, candidate, resume):
    app = Application.objects.create(job=job, candidate=candidate, resume=resume)
    ApplicationStatusChange.objects.create(
        application=app, from_status="submitted", to_status="shortlisted", note="Strong CV"
    )
    response = admin_client_logged_in.get(
        reverse("admin:applications_application_change", args=[app.pk])
    )
    assert response.status_code == 200
    assert b"Strong CV" in response.content


def test_admin_add_user_without_role_shows_form_error(admin_client_logged_in, django_user_model):
    response = admin_client_logged_in.post(
        reverse("admin:accounts_user_add"),
        {
            "username": "norole",
            "password1": "Tr1cky-Horse-Battery",
            "password2": "Tr1cky-Horse-Battery",
            "usable_password": "true",
        },
    )
    assert response.status_code == 200
    assert b"Choose a role" in response.content
    assert not django_user_model.objects.filter(username="norole").exists()


def test_admin_can_add_roleless_staff_user(admin_client_logged_in, django_user_model):
    response = admin_client_logged_in.post(
        reverse("admin:accounts_user_add"),
        {
            "username": "helper",
            "password1": "Tr1cky-Horse-Battery",
            "password2": "Tr1cky-Horse-Battery",
            "usable_password": "true",
            "is_staff": "on",
        },
    )
    assert response.status_code == 302
    assert django_user_model.objects.get(username="helper").role == ""
