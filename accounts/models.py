from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower

DUPLICATE_USERNAME = "A user with that username already exists."
ROLE_REQUIRED = "Choose a role: employer or candidate. Only staff users may have no role."


class Role(models.TextChoices):
    EMPLOYER = "employer", "Employer"
    CANDIDATE = "candidate", "Candidate"


class User(AbstractUser):
    """Project user. Employers post jobs; candidates apply to them.

    Staff (admin) users may have no role. Everyone else must have one,
    enforced by the user_role_required_unless_staff database check.
    """

    role = models.CharField(max_length=20, choices=Role.choices, blank=True)

    class Meta(AbstractUser.Meta):
        constraints = [
            # Usernames are unique ignoring case: "Alice" blocks "alice".
            # The username is still stored exactly as typed.
            models.UniqueConstraint(
                Lower("username"),
                name="user_username_ci_unique",
                violation_error_message=DUPLICATE_USERNAME,
            ),
            # Emails are unique ignoring case. Blank emails (e.g. a superuser
            # created without one) are left out so several can coexist.
            models.UniqueConstraint(
                Lower("email"),
                condition=~Q(email=""),
                name="user_email_ci_unique",
            ),
            # role is one of the choices, or blank for staff users only.
            models.CheckConstraint(
                condition=Q(role__in=Role.values) | Q(role="", is_staff=True),
                name="user_role_required_unless_staff",
                violation_error_message=ROLE_REQUIRED,
            ),
        ]

    def save(self, *args, **kwargs):
        # Normalise here, not only in the API serializer, so users created in
        # the admin, the shell or a data migration are stored the same way.
        self.email = (self.email or "").strip().lower()
        super().save(*args, **kwargs)

    @property
    def is_employer(self):
        return self.role == Role.EMPLOYER

    @property
    def is_candidate(self):
        return self.role == Role.CANDIDATE

    def __str__(self):
        return self.username
