"""Case-insensitive usernames, email normalisation and the JWT signing key."""

from unittest import mock

import jwt
import pytest
from django.conf import settings
from django.contrib.auth import authenticate, get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.urls import reverse
from rest_framework import serializers
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from accounts.serializers import RegisterSerializer

User = get_user_model()

REGISTER = reverse("accounts:register")
TOKEN = reverse("accounts:token")
ME = reverse("accounts:me")
PASSWORD = "Tr1cky-Horse-Battery"

pytestmark = pytest.mark.django_db


@pytest.fixture
def alice():
    return User.objects.create_user(
        username="Alice", email="alice@example.com", password=PASSWORD, role="candidate"
    )


# --- usernames ----------------------------------------------------------------


def test_register_username_differing_only_in_case_returns_400(api_client, alice):
    response = api_client.post(
        REGISTER,
        {
            "username": "aLiCe",
            "email": "other@example.com",
            "password": PASSWORD,
            "role": "candidate",
        },
        format="json",
    )
    assert response.status_code == 400
    assert response.data["username"] == ["A user with that username already exists."]
    assert User.objects.count() == 1


def test_register_keeps_username_as_typed(api_client):
    response = api_client.post(
        REGISTER,
        {
            "username": "BobSmith",
            "email": "bob@example.com",
            "password": PASSWORD,
            "role": "candidate",
        },
        format="json",
    )
    assert response.status_code == 201
    assert response.data["username"] == "BobSmith"


def test_db_rejects_case_insensitive_duplicate_username(alice):
    """Holds even when code bypasses the serializer (shell, scripts)."""
    with (
        pytest.raises(IntegrityError, match="user_username_ci_unique"),
        transaction.atomic(),
    ):
        User.objects.create_user(
            username="ALICE", email="a2@example.com", password=PASSWORD, role="candidate"
        )


def test_model_validation_reports_duplicate_username(alice):
    """The admin form runs this check, so it shows a form error, not a 500."""
    with pytest.raises(ValidationError, match="already exists"):
        User(username="alice", email="x@example.com", role="candidate").validate_constraints()


def test_register_race_on_username_returns_400_not_500(alice):
    """Two sign-ups pass validation together; the DB constraint catches one."""
    serializer = RegisterSerializer(
        data={
            "username": "ALICE",
            "email": "new@example.com",
            "password": PASSWORD,
            "role": "candidate",
        }
    )
    # Simulate losing the race: skip the pre-check, so the insert hits the DB.
    with mock.patch.object(RegisterSerializer, "validate_username", lambda self, v: v):
        assert serializer.is_valid(), serializer.errors
        with pytest.raises(serializers.ValidationError) as exc_info:
            serializer.save()
    assert exc_info.value.detail == {"username": ["A user with that username already exists."]}


# --- login --------------------------------------------------------------------


@pytest.mark.parametrize("typed", ["Alice", "alice", "ALICE"])
def test_login_ignores_username_case(api_client, alice, typed):
    response = api_client.post(
        TOKEN, {"username": typed, "password": PASSWORD, "role": "candidate"}, format="json"
    )
    assert response.status_code == 200
    assert "access" in response.data


def test_login_wrong_password_still_fails_with_other_case(api_client, alice):
    response = api_client.post(TOKEN, {"username": "alice", "password": "nope-nope"}, format="json")
    assert response.status_code == 401


def test_backend_rejects_unknown_and_inactive_users(alice):
    assert authenticate(username="nobody", password=PASSWORD) is None
    alice.is_active = False
    alice.save()
    assert authenticate(username="alice", password=PASSWORD) is None


# --- email normalisation ------------------------------------------------------


def test_save_lowercases_and_trims_email():
    user = User(username="carol", email="  Carol@Example.COM ", role="candidate")
    user.set_password(PASSWORD)
    user.save()
    user.refresh_from_db()
    assert user.email == "carol@example.com"


def test_save_normalises_email_on_update(alice):
    alice.email = " ALICE.New@Example.com"
    alice.save()
    alice.refresh_from_db()
    assert alice.email == "alice.new@example.com"


def test_create_superuser_normalises_email():
    admin = User.objects.create_superuser("root", " Root@Example.COM", PASSWORD)
    assert admin.email == "root@example.com"


# --- JWT signing key ----------------------------------------------------------


def test_jwt_signing_key_is_separate_from_secret_key():
    assert settings.JWT_SIGNING_KEY
    assert settings.SIMPLE_JWT["SIGNING_KEY"] == settings.JWT_SIGNING_KEY
    assert settings.JWT_SIGNING_KEY != settings.SECRET_KEY


def test_issued_token_is_signed_with_jwt_signing_key(api_client, alice):
    access = api_client.post(
        TOKEN, {"username": "Alice", "password": PASSWORD, "role": "candidate"}, format="json"
    ).data["access"]
    payload = jwt.decode(access, settings.JWT_SIGNING_KEY, algorithms=["HS256"])
    assert payload["user_id"] == str(alice.pk)
    with pytest.raises(jwt.InvalidSignatureError):
        jwt.decode(access, settings.SECRET_KEY, algorithms=["HS256"])


def test_token_signed_with_secret_key_is_rejected(alice):
    """A token forged with the old key (SECRET_KEY) no longer works."""
    payload = dict(AccessToken.for_user(alice).payload)
    forged = jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {forged}")
    assert client.get(ME).status_code == 401
