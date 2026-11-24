import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.urls import reverse

User = get_user_model()

REGISTER = reverse("accounts:register")
TOKEN = reverse("accounts:token")
REFRESH = reverse("accounts:token-refresh")
LOGOUT = reverse("accounts:logout")
ME = reverse("accounts:me")

PASSWORD = "Tr1cky-Horse-Battery"

pytestmark = pytest.mark.django_db


@pytest.fixture
def user():
    return User.objects.create_user(
        username="alice", email="alice@example.com", password=PASSWORD, role="candidate"
    )


def login(client, username="alice", password=PASSWORD):
    return client.post(TOKEN, {"username": username, "password": password}, format="json")


@pytest.fixture
def tokens(api_client, user):
    response = login(api_client)
    assert response.status_code == 200
    return response.data


def auth(client, access):
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")


# --- register -------------------------------------------------------------


def test_register_success(api_client):
    response = api_client.post(
        REGISTER,
        {
            "username": "bob",
            "email": "  Bob@Example.COM ",
            "password": PASSWORD,
            "role": "candidate",
        },
        format="json",
    )
    assert response.status_code == 201
    assert set(response.data) == {"id", "username", "email", "role"}
    assert response.data["email"] == "bob@example.com"
    assert response.data["role"] == "candidate"
    created = User.objects.get(username="bob")
    assert created.email == "bob@example.com"
    assert created.password != PASSWORD
    assert created.check_password(PASSWORD)


def test_register_requires_email(api_client):
    response = api_client.post(
        REGISTER, {"username": "bob", "password": PASSWORD, "role": "candidate"}, format="json"
    )
    assert response.status_code == 400
    assert "email" in response.data


def test_register_duplicate_username(api_client, user):
    response = api_client.post(
        REGISTER,
        {
            "username": "alice",
            "email": "other@example.com",
            "password": PASSWORD,
            "role": "candidate",
        },
        format="json",
    )
    assert response.status_code == 400
    assert "username" in response.data


def test_register_duplicate_email_different_case(api_client, user):
    response = api_client.post(
        REGISTER,
        {
            "username": "alice2",
            "email": "ALICE@Example.com",
            "password": PASSWORD,
            "role": "candidate",
        },
        format="json",
    )
    assert response.status_code == 400
    assert "email" in response.data
    assert User.objects.count() == 1


def test_register_weak_password_rejected(api_client):
    response = api_client.post(
        REGISTER,
        {
            "username": "bob",
            "email": "bob@example.com",
            "password": "12345678",
            "role": "candidate",
        },
        format="json",
    )
    assert response.status_code == 400
    assert "password" in response.data
    assert not User.objects.filter(username="bob").exists()


def test_register_as_employer(api_client):
    response = api_client.post(
        REGISTER,
        {"username": "acme", "email": "hr@acme.example", "password": PASSWORD, "role": "employer"},
        format="json",
    )
    assert response.status_code == 201
    assert response.data["role"] == "employer"
    assert User.objects.get(username="acme").role == "employer"


def test_register_requires_role(api_client):
    response = api_client.post(
        REGISTER,
        {"username": "bob", "email": "bob@example.com", "password": PASSWORD},
        format="json",
    )
    assert response.status_code == 400
    assert "role" in response.data
    assert not User.objects.filter(username="bob").exists()


@pytest.mark.parametrize("role", ["", "admin", "Employer"])
def test_register_rejects_invalid_role(api_client, role):
    response = api_client.post(
        REGISTER,
        {"username": "bob", "email": "bob@example.com", "password": PASSWORD, "role": role},
        format="json",
    )
    assert response.status_code == 400
    assert "role" in response.data
    assert not User.objects.filter(username="bob").exists()


def test_register_cannot_make_staff(api_client):
    """is_staff and is_superuser in the request body are ignored."""
    response = api_client.post(
        REGISTER,
        {
            "username": "bob",
            "email": "bob@example.com",
            "password": PASSWORD,
            "role": "candidate",
            "is_staff": True,
            "is_superuser": True,
        },
        format="json",
    )
    assert response.status_code == 201
    bob = User.objects.get(username="bob")
    assert not bob.is_staff and not bob.is_superuser


def test_db_rejects_case_insensitive_duplicate_email(user):
    """The rule holds even when code bypasses the serializer."""
    with pytest.raises(IntegrityError), transaction.atomic():
        User.objects.create_user(
            username="x", email="ALICE@example.com", password=PASSWORD, role="candidate"
        )


def test_db_allows_several_blank_emails():
    User.objects.create_user(username="a", password=PASSWORD, role="candidate")
    User.objects.create_user(username="b", password=PASSWORD, role="candidate")
    assert User.objects.filter(email="").count() == 2


# --- login / tokens -------------------------------------------------------


def test_login_returns_both_tokens(api_client, user):
    response = login(api_client)
    assert response.status_code == 200
    assert {"access", "refresh"} <= set(response.data)


def test_login_wrong_password_returns_401(api_client, user):
    response = login(api_client, password="wrong-password")
    assert response.status_code == 401
    assert "access" not in response.data


def test_refresh_returns_new_tokens(api_client, tokens):
    response = api_client.post(REFRESH, {"refresh": tokens["refresh"]}, format="json")
    assert response.status_code == 200
    assert "access" in response.data
    # ROTATE_REFRESH_TOKENS: a new refresh token comes back too.
    assert response.data["refresh"] != tokens["refresh"]


def test_refresh_token_cannot_be_reused_after_rotation(api_client, tokens):
    first = api_client.post(REFRESH, {"refresh": tokens["refresh"]}, format="json")
    assert first.status_code == 200
    again = api_client.post(REFRESH, {"refresh": tokens["refresh"]}, format="json")
    assert again.status_code == 401


# --- me ---------------------------------------------------------------------


def test_me_without_token_returns_401(api_client):
    assert api_client.get(ME).status_code == 401


def test_me_with_token_returns_user_without_password(api_client, user, tokens):
    auth(api_client, tokens["access"])
    response = api_client.get(ME)
    assert response.status_code == 200
    assert response.data == {
        "id": user.id,
        "username": "alice",
        "email": "alice@example.com",
        "role": "candidate",
    }
    assert "password" not in response.data


# --- logout -----------------------------------------------------------------


def test_logout_blacklists_refresh_token(api_client, tokens):
    auth(api_client, tokens["access"])
    response = api_client.post(LOGOUT, {"refresh": tokens["refresh"]}, format="json")
    assert response.status_code == 205
    reuse = api_client.post(REFRESH, {"refresh": tokens["refresh"]}, format="json")
    assert reuse.status_code == 401


def test_logout_invalid_token_returns_400(api_client, tokens):
    auth(api_client, tokens["access"])
    response = api_client.post(LOGOUT, {"refresh": "not-a-token"}, format="json")
    assert response.status_code == 400


def test_logout_twice_returns_400(api_client, tokens):
    auth(api_client, tokens["access"])
    assert api_client.post(LOGOUT, {"refresh": tokens["refresh"]}, format="json").status_code == 205
    assert api_client.post(LOGOUT, {"refresh": tokens["refresh"]}, format="json").status_code == 400


def test_logout_requires_login(api_client, tokens):
    response = api_client.post(LOGOUT, {"refresh": tokens["refresh"]}, format="json")
    assert response.status_code == 401


def test_logout_rejects_another_users_token(api_client, tokens):
    User.objects.create_user(
        username="mallory", email="m@example.com", password=PASSWORD, role="candidate"
    )
    mallory = login(api_client, username="mallory").data
    auth(api_client, mallory["access"])
    response = api_client.post(LOGOUT, {"refresh": tokens["refresh"]}, format="json")
    assert response.status_code == 400


# --- throttling ---------------------------------------------------------------


def test_login_throttled_on_sixth_attempt(api_client, user):
    for _ in range(5):
        assert login(api_client, password="wrong-password").status_code == 401
    assert login(api_client).status_code == 429


def test_register_throttled_on_sixth_attempt(api_client):
    for i in range(5):
        response = api_client.post(
            REGISTER,
            {
                "username": f"u{i}",
                "email": f"u{i}@example.com",
                "password": PASSWORD,
                "role": "candidate",
            },
            format="json",
        )
        assert response.status_code == 201
    response = api_client.post(
        REGISTER,
        {"username": "u5", "email": "u5@example.com", "password": PASSWORD, "role": "candidate"},
        format="json",
    )
    assert response.status_code == 429
