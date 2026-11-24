"""POST /api/jobs/{id}/apply/ and GET /api/me/applications/."""

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from applications.models import Application
from candidates.models import Resume

pytestmark = pytest.mark.django_db

MY_APPLICATIONS = reverse("my-applications")


def apply_url(job):
    return reverse("job-apply", args=[job.id])


@pytest.fixture
def as_candidate(api_client, candidate_user):
    api_client.force_authenticate(candidate_user)
    return api_client


def test_apply_with_default_resume(as_candidate, open_job, candidate, resume, candidate_user):
    response = as_candidate.post(apply_url(open_job), {"cover_letter": "Hi!"}, format="json")
    assert response.status_code == 201, response.data
    assert response.data["status"] == "submitted"
    assert response.data["resume"]["id"] == resume.id
    assert response.data["cover_letter"] == "Hi!"
    assert response.data["job_title"] == open_job.title
    assert response.data["allowed_moves"] == ["withdrawn"]
    application = Application.objects.get(pk=response.data["id"])
    assert application.candidate == candidate
    [first] = application.status_changes.all()
    assert (first.from_status, first.to_status, first.changed_by) == (
        "",
        "submitted",
        candidate_user,
    )
    assert response.data["history"][0]["from_status"] == ""


def test_apply_with_chosen_resume(as_candidate, open_job, candidate, resume):
    other = Resume.objects.create(
        candidate=candidate, file="resumes/b.pdf", original_filename="b.pdf", size_bytes=1
    )
    response = as_candidate.post(apply_url(open_job), {"resume_id": other.id}, format="json")
    assert response.status_code == 201
    assert response.data["resume"]["id"] == other.id


def test_empty_body_is_fine(as_candidate, open_job, resume):
    assert as_candidate.post(apply_url(open_job)).status_code == 201


def test_no_default_resume_is_400(as_candidate, open_job, candidate):
    response = as_candidate.post(apply_url(open_job), {}, format="json")
    assert response.status_code == 400
    assert "no default resume" in response.data["resume_id"][0]
    assert not Application.objects.exists()


def test_someone_elses_resume_is_400(as_candidate, open_job, resume, other_candidate):
    theirs = Resume.objects.create(
        candidate=other_candidate, file="resumes/g.pdf", original_filename="g.pdf", size_bytes=1
    )
    response = as_candidate.post(apply_url(open_job), {"resume_id": theirs.id}, format="json")
    assert response.status_code == 400
    assert "not one of your resumes" in response.data["resume_id"][0]


def test_cover_letter_over_2000_is_400(as_candidate, open_job, resume):
    body = {"cover_letter": "x" * 2001}
    response = as_candidate.post(apply_url(open_job), body, format="json")
    assert response.status_code == 400
    assert "cover_letter" in response.data


def test_second_application_is_409(as_candidate, open_job, resume):
    assert as_candidate.post(apply_url(open_job)).status_code == 201
    response = as_candidate.post(apply_url(open_job))
    assert response.status_code == 409
    assert response.data["detail"] == "You have already applied to this job."
    assert Application.objects.count() == 1


def test_second_application_is_409_even_after_withdrawing(as_candidate, application, open_job):
    application.status = "withdrawn"
    application.save()
    assert as_candidate.post(apply_url(open_job)).status_code == 409


@pytest.mark.parametrize(
    "change",
    [
        {"status": "draft"},
        {"status": "closed"},
        {"closes_at": timezone.now() - timedelta(minutes=1)},
    ],
)
def test_job_must_be_open(as_candidate, open_job, resume, change):
    for field, value in change.items():
        setattr(open_job, field, value)
    open_job.save()
    assert as_candidate.post(apply_url(open_job)).status_code == 404
    assert not Application.objects.exists()


def test_employer_cannot_apply(api_client, employer_user, open_job):
    api_client.force_authenticate(employer_user)
    assert api_client.post(apply_url(open_job)).status_code == 403


def test_anonymous_cannot_apply(api_client, open_job):
    assert api_client.post(apply_url(open_job)).status_code == 401


# --- my applications ----------------------------------------------------------


def test_my_applications_lists_own_only(
    as_candidate, application, other_candidate, open_job, other_employer
):
    other_resume = Resume.objects.create(
        candidate=other_candidate, file="resumes/g.pdf", original_filename="g.pdf", size_bytes=1
    )
    Application.objects.create(job=open_job, candidate=other_candidate, resume=other_resume)
    response = as_candidate.get(MY_APPLICATIONS)
    assert response.status_code == 200
    [row] = response.data["results"]
    assert row["id"] == application.id
    assert row["job_title"] == open_job.title
    assert row["company_name"] == "Acme Ltd"
    assert row["status"] == "submitted"


def test_my_applications_filter_by_status(as_candidate, make_application, employer):
    from jobs.models import Job

    first = make_application("reviewing")
    second_job = Job.objects.create(
        employer=employer,
        title="Second",
        description="x",
        location="x",
        job_type="contract",
        work_mode="remote",
        experience_level="entry",
        status="open",
    )
    make_application(job=second_job)
    response = as_candidate.get(MY_APPLICATIONS, {"status": "reviewing"})
    assert [r["id"] for r in response.data["results"]] == [first.id]
    assert as_candidate.get(MY_APPLICATIONS, {"status": "hired"}).status_code == 400


def test_my_applications_still_shows_closed_jobs(as_candidate, application, open_job):
    open_job.status = "closed"
    open_job.save()
    assert len(as_candidate.get(MY_APPLICATIONS).data["results"]) == 1


def test_employer_cannot_list_my_applications(api_client, employer_user):
    api_client.force_authenticate(employer_user)
    assert api_client.get(MY_APPLICATIONS).status_code == 403


def test_anonymous_cannot_list_my_applications(api_client):
    assert api_client.get(MY_APPLICATIONS).status_code == 401
