import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError

from jobs.models import Job, JobStatus

pytestmark = pytest.mark.django_db


def make_job(employer, **overrides):
    data = {
        "employer": employer,
        "title": "Data Analyst",
        "description": "SQL and dashboards.",
        "location": "Abuja",
        "job_type": "contract",
        "work_mode": "remote",
        "experience_level": "entry",
    }
    data.update(overrides)
    return Job.objects.create(**data)


def test_defaults(job):
    assert job.status == JobStatus.DRAFT
    assert job.salary_currency == "NGN"
    assert job.salary_min is None and job.salary_max is None


def test_db_rejects_salary_max_below_min(employer):
    with (
        pytest.raises(IntegrityError, match="job_salary_max_gte_min"),
        transaction.atomic(),
    ):
        make_job(employer, salary_min=500_000, salary_max=400_000)


@pytest.mark.parametrize(
    ("salary_min", "salary_max"),
    [(300_000, 300_000), (300_000, 450_000), (None, 450_000), (300_000, None), (None, None)],
)
def test_valid_salary_ranges_are_accepted(employer, salary_min, salary_max):
    job = make_job(employer, salary_min=salary_min, salary_max=salary_max)
    assert job.pk


def test_db_rejects_negative_salary(employer):
    with pytest.raises(IntegrityError), transaction.atomic():
        make_job(employer, salary_min=-1)


def test_model_validation_explains_salary_range(employer):
    """The admin form runs this check, so it shows a clear error, not a 500."""
    job = Job(
        employer=employer,
        title="X",
        description="X",
        location="X",
        job_type="contract",
        work_mode="remote",
        experience_level="entry",
        salary_min=2,
        salary_max=1,
    )
    with pytest.raises(ValidationError, match="at least the minimum"):
        job.full_clean()


def test_employer_with_jobs_cannot_be_deleted(employer, job):
    with pytest.raises(ProtectedError):
        employer.delete()
