import pytest

from applications.models import Application
from notifications.models import Notification, NotificationKind

pytestmark = pytest.mark.django_db


def test_notification_starts_unread(employer_user):
    note = Notification.objects.create(
        recipient=employer_user, kind=NotificationKind.NEW_APPLICATION, message="New applicant"
    )
    assert note.read_at is None
    assert note.application is None


def test_notification_can_point_at_an_application(employer_user, job, candidate, resume):
    app = Application.objects.create(job=job, candidate=candidate, resume=resume)
    note = Notification.objects.create(
        recipient=candidate.user,
        kind=NotificationKind.STATUS_CHANGED,
        message="Your application is being reviewed",
        application=app,
    )
    assert list(app.notifications.all()) == [note]
