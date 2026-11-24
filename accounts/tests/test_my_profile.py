"""GET and PATCH /api/me/profile/: the right profile for each role."""

import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db

URL = reverse("my-profile")
REQUIRED = "This field is required to complete your profile."


@pytest.fixture
def as_employer(api_client, employer_user):
    api_client.force_authenticate(employer_user)
    return api_client


@pytest.fixture
def as_candidate(api_client, candidate_user):
    api_client.force_authenticate(candidate_user)
    return api_client


def test_requires_login(api_client):
    assert api_client.get(URL).status_code == 401
    assert api_client.patch(URL, {}, format="json").status_code == 401


def test_employer_gets_company_profile(as_employer, employer_user):
    response = as_employer.get(URL)
    assert response.status_code == 200
    assert response.data["role"] == "employer"
    assert response.data["id"] == employer_user.employer_profile.id
    assert "company_name" in response.data and "headline" not in response.data
    assert response.data["is_complete"] is False


def test_candidate_gets_candidate_profile(as_candidate, candidate):
    response = as_candidate.get(URL)
    assert response.status_code == 200
    assert response.data["role"] == "candidate"
    assert response.data["id"] == candidate.id
    assert "headline" in response.data and "company_name" not in response.data


def test_staff_without_role_gets_403(api_client, django_user_model):
    admin = django_user_model.objects.create_superuser(username="root", password="x-12345!")
    api_client.force_authenticate(admin)
    assert api_client.get(URL).status_code == 403
    assert api_client.patch(URL, {"headline": "x"}, format="json").status_code == 403


def test_put_is_not_allowed(as_employer):
    assert as_employer.put(URL, {}, format="json").status_code == 405


# --- employer PATCH ---------------------------------------------------------


def test_employer_fills_whole_profile(as_employer, employer_user):
    data = {
        "company_name": "Acme Ltd",
        "location": "Lagos",
        "description": "Logistics software.",
        "website": "https://acme.example",
    }
    response = as_employer.patch(URL, data, format="json")
    assert response.status_code == 200, response.data
    assert response.data["is_complete"] is True
    profile = employer_user.employer_profile
    profile.refresh_from_db()
    assert profile.company_name == "Acme Ltd" and profile.website == "https://acme.example"


def test_employer_partial_patch_must_end_complete(as_employer):
    response = as_employer.patch(URL, {"company_name": "Acme Ltd"}, format="json")
    assert response.status_code == 400
    assert response.data["location"] == [REQUIRED]
    assert response.data["description"] == [REQUIRED]
    assert "company_name" not in response.data


def test_employer_partial_patch_uses_stored_values(as_employer, employer):
    # employer fixture already has all three fields; changing one is fine.
    response = as_employer.patch(URL, {"location": "Abuja"}, format="json")
    assert response.status_code == 200
    assert response.data["location"] == "Abuja"


def test_employer_cannot_blank_a_required_field(as_employer, employer):
    response = as_employer.patch(URL, {"description": "   "}, format="json")
    assert response.status_code == 400
    assert response.data["description"] == [REQUIRED]
    employer.refresh_from_db()
    assert employer.description == "We build logistics software."


def test_employer_website_is_validated(as_employer, employer):
    response = as_employer.patch(URL, {"website": "not a url"}, format="json")
    assert response.status_code == 400
    assert "website" in response.data


# --- candidate PATCH --------------------------------------------------------


def test_candidate_fills_profile(as_candidate, candidate):
    data = {"headline": "Backend developer", "location": "Lagos", "skills": "Python, Django"}
    response = as_candidate.patch(URL, data, format="json")
    assert response.status_code == 200, response.data
    assert response.data["is_complete"] is True
    candidate.refresh_from_db()
    assert candidate.skills == "Python, Django"


def test_candidate_needs_headline_and_location(as_candidate):
    response = as_candidate.patch(URL, {"skills": "SQL"}, format="json")
    assert response.status_code == 400
    assert response.data["headline"] == [REQUIRED]
    assert response.data["location"] == [REQUIRED]


def test_candidate_cannot_set_employer_fields(as_candidate, candidate):
    data = {"headline": "Dev", "location": "Lagos", "company_name": "Sneaky Ltd"}
    response = as_candidate.patch(URL, data, format="json")
    assert response.status_code == 200
    assert "company_name" not in response.data


# --- the role is fixed ------------------------------------------------------


@pytest.mark.parametrize("new_role", ["employer", "candidate", ""])
def test_role_cannot_be_changed(as_candidate, candidate_user, new_role):
    data = {"headline": "Dev", "location": "Lagos", "role": new_role}
    response = as_candidate.patch(URL, data, format="json")
    assert response.status_code == 400
    assert response.data["role"] == ["Your role cannot be changed."]
    candidate_user.refresh_from_db()
    assert candidate_user.role == "candidate"


def test_employer_role_cannot_be_changed(as_employer, employer, employer_user):
    response = as_employer.patch(URL, {"role": "candidate"}, format="json")
    assert response.status_code == 400
    employer_user.refresh_from_db()
    assert employer_user.role == "employer"
    assert not hasattr(employer_user, "candidate_profile")


def test_auth_me_is_read_only(as_candidate, candidate_user):
    response = as_candidate.patch(reverse("accounts:me"), {"role": "employer"}, format="json")
    assert response.status_code == 405
    candidate_user.refresh_from_db()
    assert candidate_user.role == "candidate"
