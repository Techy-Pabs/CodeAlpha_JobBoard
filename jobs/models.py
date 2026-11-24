from django.contrib.postgres.indexes import GinIndex
from django.db import models
from django.db.models import F, Q
from django.utils import timezone

from companies.models import EmployerProfile

from .search import SEARCH_INDEX_NAME, search_vector


class JobType(models.TextChoices):
    FULL_TIME = "full_time", "Full-time"
    PART_TIME = "part_time", "Part-time"
    CONTRACT = "contract", "Contract"
    INTERNSHIP = "internship", "Internship"


class WorkMode(models.TextChoices):
    ONSITE = "onsite", "On-site"
    REMOTE = "remote", "Remote"
    HYBRID = "hybrid", "Hybrid"


class ExperienceLevel(models.TextChoices):
    ENTRY = "entry", "Entry"
    MID = "mid", "Mid"
    SENIOR = "senior", "Senior"


class JobStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    OPEN = "open", "Open"
    CLOSED = "closed", "Closed"


def open_jobs_q(prefix=""):
    """Q for jobs that are open and not past closes_at: what the public sees.

    prefix lets the same rule filter related rows, e.g. open_jobs_q("jobs__")
    inside Count() on EmployerProfile.
    """
    return Q(**{f"{prefix}status": JobStatus.OPEN}) & (
        Q(**{f"{prefix}closes_at__isnull": True}) | Q(**{f"{prefix}closes_at__gt": timezone.now()})
    )


class JobQuerySet(models.QuerySet):
    def open(self):
        return self.filter(open_jobs_q())


class Job(models.Model):
    # PROTECT: a company with job posts can't be deleted by accident.
    employer = models.ForeignKey(EmployerProfile, on_delete=models.PROTECT, related_name="jobs")
    title = models.CharField(max_length=200)
    description = models.TextField()
    location = models.CharField(max_length=200)
    job_type = models.CharField(max_length=20, choices=JobType.choices)
    work_mode = models.CharField(max_length=20, choices=WorkMode.choices)
    salary_min = models.PositiveIntegerField(null=True, blank=True)
    salary_max = models.PositiveIntegerField(null=True, blank=True)
    salary_currency = models.CharField(max_length=3, default="NGN")
    experience_level = models.CharField(max_length=20, choices=ExperienceLevel.choices)
    skills = models.TextField(blank=True, help_text="Comma-separated, e.g. Python, Django, SQL.")
    status = models.CharField(max_length=20, choices=JobStatus.choices, default=JobStatus.DRAFT)
    closes_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = JobQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            # Either bound may be left out; when both are set, max >= min.
            models.CheckConstraint(
                condition=Q(salary_min__isnull=True)
                | Q(salary_max__isnull=True)
                | Q(salary_max__gte=F("salary_min")),
                name="job_salary_max_gte_min",
                violation_error_message="Maximum salary must be at least the minimum salary.",
            ),
        ]
        indexes = [
            # Full-text search (?q=) on the exact weighted vector the search
            # uses, so Postgres can find matches without reading every job.
            GinIndex(search_vector(), name=SEARCH_INDEX_NAME),
        ]

    def __str__(self):
        return f"{self.title} at {self.employer}"

    @property
    def is_open(self):
        """Open for applications right now (same rule as open_jobs_q)."""
        return self.status == JobStatus.OPEN and (
            self.closes_at is None or self.closes_at > timezone.now()
        )
