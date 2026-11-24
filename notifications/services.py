"""Tell people about applications: an in-app notification plus an email.

Both are sent only after the surrounding transaction commits
(transaction.on_commit). If the save that triggered them fails and rolls
back, nobody is told about something that never happened.

An email that can't be sent is logged and skipped. It never fails the
request, because the application or status change has already been saved.
"""

import logging

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction

from .models import Notification, NotificationKind

logger = logging.getLogger(__name__)


def notify(*, recipient, kind, subject, message, application=None):
    """Queue a notification and an email for recipient, sent on commit."""
    # Copy plain values now: the objects may change before the commit.
    recipient_id = recipient.pk
    email = recipient.email
    application_id = application.pk if application else None

    def create_notification():
        Notification.objects.create(
            recipient_id=recipient_id,
            kind=kind,
            message=message,
            application_id=application_id,
        )

    def send_email():
        if not email:
            return
        try:
            send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [email])
        except Exception:
            # Never break the request over an email. The in-app notification
            # still exists, and the log shows what went wrong.
            logger.exception(
                "Could not send %s email to user %s (application %s)",
                kind,
                recipient_id,
                application_id,
            )

    # robust=True: if creating the notification fails after the commit, the
    # error is logged and the request still succeeds (the save it reports on
    # is already in the database).
    transaction.on_commit(create_notification, robust=True)
    transaction.on_commit(send_email, robust=True)


def notify_new_application(application):
    """Tell the job's employer that someone applied."""
    job = application.job
    applicant = application.candidate.user.username
    notify(
        recipient=job.employer.user,
        kind=NotificationKind.NEW_APPLICATION,
        subject=f"New application: {job.title}",
        message=f"{applicant} applied to {job.title}.",
        application=application,
    )


def notify_status_change(application, from_status, to_status, by):
    """Tell the other side that an application moved.

    The employer moved it: the candidate hears about it. The candidate
    withdrew: the employer hears about it. A change by anyone else (an admin,
    say) goes to the candidate, whose application it is.
    """
    job = application.job
    employer_user = job.employer.user
    candidate_user = application.candidate.user
    by_id = by.pk if by else None

    if by_id == candidate_user.pk:
        notify(
            recipient=employer_user,
            kind=NotificationKind.STATUS_CHANGED,
            subject=f"Application withdrawn: {job.title}",
            message=f"{candidate_user.username} withdrew their application to {job.title}.",
            application=application,
        )
        return

    company = job.employer.company_name or "the employer"
    notify(
        recipient=candidate_user,
        kind=NotificationKind.STATUS_CHANGED,
        subject=f"Your application to {job.title}: {to_status}",
        message=(
            f"Your application to {job.title} at {company} moved from {from_status} to {to_status}."
        ),
        application=application,
    )
