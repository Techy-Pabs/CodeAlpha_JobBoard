from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.db.models.functions import Length
from django.db.models.lookups import LessThanOrEqual

from candidates.models import CandidateProfile, Resume
from jobs.models import Job

COVER_LETTER_MAX = 2000


class ApplicationStatus(models.TextChoices):
    SUBMITTED = "submitted", "Submitted"
    REVIEWING = "reviewing", "Reviewing"
    SHORTLISTED = "shortlisted", "Shortlisted"
    INTERVIEW = "interview", "Interview"
    OFFERED = "offered", "Offered"
    REJECTED = "rejected", "Rejected"
    WITHDRAWN = "withdrawn", "Withdrawn"


class Application(models.Model):
    # PROTECT: jobs and resumes that applications point at can't be deleted
    # out from under them (the employer would lose the CV they reviewed).
    job = models.ForeignKey(Job, on_delete=models.PROTECT, related_name="applications")
    candidate = models.ForeignKey(
        CandidateProfile, on_delete=models.CASCADE, related_name="applications"
    )
    resume = models.ForeignKey(Resume, on_delete=models.PROTECT, related_name="applications")
    cover_letter = models.TextField(max_length=COVER_LETTER_MAX, blank=True)
    status = models.CharField(
        max_length=20, choices=ApplicationStatus.choices, default=ApplicationStatus.SUBMITTED
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["job", "candidate"],
                name="application_one_per_job_candidate",
                violation_error_message="This candidate has already applied to this job.",
            ),
            # Allowed values come from ApplicationStatus, so they cannot drift.
            models.CheckConstraint(
                condition=Q(status__in=ApplicationStatus.values),
                name="application_status_valid",
            ),
            # TextField max_length is only enforced by forms; enforce it in the DB too.
            models.CheckConstraint(
                condition=LessThanOrEqual(Length("cover_letter"), COVER_LETTER_MAX),
                name="application_cover_letter_max_2000",
            ),
        ]

    def __str__(self):
        return f"{self.candidate} -> {self.job.title} [{self.status}]"

    def clean(self):
        # A candidate can only apply with one of their own resumes.
        if self.resume_id and self.candidate_id and self.resume.candidate_id != self.candidate_id:
            raise ValidationError({"resume": "This resume belongs to a different candidate."})


class ApplicationStatusChange(models.Model):
    """One step in an application's history: who moved it, from what, to what."""

    application = models.ForeignKey(
        Application, on_delete=models.CASCADE, related_name="status_changes"
    )
    # Blank on the first row of every history: "" -> submitted, when applying.
    from_status = models.CharField(max_length=20, choices=ApplicationStatus.choices, blank=True)
    to_status = models.CharField(max_length=20, choices=ApplicationStatus.choices)
    # SET_NULL: the history survives if the person who made the change is deleted.
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="application_status_changes",
    )
    note = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.from_status} -> {self.to_status}"
