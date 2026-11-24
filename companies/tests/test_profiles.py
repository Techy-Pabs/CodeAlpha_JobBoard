"""The right profile is created for each role, at register and elsewhere."""

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.urls import reverse

from candidates.models import CandidateProfile
from companies.models import EmployerProfile
from conftest import PASSWORD

User = get_user_model()

REGISTER = reverse("accounts:register")
TOKEN = reverse("accounts:token")

pytestmark = pytest.mark.django_db


def register(client, username, role):
    return client.post(
        REGISTER,
        {
            "username": username,
            "email": f"{username}@example.com",
            "password": PASSWORD,
            "role": role,
        },
        format="json",
    )


def test_register_employer_creates_employer_profile_only(api_client):
    assert register(api_client, "acme", "employer").status_code == 201
    user = User.objects.get(username="acme")
    assert EmployerProfile.objects.filter(user=user).exists()
    assert not CandidateProfile.objects.filter(user=user).exists()


def test_register_candidate_creates_candidate_profile_only(api_client):
    assert register(api_client, "ada", "candidate").status_code == 201
    user = User.objects.get(username="ada")
    assert CandidateProfile.objects.filter(user=user).exists()
    assert not EmployerProfile.objects.filter(user=user).exists()


def test_failed_register_creates_no_profile(api_client):
    """A rejected sign-up leaves neither a user nor a stray profile behind."""
    response = api_client.post(
        REGISTER,
        {"username": "ada", "email": "ada@example.com", "password": "123", "role": "candidate"},
        format="json",
    )
    assert response.status_code == 400
    assert not User.objects.exists()
    assert not CandidateProfile.objects.exists()


def test_user_created_outside_the_api_also_gets_a_profile():
    """The admin and the shell go through the same post_save signal."""
    user = User.objects.create_user(username="shell", password=PASSWORD, role="employer")
    assert EmployerProfile.objects.filter(user=user).count() == 1


def test_superuser_gets_no_profile():
    User.objects.create_superuser("root", "root@example.com", PASSWORD)
    assert not EmployerProfile.objects.exists()
    assert not CandidateProfile.objects.exists()


def test_login_does_not_create_a_second_profile(api_client, employer_user):
    response = api_client.post(TOKEN, {"username": "acme", "password": PASSWORD}, format="json")
    assert response.status_code == 200
    employer_user.save()
    assert EmployerProfile.objects.filter(user=employer_user).count() == 1


def test_db_allows_only_one_employer_profile_per_user(employer_user):
    with pytest.raises(IntegrityError), transaction.atomic():
        EmployerProfile.objects.create(user=employer_user, company_name="Second Co")


def test_employer_profile_rejects_candidate_user(candidate_user):
    with pytest.raises(ValidationError, match="Only employer accounts"):
        EmployerProfile(user=candidate_user, company_name="X").full_clean()


def test_candidate_profile_rejects_employer_user(employer_user):
    with pytest.raises(ValidationError, match="Only candidate accounts"):
        CandidateProfile(user=employer_user).full_clean()
