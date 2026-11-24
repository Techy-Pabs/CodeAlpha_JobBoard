import uuid
from pathlib import PurePath

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.db import models
from django.db.models import Q

from accounts.models import Role

RESUME_EXTENSIONS = ["pdf", "doc", "docx"]


class CandidateProfile(models.Model):
    """A job seeker's public profile. One per candidate user.

    Created empty when the candidate registers; they fill it in later.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="candidate_profile",
        limit_choices_to={"role": Role.CANDIDATE},
    )
    headline = models.CharField(max_length=200, blank=True)
    location = models.CharField(max_length=200, blank=True)
    skills = models.TextField(blank=True, help_text="Comma-separated, e.g. Python, Django, SQL.")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["user__username"]

    def __str__(self):
        return f"{self.user} ({self.headline})" if self.headline else str(self.user)

    def clean(self):
        if self.user_id and self.user.role != Role.CANDIDATE:
            raise ValidationError({"user": "Only candidate accounts can have a candidate profile."})


def resume_upload_to(instance, filename):
    """Store under a random name, so the user's file name never reaches disk.

    Only a known extension is kept (lower-cased); anything else is dropped.
    The original name is kept in Resume.original_filename for display.
    """
    ext = PurePath(filename).suffix.lower().lstrip(".")
    suffix = f".{ext}" if ext in RESUME_EXTENSIONS else ""
    return f"resumes/{uuid.uuid4().hex}{suffix}"


class Resume(models.Model):
    candidate = models.ForeignKey(
        CandidateProfile, on_delete=models.CASCADE, related_name="resumes"
    )
    file = models.FileField(
        upload_to=resume_upload_to,
        validators=[FileExtensionValidator(RESUME_EXTENSIONS)],
    )
    original_filename = models.CharField(max_length=255)
    size_bytes = models.PositiveIntegerField()
    is_default = models.BooleanField(default=False)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-uploaded_at"]
        constraints = [
            # A candidate can have many resumes but at most one default.
            models.UniqueConstraint(
                fields=["candidate"],
                condition=Q(is_default=True),
                name="resume_one_default_per_candidate",
                violation_error_message="This candidate already has a default resume.",
            ),
        ]

    def __str__(self):
        return f"{self.original_filename} ({self.candidate.user})"
