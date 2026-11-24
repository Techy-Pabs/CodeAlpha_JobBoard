"""Filters, full-text search and ordering on GET /api/jobs/."""

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from jobs.models import Job

pytestmark = pytest.mark.django_db

LIST = reverse("job-list")


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


def titles(client, **params):
    response = client.get(LIST, params)
    assert response.status_code == 200, response.data
    return [j["title"] for j in response.data["results"]]


# --- full-text search ---------------------------------------------------------


def test_plural_finds_singular_title(api_client, employer):
    make_job(employer, title="Python Developer")
    make_job(employer, title="Accountant", description="Spreadsheets.")
    assert titles(api_client, q="developers") == ["Python Developer"]


def test_search_covers_skills_and_description(api_client, employer):
    make_job(employer, title="Engineer A", skills="Kubernetes, Go")
    make_job(employer, title="Engineer B", description="You will run Kubernetes clusters.")
    make_job(employer, title="Engineer C")
    assert set(titles(api_client, q="kubernetes")) == {"Engineer A", "Engineer B"}


def test_title_match_ranks_above_skills_above_description(api_client, employer):
    # Created in the reverse of the expected order, so "newest" would differ.
    make_job(employer, title="Ops role", description="Some django work.")
    make_job(employer, title="Web role", skills="Django")
    make_job(employer, title="Django Engineer")
    assert titles(api_client, q="django") == ["Django Engineer", "Web role", "Ops role"]


def test_search_handles_punctuation_and_operators(api_client, employer):
    make_job(employer, title="C++ Developer")
    for q in ['"unclosed', "a & | ! b", "(((", "-developer", "' OR 1=1 --"]:
        assert api_client.get(LIST, {"q": q}).status_code == 200


def test_search_with_no_match(api_client, employer):
    make_job(employer, title="Python Developer")
    assert titles(api_client, q="astronaut") == []


def test_overlong_search_is_400(api_client):
    response = api_client.get(LIST, {"q": "x" * 201})
    assert response.status_code == 400
    assert "q" in response.data


def test_blank_search_is_ignored(api_client, employer):
    make_job(employer)
    assert len(titles(api_client, q="  ")) == 1


# --- filters ------------------------------------------------------------------


def test_location_contains_ignoring_case(api_client, employer):
    make_job(employer, title="A", location="Lagos, Nigeria")
    make_job(employer, title="B", location="Abuja")
    assert titles(api_client, location="lagos") == ["A"]


@pytest.mark.parametrize(
    ("param", "match", "other"),
    [
        ("job_type", "full_time", "contract"),
        ("work_mode", "onsite", "remote"),
        ("experience_level", "senior", "entry"),
    ],
)
def test_choice_filters(api_client, employer, param, match, other):
    make_job(employer, title="Match", **{param: match})
    make_job(employer, title="Other", **{param: other})
    assert titles(api_client, **{param: match}) == ["Match"]


@pytest.mark.parametrize("param", ["job_type", "work_mode", "experience_level"])
def test_unknown_choice_is_400(api_client, param):
    response = api_client.get(LIST, {param: "nope"})
    assert response.status_code == 400
    assert "Choose one of" in response.data[param][0]


def test_min_salary_compares_with_salary_max(api_client, employer):
    make_job(employer, title="High", salary_min=100, salary_max=500)
    make_job(employer, title="Exact", salary_max=300)
    make_job(employer, title="Low", salary_min=100, salary_max=299)
    make_job(employer, title="Unknown")  # no salary: can't promise the minimum
    assert set(titles(api_client, min_salary=300)) == {"High", "Exact"}


@pytest.mark.parametrize("bad", ["abc", "-5", "1.5", "99999999999"])
def test_bad_min_salary_is_400(api_client, bad):
    response = api_client.get(LIST, {"min_salary": bad})
    assert response.status_code == 400
    assert "min_salary" in response.data


def test_filters_combine(api_client, employer):
    make_job(employer, title="Python Developer", location="Lagos", work_mode="remote")
    make_job(employer, title="Python Developer II", location="Lagos", work_mode="onsite")
    make_job(employer, title="Python Developer III", location="Abuja", work_mode="remote")
    assert titles(api_client, q="python", location="lagos", work_mode="remote") == [
        "Python Developer"
    ]


def test_several_bad_values_reported_together(api_client):
    response = api_client.get(LIST, {"job_type": "x", "min_salary": "y", "ordering": "z"})
    assert response.status_code == 400
    assert {"job_type", "min_salary", "ordering"} <= set(response.data)


def test_filters_do_not_reveal_hidden_jobs(api_client, employer):
    make_job(employer, title="Python Developer", status="draft")
    assert titles(api_client, q="python") == []


def test_filter_params_are_ignored_on_detail(api_client, employer):
    job = make_job(employer)
    response = api_client.get(reverse("job-detail", args=[job.id]), {"job_type": "bad"})
    assert response.status_code == 200


# --- ordering -----------------------------------------------------------------


def test_default_ordering_is_newest(api_client, employer):
    make_job(employer, title="Old")
    make_job(employer, title="New")
    assert titles(api_client) == ["New", "Old"]
    assert titles(api_client, ordering="newest") == ["New", "Old"]


def test_salary_ordering_highest_first_unknown_last(api_client, employer):
    make_job(employer, title="Unknown")
    make_job(employer, title="Mid", salary_max=200)
    make_job(employer, title="Top", salary_max=900)
    assert titles(api_client, ordering="salary") == ["Top", "Mid", "Unknown"]


def test_relevance_needs_q(api_client):
    response = api_client.get(LIST, {"ordering": "relevance"})
    assert response.status_code == 400
    assert "ordering" in response.data


def test_q_can_be_ordered_by_newest(api_client, employer):
    make_job(employer, title="Django Engineer")
    make_job(employer, title="Web role", skills="Django")
    assert titles(api_client, q="django", ordering="newest") == ["Web role", "Django Engineer"]


def test_unknown_ordering_is_400(api_client):
    assert api_client.get(LIST, {"ordering": "-salary"}).status_code == 400


# --- query count --------------------------------------------------------------


def count_queries(client, **params):
    with CaptureQueriesContext(connection) as ctx:
        assert client.get(LIST, params).status_code == 200
    return len(ctx.captured_queries)


@pytest.mark.parametrize("params", [{}, {"q": "developer", "ordering": "relevance"}])
@pytest.mark.parametrize("who", ["anonymous", "employer", "candidate"])
def test_list_query_count_does_not_grow_with_jobs(
    api_client, employer, employer_user, candidate_user, resume, params, who
):
    from applications.models import Application

    user = {"anonymous": None, "employer": employer_user, "candidate": candidate_user}[who]
    api_client.force_authenticate(user)
    make_job(employer, title="Python Developer")
    one = count_queries(api_client, **params)
    for n in range(8):
        job = make_job(employer, title=f"Developer {n}", status="draft" if n % 2 else "open")
        if n < 2:
            Application.objects.create(job=job, candidate=resume.candidate, resume=resume)
    many = count_queries(api_client, **params)
    assert one == many
    assert many <= 2  # page count + page rows
