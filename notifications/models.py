from django.conf import settings
from django.db import models

from applications.models import Application


class NotificationKind(models.TextChoices):
    NEW_APPLICATION = "new_application", "New application"
    STATUS_CHANGED = "status_changed", "Status changed"


class Notification(models.Model):
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications"
    )
    kind = models.CharField(max_length=30, choices=NotificationKind.choices)
    message = models.CharField(max_length=500)
    application = models.ForeignKey(
        Application,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="notifications",
    )
    # Empty until the recipient reads it.
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            # "My unread notifications" is the common query.
            models.Index(fields=["recipient", "read_at"], name="notification_recipient_read"),
        ]

    def __str__(self):
        return f"{self.kind} for {self.recipient}"
