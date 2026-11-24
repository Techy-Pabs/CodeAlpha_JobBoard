"""GET /api/companies/{id}/: public employer profile."""

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from jobs.models import Job

pytestmark = pytest.mark.django_db


def url(pk):
    return reverse("companies:detail", args=[pk])


def make_job(employer, **overrides):
    data = {
        "employer": employer,
        "title": "Data Analyst",
        "description": "SQL.",
        "location": "Abuja",
        "job_type": "contract",
        "work_mode": "remote",
        "experience_level": "entry",
        "status": "open",
    }
    data.update(overrides)
    return Job.objects.create(**data)


def test_company_is_public(api_client, employer):
    response = api_client.get(url(employer.id))
    assert response.status_code == 200
    assert response.data["company_name"] == "Acme Ltd"
    assert response.data["location"] == "Lagos"
    assert response.data["open_jobs_count"] == 0


def test_public_profile_hides_account_details(api_client, employer):
    data = api_client.get(url(employer.id)).data
    assert "user" not in data and "username" not in data and "email" not in data


def test_stale_token_does_not_block_public_profile(api_client, employer):
    api_client.credentials(HTTP_AUTHORIZATION="Bearer not-a-real-token")
    assert api_client.get(url(employer.id)).status_code == 200


def test_open_jobs_count_only_counts_open_unexpired_jobs(api_client, employer):
    now = timezone.now()
    make_job(employer)  # open, no deadline
    make_job(employer, closes_at=now + timedelta(days=3))  # open, deadline ahead
    make_job(employer, closes_at=now - timedelta(minutes=1))  # deadline passed
    make_job(employer, status="draft")
    make_job(employer, status="closed")
    assert api_client.get(url(employer.id)).data["open_jobs_count"] == 2


def test_unknown_company_is_404(api_client):
    assert api_client.get(url(999_999)).status_code == 404


def test_deactivated_employer_is_404(api_client, employer, employer_user):
    employer_user.is_active = False
    employer_user.save()
    assert api_client.get(url(employer.id)).status_code == 404


def test_read_only(api_client, employer, employer_user):
    api_client.force_authenticate(employer_user)
    assert api_client.patch(url(employer.id), {"company_name": "X"}).status_code == 405
