from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from accounts.models import Role


class EmployerProfile(models.Model):
    """The company behind an employer account. One per employer user.

    Created empty when the employer registers; they fill it in later.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="employer_profile",
        limit_choices_to={"role": Role.EMPLOYER},
    )
    company_name = models.CharField(max_length=200, blank=True)
    website = models.URLField(blank=True)
    location = models.CharField(max_length=200, blank=True)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["company_name"]

    def __str__(self):
        return self.company_name or f"(unnamed company of {self.user})"

    def clean(self):
        if self.user_id and self.user.role != Role.EMPLOYER:
            raise ValidationError({"user": "Only employer accounts can have an employer profile."})
