"""Who can see which application, and the employer's list for a job."""

import pytest
from django.urls import reverse

from applications.models import Application
from candidates.models import Resume

pytestmark = pytest.mark.django_db


def detail(application):
    return reverse("application-detail", args=[application.id])


def job_applications(job):
    return reverse("job-applications", args=[job.id])


# --- GET /api/applications/{id}/ ------------------------------------------------


def test_candidate_sees_own_application_with_history(api_client, candidate_user, application):
    api_client.force_authenticate(candidate_user)
    response = api_client.get(detail(application))
    assert response.status_code == 200
    assert response.data["history"][0]["to_status"] == "submitted"
    assert response.data["allowed_moves"] == ["withdrawn"]


def test_job_employer_sees_application(api_client, employer_user, make_application):
    application = make_application("reviewing")
    api_client.force_authenticate(employer_user)
    response = api_client.get(detail(application))
    assert response.status_code == 200
    assert [h["to_status"] for h in response.data["history"]] == ["submitted", "reviewing"]
    assert response.data["allowed_moves"] == ["shortlisted", "rejected"]
    assert response.data["candidate"]["username"] == "ada"
    assert response.data["resume"]["download_url"].endswith(
        reverse("resume-download", args=[application.resume_id])
    )


def test_other_people_get_404(api_client, application, other_employer, other_candidate):
    for user in (other_employer.user, other_candidate.user):
        api_client.force_authenticate(user)
        assert api_client.get(detail(application)).status_code == 404


def test_staff_without_role_gets_404(api_client, application, django_user_model):
    admin = django_user_model.objects.create_superuser(username="root", password="x-12345!")
    api_client.force_authenticate(admin)
    assert api_client.get(detail(application)).status_code == 404


def test_anonymous_gets_401(api_client, application):
    assert api_client.get(detail(application)).status_code == 401


def test_there_is_no_list_or_update(api_client, candidate_user, application):
    api_client.force_authenticate(candidate_user)
    assert api_client.get("/api/applications/").status_code == 404
    assert api_client.patch(detail(application), {"status": "offered"}).status_code == 405
    assert api_client.delete(detail(application)).status_code == 405


# --- GET /api/jobs/{id}/applications/ ---------------------------------------------


def test_employer_lists_applications_to_own_job(
    api_client, employer_user, application, open_job, other_candidate
):
    other_resume = Resume.objects.create(
        candidate=other_candidate, file="resumes/g.pdf", original_filename="g.pdf", size_bytes=1
    )
    Application.objects.create(
        job=open_job, candidate=other_candidate, resume=other_resume, status="rejected"
    )
    api_client.force_authenticate(employer_user)
    response = api_client.get(job_applications(open_job))
    assert response.status_code == 200
    assert response.data["count"] == 2
    row = next(r for r in response.data["results"] if r["id"] == application.id)
    assert row["candidate"]["username"] == "ada"
    assert row["resume"]["original_filename"] == "Ada CV.pdf"


def test_filter_by_status(api_client, employer_user, application, open_job):
    api_client.force_authenticate(employer_user)
    response = api_client.get(job_applications(open_job), {"status": "submitted"})
    assert [r["id"] for r in response.data["results"]] == [application.id]
    response = api_client.get(job_applications(open_job), {"status": "offered"})
    assert response.data["results"] == []


def test_bad_status_filter_is_400(api_client, employer_user, open_job):
    api_client.force_authenticate(employer_user)
    response = api_client.get(job_applications(open_job), {"status": "hired"})
    assert response.status_code == 400
    assert "status" in response.data


def test_employer_still_sees_applications_after_closing(
    api_client, employer_user, application, open_job
):
    open_job.status = "closed"
    open_job.save()
    api_client.force_authenticate(employer_user)
    assert api_client.get(job_applications(open_job)).data["count"] == 1


def test_other_employer_gets_403(api_client, other_employer, open_job, application):
    api_client.force_authenticate(other_employer.user)
    assert api_client.get(job_applications(open_job)).status_code == 403


def test_candidate_gets_403_even_for_own_application(api_client, candidate_user, open_job):
    api_client.force_authenticate(candidate_user)
    assert api_client.get(job_applications(open_job)).status_code == 403


def test_anonymous_gets_401_for_job_applications(api_client, open_job):
    assert api_client.get(job_applications(open_job)).status_code == 401


def test_hidden_job_of_another_employer_is_404(api_client, other_employer, job):
    api_client.force_authenticate(other_employer.user)  # job is a draft
    assert api_client.get(job_applications(job)).status_code == 404
