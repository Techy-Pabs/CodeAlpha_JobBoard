"""GET /api/me/stats/: application counts per job by status, for employers."""

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from applications.models import Application, ApplicationStatus
from candidates.models import Resume
from jobs.models import Job

pytestmark = pytest.mark.django_db

STATS = reverse("my-stats")
ZERO = dict.fromkeys(ApplicationStatus.values, 0)


@pytest.fixture
def make_candidate(django_user_model):
    count = 0

    def make():
        nonlocal count
        count += 1
        user = django_user_model.objects.create_user(
            username=f"cand{count}",
            email=f"cand{count}@example.com",
            password="x-Pass-1234",
            role="candidate",
        )
        profile = user.candidate_profile
        resume = Resume.objects.create(
            candidate=profile, file=f"resumes/{count}.pdf", original_filename="cv.pdf", size_bytes=1
        )
        return profile, resume

    return make


@pytest.fixture
def make_job(employer):
    def make(title, status="open", employer_profile=employer):
        return Job.objects.create(
            employer=employer_profile,
            title=title,
            description="d",
            location="Lagos",
            job_type="full_time",
            work_mode="remote",
            experience_level="mid",
            status=status,
        )

    return make


@pytest.fixture
def add_applications(make_candidate):
    def add(job, *statuses):
        for status in statuses:
            candidate, resume = make_candidate()
            Application.objects.create(job=job, candidate=candidate, resume=resume, status=status)

    return add


@pytest.fixture
def as_employer(api_client, employer_user):
    api_client.force_authenticate(employer_user)
    return api_client


def test_counts_per_job_and_totals(as_employer, make_job, add_applications, other_employer):
    backend = make_job("Backend")
    frontend = make_job("Frontend", status="closed")
    empty = make_job("Draft role", status="draft")
    add_applications(backend, "submitted", "submitted", "reviewing", "rejected")
    add_applications(frontend, "offered", "withdrawn")
    # Another employer's job and applications must not show up.
    add_applications(make_job("Theirs", employer_profile=other_employer), "submitted")

    response = as_employer.get(STATS)
    assert response.status_code == 200
    by_title = {job["title"]: job for job in response.data["jobs"]}
    assert set(by_title) == {"Backend", "Frontend", "Draft role"}

    assert by_title["Backend"] == {
        "id": backend.id,
        "title": "Backend",
        "status": "open",
        "applications": {**ZERO, "submitted": 2, "reviewing": 1, "rejected": 1},
        "total": 4,
    }
    assert by_title["Frontend"]["applications"] == {**ZERO, "offered": 1, "withdrawn": 1}
    assert by_title["Frontend"]["status"] == "closed"
    assert by_title["Draft role"]["applications"] == ZERO
    assert by_title["Draft role"]["total"] == 0
    assert empty.id == by_title["Draft role"]["id"]

    assert response.data["totals"] == {
        "jobs": 3,
        "applications": {
            **ZERO,
            "submitted": 2,
            "reviewing": 1,
            "rejected": 1,
            "offered": 1,
            "withdrawn": 1,
        },
        "total": 6,
    }


def test_employer_with_no_jobs(as_employer):
    response = as_employer.get(STATS)
    assert response.data == {"jobs": [], "totals": {"jobs": 0, "applications": ZERO, "total": 0}}


def test_jobs_listed_newest_first(as_employer, make_job):
    old, new = make_job("Old"), make_job("New")
    assert [job["id"] for job in as_employer.get(STATS).data["jobs"]] == [new.id, old.id]


def test_query_count_does_not_grow_with_jobs(as_employer, make_job, add_applications):
    def queries_for_stats():
        with CaptureQueriesContext(connection) as ctx:
            assert as_employer.get(STATS).status_code == 200
        return len(ctx.captured_queries)

    add_applications(make_job("One"), "submitted")
    with_one = queries_for_stats()
    for n in range(8):
        add_applications(make_job(f"Job {n}"), "submitted", "reviewing", "interview")
    assert queries_for_stats() == with_one
    # force_authenticate needs no user lookup, so the stats are a single query.
    assert with_one == 1


def test_candidates_get_403(api_client, candidate_user):
    api_client.force_authenticate(candidate_user)
    assert api_client.get(STATS).status_code == 403


def test_needs_login(api_client):
    assert api_client.get(STATS).status_code == 401
