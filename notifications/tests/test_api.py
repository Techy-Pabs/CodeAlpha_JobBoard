"""GET /api/me/notifications/, and marking one or all as read."""

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from notifications.models import Notification

pytestmark = pytest.mark.django_db

LIST = reverse("my-notification-list")
READ_ALL = reverse("my-notification-read-all")


def read_url(note):
    return reverse("my-notification-read", args=[note.id])


@pytest.fixture
def make_note(employer_user):
    def make(recipient=employer_user, read=False, message="New applicant"):
        return Notification.objects.create(
            recipient=recipient,
            kind="new_application",
            message=message,
            read_at=timezone.now() if read else None,
        )

    return make


@pytest.fixture
def as_employer(api_client, employer_user):
    api_client.force_authenticate(employer_user)
    return api_client


def ids(response):
    return [item["id"] for item in response.data["results"]]


def test_list_needs_login(api_client):
    assert api_client.get(LIST).status_code == 401


def test_list_shows_only_own_newest_first(as_employer, make_note, candidate_user):
    first = make_note(message="first")
    second = make_note(message="second")
    make_note(recipient=candidate_user, message="someone else's")
    response = as_employer.get(LIST)
    assert response.status_code == 200
    assert response.data["count"] == 2
    assert ids(response) == [second.id, first.id]
    item = response.data["results"][0]
    assert set(item) == {
        "id",
        "kind",
        "message",
        "application_id",
        "is_read",
        "read_at",
        "created_at",
    }
    assert item["is_read"] is False


def test_same_time_ties_break_newest_id_first(as_employer, make_note):
    a, b = make_note(), make_note()
    Notification.objects.update(created_at=timezone.now())
    assert ids(as_employer.get(LIST)) == [b.id, a.id]


@pytest.mark.parametrize(
    ("value", "expect_unread"), [("true", True), ("1", True), ("false", False)]
)
def test_unread_filter(as_employer, make_note, value, expect_unread):
    unread = make_note()
    read = make_note(read=True)
    response = as_employer.get(LIST, {"unread": value})
    assert ids(response) == ([unread.id] if expect_unread else [read.id])


def test_bad_unread_value_is_400(as_employer):
    response = as_employer.get(LIST, {"unread": "maybe"})
    assert response.status_code == 400
    assert "unread" in response.data


def test_list_is_paginated(as_employer, make_note):
    for _ in range(21):
        make_note()
    response = as_employer.get(LIST)
    assert response.data["count"] == 21
    assert len(response.data["results"]) == 20
    assert response.data["next"] is not None


def test_mark_one_read(as_employer, make_note):
    note = make_note()
    response = as_employer.post(read_url(note))
    assert response.status_code == 200
    assert response.data["is_read"] is True
    note.refresh_from_db()
    assert note.read_at is not None


def test_marking_again_keeps_first_read_time(as_employer, make_note):
    note = make_note()
    earlier = timezone.now() - timedelta(days=1)
    Notification.objects.filter(pk=note.pk).update(read_at=earlier)
    as_employer.post(read_url(note))
    note.refresh_from_db()
    assert note.read_at == earlier


def test_cannot_mark_someone_elses_read(as_employer, make_note, candidate_user):
    theirs = make_note(recipient=candidate_user)
    assert as_employer.post(read_url(theirs)).status_code == 404
    theirs.refresh_from_db()
    assert theirs.read_at is None


def test_read_needs_login(api_client, make_note):
    assert api_client.post(read_url(make_note())).status_code == 401


def test_read_all_marks_only_own_unread(as_employer, make_note, candidate_user):
    make_note()
    make_note()
    already = make_note(read=True)
    before = Notification.objects.get(pk=already.pk).read_at
    theirs = make_note(recipient=candidate_user)

    response = as_employer.post(READ_ALL)
    assert response.status_code == 200
    assert response.data == {"marked_read": 2}
    assert not Notification.objects.filter(recipient__username="acme", read_at=None).exists()
    assert Notification.objects.get(pk=already.pk).read_at == before
    theirs.refresh_from_db()
    assert theirs.read_at is None
    assert as_employer.post(READ_ALL).data == {"marked_read": 0}


def test_read_all_needs_login(api_client):
    assert api_client.post(READ_ALL).status_code == 401


def test_candidates_have_notifications_too(api_client, candidate_user, make_note):
    note = make_note(recipient=candidate_user)
    api_client.force_authenticate(candidate_user)
    assert ids(api_client.get(LIST)) == [note.id]
