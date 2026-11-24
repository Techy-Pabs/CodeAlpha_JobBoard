"""Applying and moving an application notify the right person, only on commit."""

from unittest import mock

import pytest
from django.core import mail
from django.db import DatabaseError, transaction
from django.urls import reverse

from applications import workflow
from applications.models import Application, ApplicationStatusChange
from notifications.models import Notification

pytestmark = pytest.mark.django_db


def apply_url(job):
    return reverse("job-apply", args=[job.id])


@pytest.fixture
def as_candidate(api_client, candidate_user):
    api_client.force_authenticate(candidate_user)
    return api_client


def test_applying_notifies_the_employer(
    as_candidate, open_job, resume, employer_user, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True) as callbacks:
        response = as_candidate.post(apply_url(open_job), {}, format="json")
    assert response.status_code == 201
    assert len(callbacks) == 2  # the notification and the email

    [note] = Notification.objects.all()
    assert note.recipient == employer_user
    assert note.kind == "new_application"
    assert note.application_id == response.data["id"]
    assert note.message == "ada applied to Backend Developer."
    assert note.read_at is None

    [email] = mail.outbox
    assert email.to == ["hr@acme.example"]
    assert email.subject == "New application: Backend Developer"
    assert email.body == note.message


def test_nothing_is_sent_before_commit(as_candidate, open_job, resume):
    # Without running the on-commit callbacks (the test transaction never
    # commits), the application exists but nobody has been told yet.
    response = as_candidate.post(apply_url(open_job), {}, format="json")
    assert response.status_code == 201
    assert not Notification.objects.exists()
    assert mail.outbox == []


def test_employer_move_notifies_the_candidate(
    application, employer_user, candidate_user, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        workflow.move(application.pk, "reviewing", by=employer_user, moves=workflow.EMPLOYER_MOVES)
    [note] = Notification.objects.all()
    assert note.recipient == candidate_user
    assert note.kind == "status_changed"
    assert note.message == (
        "Your application to Backend Developer at Acme Ltd moved from submitted to reviewing."
    )
    [email] = mail.outbox
    assert email.to == ["ada@example.com"]


def test_withdraw_notifies_the_employer(
    api_client, application, candidate_user, employer_user, django_capture_on_commit_callbacks
):
    api_client.force_authenticate(candidate_user)
    with django_capture_on_commit_callbacks(execute=True):
        response = api_client.post(
            reverse("application-withdraw", args=[application.id]), {}, format="json"
        )
    assert response.status_code == 200
    [note] = Notification.objects.all()
    assert note.recipient == employer_user
    assert note.message == "ada withdrew their application to Backend Developer."
    assert mail.outbox[0].to == ["hr@acme.example"]


def test_refused_move_sends_nothing(application, employer_user, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True) as callbacks:
        with pytest.raises(workflow.InvalidMove):
            workflow.move(
                application.pk, "offered", by=employer_user, moves=workflow.EMPLOYER_MOVES
            )
    assert callbacks == []
    assert not Notification.objects.exists()
    assert mail.outbox == []


def test_failed_apply_sends_nothing(
    as_candidate, open_job, resume, django_capture_on_commit_callbacks
):
    """The history row fails after the notification was queued: all rolled back."""
    boom = DatabaseError("disk full")
    with django_capture_on_commit_callbacks(execute=True) as callbacks:
        with mock.patch.object(ApplicationStatusChange.objects, "create", side_effect=boom):
            with pytest.raises(DatabaseError):
                as_candidate.post(apply_url(open_job), {}, format="json")
    assert callbacks == []
    assert not Application.objects.exists()
    assert not Notification.objects.exists()
    assert mail.outbox == []


def test_failed_move_sends_nothing(application, employer_user, django_capture_on_commit_callbacks):
    boom = DatabaseError("disk full")
    with django_capture_on_commit_callbacks(execute=True) as callbacks:
        with mock.patch.object(ApplicationStatusChange.objects, "create", side_effect=boom):
            with pytest.raises(DatabaseError):
                workflow.move(
                    application.pk, "reviewing", by=employer_user, moves=workflow.EMPLOYER_MOVES
                )
    assert callbacks == []
    application.refresh_from_db()
    assert application.status == "submitted"
    assert not Notification.objects.exists()
    assert mail.outbox == []


def test_move_inside_a_rolled_back_transaction_sends_nothing(
    application, employer_user, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True) as callbacks:
        with pytest.raises(RuntimeError):
            with transaction.atomic():
                workflow.move(
                    application.pk, "reviewing", by=employer_user, moves=workflow.EMPLOYER_MOVES
                )
                raise RuntimeError("something later in the same transaction failed")
    assert callbacks == []
    assert not Notification.objects.exists()


def test_failing_email_backend_does_not_break_applying(
    settings, as_candidate, open_job, resume, caplog, django_capture_on_commit_callbacks
):
    settings.EMAIL_BACKEND = "notifications.tests.backends.FailingEmailBackend"
    with django_capture_on_commit_callbacks(execute=True):
        response = as_candidate.post(apply_url(open_job), {}, format="json")
    assert response.status_code == 201
    assert Application.objects.count() == 1
    # The in-app notification still exists; the email failure is logged.
    assert Notification.objects.count() == 1
    assert "Could not send new_application email" in caplog.text
    assert "SMTP server unreachable" in caplog.text


def test_failing_email_backend_does_not_break_a_move(
    settings, api_client, application, employer_user, caplog, django_capture_on_commit_callbacks
):
    settings.EMAIL_BACKEND = "notifications.tests.backends.FailingEmailBackend"
    api_client.force_authenticate(employer_user)
    with django_capture_on_commit_callbacks(execute=True):
        response = api_client.post(
            reverse("application-status", args=[application.id]),
            {"to_status": "reviewing"},
            format="json",
        )
    assert response.status_code == 200
    assert response.data["status"] == "reviewing"
    assert Notification.objects.count() == 1
    assert "Could not send status_changed email" in caplog.text


def test_user_without_email_gets_only_the_in_app_notification(
    as_candidate, open_job, resume, employer_user, django_capture_on_commit_callbacks
):
    employer_user.email = ""
    employer_user.save()
    with django_capture_on_commit_callbacks(execute=True):
        as_candidate.post(apply_url(open_job), {}, format="json")
    assert Notification.objects.filter(recipient=employer_user).count() == 1
    assert mail.outbox == []
