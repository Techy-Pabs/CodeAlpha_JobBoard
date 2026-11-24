"""/api/jobs/: visibility, permissions and the employer's own view."""

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from applications.models import Application
from jobs.models import Job

pytestmark = pytest.mark.django_db

LIST = reverse("job-list")


def detail(pk):
    return reverse("job-detail", args=[pk])


def make_job(employer, **overrides):
    data = {
        "employer": employer,
        "title": "Data Analyst",
        "description": "SQL and dashboards.",
        "location": "Abuja",
        "job_type": "contract",
        "work_mode": "remote",
        "experience_level": "entry",
        "status": "open",
    }
    data.update(overrides)
    return Job.objects.create(**data)


def payload(**overrides):
    data = {
        "title": "Backend Developer",
        "description": "Build APIs with Django.",
        "location": "Lagos",
        "job_type": "full_time",
        "work_mode": "hybrid",
        "experience_level": "mid",
        "status": "open",
    }
    data.update(overrides)
    return data


def ids(response):
    return [j["id"] for j in response.data["results"]]


@pytest.fixture
def other_employer(django_user_model):
    user = django_user_model.objects.create_user(
        username="globex", email="hr@globex.example", password="x-Pass-1234", role="employer"
    )
    profile = user.employer_profile
    profile.company_name, profile.location, profile.description = "Globex", "Abuja", "Energy."
    profile.save()
    return profile


@pytest.fixture
def jobs_by_state(employer):
    now = timezone.now()
    return {
        "open": make_job(employer, title="Open"),
        "open_future": make_job(employer, title="Open later", closes_at=now + timedelta(days=1)),
        "expired": make_job(employer, title="Expired", closes_at=now - timedelta(seconds=1)),
        "draft": make_job(employer, title="Draft", status="draft"),
        "closed": make_job(employer, title="Closed", status="closed"),
    }


# --- public visibility -------------------------------------------------------


def test_public_list_shows_only_open_unexpired_jobs(api_client, jobs_by_state):
    response = api_client.get(LIST)
    assert response.status_code == 200
    visible = {jobs_by_state["open"].id, jobs_by_state["open_future"].id}
    assert set(ids(response)) == visible


@pytest.mark.parametrize("state", ["expired", "draft", "closed"])
def test_hidden_job_detail_is_404(api_client, jobs_by_state, state):
    assert api_client.get(detail(jobs_by_state[state].id)).status_code == 404


@pytest.mark.parametrize("state", ["expired", "draft", "closed"])
def test_hidden_job_is_404_for_candidates_and_other_employers(
    api_client, jobs_by_state, state, candidate_user, other_employer
):
    for user in (candidate_user, other_employer.user):
        api_client.force_authenticate(user)
        assert api_client.get(detail(jobs_by_state[state].id)).status_code == 404
        assert jobs_by_state[state].id not in ids(api_client.get(LIST))


def test_open_job_detail_is_public(api_client, jobs_by_state):
    response = api_client.get(detail(jobs_by_state["open"].id))
    assert response.status_code == 200
    assert response.data["is_open"] is True


def test_employer_sees_all_own_jobs_plus_others_open(
    api_client, employer_user, jobs_by_state, other_employer
):
    others_open = make_job(other_employer, title="Globex open")
    others_draft = make_job(other_employer, title="Globex draft", status="draft")
    api_client.force_authenticate(employer_user)
    seen = set(ids(api_client.get(LIST)))
    assert seen == {j.id for j in jobs_by_state.values()} | {others_open.id}
    assert others_draft.id not in seen
    for job in jobs_by_state.values():
        assert api_client.get(detail(job.id)).status_code == 200


def test_job_includes_company_name_and_location(api_client, jobs_by_state, employer):
    data = api_client.get(detail(jobs_by_state["open"].id)).data
    assert data["company_id"] == employer.id
    assert data["company_name"] == "Acme Ltd"
    assert data["company_location"] == "Lagos"


# --- application count: owner only -------------------------------------------


@pytest.fixture
def applied_job(employer, candidate, resume):
    job = make_job(employer, title="Applied")
    Application.objects.create(job=job, candidate=candidate, resume=resume)
    return job


def test_owner_sees_application_count(api_client, employer_user, applied_job):
    api_client.force_authenticate(employer_user)
    assert api_client.get(detail(applied_job.id)).data["application_count"] == 1
    [row] = api_client.get(LIST).data["results"]
    assert row["application_count"] == 1


def test_others_never_see_application_count(
    api_client, applied_job, candidate_user, other_employer
):
    for user in (None, candidate_user, other_employer.user):
        api_client.force_authenticate(user)
        assert "application_count" not in api_client.get(detail(applied_job.id)).data
        [row] = api_client.get(LIST).data["results"]
        assert "application_count" not in row


# --- create -------------------------------------------------------------------


def test_employer_creates_job(api_client, employer_user, employer):
    api_client.force_authenticate(employer_user)
    response = api_client.post(LIST, payload(), format="json")
    assert response.status_code == 201, response.data
    assert response.data["company_name"] == "Acme Ltd"
    assert response.data["application_count"] == 0
    assert Job.objects.get(pk=response.data["id"]).employer == employer


def test_employer_is_taken_from_the_login_not_the_body(
    api_client, employer_user, employer, other_employer
):
    api_client.force_authenticate(employer_user)
    body = payload(employer=other_employer.id, company_id=other_employer.id)
    response = api_client.post(LIST, body, format="json")
    assert response.status_code == 201
    assert Job.objects.get(pk=response.data["id"]).employer == employer


def test_new_job_defaults_to_draft(api_client, employer_user, employer):
    api_client.force_authenticate(employer_user)
    body = payload()
    del body["status"]
    assert api_client.post(LIST, body, format="json").data["status"] == "draft"


def test_create_needs_login(api_client):
    assert api_client.post(LIST, payload(), format="json").status_code == 401


def test_candidate_cannot_create(api_client, candidate_user):
    api_client.force_authenticate(candidate_user)
    response = api_client.post(LIST, payload(), format="json")
    assert response.status_code == 403
    assert not Job.objects.exists()


@pytest.mark.parametrize("blank", ["company_name", "location", "description"])
def test_incomplete_profile_cannot_post(api_client, employer_user, employer, blank):
    setattr(employer, blank, "")
    employer.save()
    api_client.force_authenticate(employer_user)
    response = api_client.post(LIST, payload(), format="json")
    assert response.status_code == 400
    assert "Complete your company profile" in response.data["detail"]
    assert not Job.objects.exists()


@pytest.mark.parametrize(
    ("override", "field"),
    [
        ({"salary_min": 500, "salary_max": 400}, "salary_max"),
        ({"salary_currency": "naira"}, "salary_currency"),
        ({"closes_at": "2000-01-01T00:00:00Z"}, "closes_at"),
        ({"job_type": "gig"}, "job_type"),
        ({"status": "archived"}, "status"),
        ({"title": ""}, "title"),
    ],
)
def test_create_validation(api_client, employer_user, employer, override, field):
    api_client.force_authenticate(employer_user)
    response = api_client.post(LIST, payload(**override), format="json")
    assert response.status_code == 400
    assert field in response.data


def test_currency_is_upper_cased(api_client, employer_user, employer):
    api_client.force_authenticate(employer_user)
    response = api_client.post(LIST, payload(salary_currency="usd"), format="json")
    assert response.data["salary_currency"] == "USD"


# --- update -------------------------------------------------------------------


def test_owner_updates_job(api_client, employer_user, job):
    api_client.force_authenticate(employer_user)
    response = api_client.patch(detail(job.id), {"status": "open"}, format="json")
    assert response.status_code == 200
    job.refresh_from_db()
    assert job.status == "open"


def test_patch_checks_salary_against_stored_bound(api_client, employer_user, job):
    job.salary_min = 500_000
    job.save()
    api_client.force_authenticate(employer_user)
    response = api_client.patch(detail(job.id), {"salary_max": 100}, format="json")
    assert response.status_code == 400
    assert "salary_max" in response.data


def test_other_employer_cannot_update_open_job(api_client, other_employer, employer):
    job = make_job(employer)
    api_client.force_authenticate(other_employer.user)
    assert api_client.patch(detail(job.id), {"title": "Mine"}, format="json").status_code == 403
    assert api_client.delete(detail(job.id)).status_code == 403
    job.refresh_from_db()
    assert job.title == "Data Analyst"


def test_other_employer_gets_404_for_hidden_job(api_client, other_employer, job):
    api_client.force_authenticate(other_employer.user)  # job is a draft
    assert api_client.patch(detail(job.id), {"title": "x"}, format="json").status_code == 404


def test_candidate_cannot_update(api_client, candidate_user, employer):
    job = make_job(employer)
    api_client.force_authenticate(candidate_user)
    assert api_client.patch(detail(job.id), {"title": "x"}, format="json").status_code == 403


def test_anonymous_cannot_update(api_client, employer):
    job = make_job(employer)
    assert api_client.patch(detail(job.id), {"title": "x"}, format="json").status_code == 401


# --- delete -------------------------------------------------------------------


def test_owner_deletes_draft_without_applications(api_client, employer_user, job):
    api_client.force_authenticate(employer_user)
    assert api_client.delete(detail(job.id)).status_code == 204
    assert not Job.objects.filter(pk=job.id).exists()


@pytest.mark.parametrize("status", ["open", "closed"])
def test_non_draft_cannot_be_deleted(api_client, employer_user, employer, status):
    job = make_job(employer, status=status)
    api_client.force_authenticate(employer_user)
    response = api_client.delete(detail(job.id))
    assert response.status_code == 409
    assert "status=closed" in response.data["detail"]
    assert Job.objects.filter(pk=job.id).exists()


def test_draft_with_applications_cannot_be_deleted(api_client, employer_user, applied_job):
    applied_job.status = "draft"
    applied_job.save()
    api_client.force_authenticate(employer_user)
    assert api_client.delete(detail(applied_job.id)).status_code == 409
    assert Job.objects.filter(pk=applied_job.id).exists()
