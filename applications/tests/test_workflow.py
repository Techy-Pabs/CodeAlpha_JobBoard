"""Every allowed and refused status move, who may make it, and the history."""

import itertools

import pytest
from django.urls import reverse

from applications.models import Application, ApplicationStatus
from applications.workflow import CANDIDATE_MOVES, EMPLOYER_MOVES, FINAL

pytestmark = pytest.mark.django_db

STATUSES = list(ApplicationStatus.values)

EMPLOYER_ALLOWED = {
    ("submitted", "reviewing"),
    ("submitted", "rejected"),
    ("reviewing", "shortlisted"),
    ("reviewing", "rejected"),
    ("shortlisted", "interview"),
    ("shortlisted", "rejected"),
    ("interview", "offered"),
    ("interview", "rejected"),
}
WITHDRAWABLE = {"submitted", "reviewing", "shortlisted", "interview"}


def status_url(application):
    return reverse("application-status", args=[application.id])


def withdraw_url(application):
    return reverse("application-withdraw", args=[application.id])


def assert_history_matches(application):
    """History starts at blank, each step follows the last, and ends at the status."""
    application.refresh_from_db()
    steps = list(application.status_changes.order_by("created_at", "id"))
    assert steps[0].from_status == ""
    for before, after in itertools.pairwise(steps):
        assert after.from_status == before.to_status
    assert steps[-1].to_status == application.status


def test_tables_match_the_spec():
    """The rules in workflow.py are exactly the ones agreed, nothing more."""
    assert {(str(a), str(b)) for a, tos in EMPLOYER_MOVES.items() for b in tos} == (
        EMPLOYER_ALLOWED
    )
    assert {str(s) for s in CANDIDATE_MOVES} == WITHDRAWABLE
    assert {str(s) for s in FINAL} == {"offered", "rejected", "withdrawn"}


# --- employer moves: every (from, to) pair -----------------------------------------


@pytest.mark.parametrize(("current", "wanted"), list(itertools.product(STATUSES, STATUSES)))
def test_employer_move(api_client, employer_user, make_application, current, wanted):
    application = make_application(current)
    api_client.force_authenticate(employer_user)
    body = {"to_status": wanted, "note": "Checked"}
    response = api_client.post(status_url(application), body, format="json")

    application.refresh_from_db()
    if (current, wanted) in EMPLOYER_ALLOWED:
        assert response.status_code == 200, response.data
        assert response.data["status"] == wanted
        assert application.status == wanted
        last = application.status_changes.order_by("-created_at", "-id").first()
        assert (last.from_status, last.to_status, last.note) == (current, wanted, "Checked")
        assert last.changed_by == employer_user
    else:
        assert response.status_code == 400
        allowed = [b for (a, b) in sorted(EMPLOYER_ALLOWED) if a == current]
        assert sorted(response.data["allowed_moves"]) == allowed
        assert response.data["current_status"] == current
        assert application.status == current  # unchanged
        if current in {"offered", "rejected", "withdrawn"}:
            assert "final" in response.data["detail"]
    assert_history_matches(application)


def test_refusal_lists_allowed_moves(api_client, employer_user, application):
    api_client.force_authenticate(employer_user)
    response = api_client.post(status_url(application), {"to_status": "offered"}, format="json")
    assert response.status_code == 400
    assert response.data["detail"] == (
        "Cannot move an application from submitted to offered. Allowed: reviewing, rejected."
    )
    assert response.data["allowed_moves"] == ["reviewing", "rejected"]


def test_unknown_status_is_400(api_client, employer_user, application):
    api_client.force_authenticate(employer_user)
    response = api_client.post(status_url(application), {"to_status": "hired"}, format="json")
    assert response.status_code == 400
    assert "to_status" in response.data


def test_note_is_optional_and_limited(api_client, employer_user, application):
    api_client.force_authenticate(employer_user)
    long_note = {"to_status": "reviewing", "note": "x" * 501}
    assert api_client.post(status_url(application), long_note, format="json").status_code == 400
    ok = api_client.post(status_url(application), {"to_status": "reviewing"}, format="json")
    assert ok.status_code == 200


def test_full_happy_path_keeps_history_in_step(api_client, employer_user, application):
    api_client.force_authenticate(employer_user)
    for wanted in ["reviewing", "shortlisted", "interview", "offered"]:
        response = api_client.post(status_url(application), {"to_status": wanted}, format="json")
        assert response.status_code == 200
        assert response.data["history"][-1]["to_status"] == response.data["status"] == wanted
        assert_history_matches(application)
    assert [h["to_status"] for h in response.data["history"]] == [
        "submitted",
        "reviewing",
        "shortlisted",
        "interview",
        "offered",
    ]
    assert response.data["allowed_moves"] == []


# --- who may change the status -------------------------------------------------------


def test_candidate_cannot_use_status_endpoint(api_client, candidate_user, application):
    api_client.force_authenticate(candidate_user)
    response = api_client.post(status_url(application), {"to_status": "offered"}, format="json")
    assert response.status_code == 403
    application.refresh_from_db()
    assert application.status == "submitted"


def test_other_employer_gets_404_on_status(api_client, other_employer, application):
    api_client.force_authenticate(other_employer.user)
    response = api_client.post(status_url(application), {"to_status": "reviewing"}, format="json")
    assert response.status_code == 404


def test_other_candidate_gets_role_403_on_status(api_client, other_candidate, application):
    """Wrong role is refused before the lookup, so the answer is the same 403
    whether or not the application exists: nothing is revealed."""
    api_client.force_authenticate(other_candidate.user)
    body = {"to_status": "reviewing"}
    assert api_client.post(status_url(application), body, format="json").status_code == 403
    missing = reverse("application-status", args=[999_999])
    assert api_client.post(missing, body, format="json").status_code == 403


def test_anonymous_gets_401_on_status(api_client, application):
    response = api_client.post(status_url(application), {"to_status": "reviewing"}, format="json")
    assert response.status_code == 401


# --- withdraw ---------------------------------------------------------------------------


@pytest.mark.parametrize("current", STATUSES)
def test_withdraw_from_each_status(api_client, candidate_user, make_application, current):
    application = make_application(current)
    api_client.force_authenticate(candidate_user)
    response = api_client.post(withdraw_url(application), {"note": "Took another offer"})
    application.refresh_from_db()
    if current in WITHDRAWABLE:
        assert response.status_code == 200, response.data
        assert application.status == "withdrawn"
        last = application.status_changes.order_by("-created_at", "-id").first()
        assert (last.from_status, last.to_status) == (current, "withdrawn")
        assert last.changed_by == candidate_user
        assert last.note == "Took another offer"
    else:
        assert response.status_code == 400
        assert response.data["allowed_moves"] == []
        assert application.status == current
    assert_history_matches(application)


def test_withdraw_without_body(api_client, candidate_user, application):
    api_client.force_authenticate(candidate_user)
    assert api_client.post(withdraw_url(application)).status_code == 200


def test_employer_cannot_withdraw(api_client, employer_user, application):
    api_client.force_authenticate(employer_user)
    assert api_client.post(withdraw_url(application)).status_code == 403
    application.refresh_from_db()
    assert application.status == "submitted"


def test_other_candidate_gets_404_on_withdraw(api_client, other_candidate, application):
    api_client.force_authenticate(other_candidate.user)
    assert api_client.post(withdraw_url(application)).status_code == 404


def test_other_employer_gets_role_403_on_withdraw(api_client, other_employer, application):
    api_client.force_authenticate(other_employer.user)
    assert api_client.post(withdraw_url(application)).status_code == 403
    assert api_client.post(reverse("application-withdraw", args=[999_999])).status_code == 403


def test_anonymous_gets_401_on_withdraw(api_client, application):
    assert api_client.post(withdraw_url(application)).status_code == 401


# --- locking ------------------------------------------------------------------------------


def test_move_locks_the_row(api_client, employer_user, application):
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    api_client.force_authenticate(employer_user)
    with CaptureQueriesContext(connection) as ctx:
        api_client.post(status_url(application), {"to_status": "reviewing"}, format="json")
    sql = [q["sql"] for q in ctx.captured_queries]
    locks = [s for s in sql if "FOR UPDATE" in s and '"applications_application"' in s]
    assert locks, "the application row must be read with SELECT ... FOR UPDATE"
    lock_at = sql.index(locks[0])
    update_at = next(i for i, s in enumerate(sql) if s.startswith("UPDATE"))
    insert_at = next(i for i, s in enumerate(sql) if "INSERT" in s and "statuschange" in s)
    assert lock_at < update_at < insert_at


def test_status_and_history_roll_back_together(employer_user, application, monkeypatch):
    """If writing the history row fails, the status change is undone too."""
    from applications import workflow
    from applications.models import ApplicationStatusChange

    def boom(**kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(ApplicationStatusChange.objects, "create", boom)
    with pytest.raises(RuntimeError):
        workflow.move(application.pk, "reviewing", by=employer_user, moves=workflow.EMPLOYER_MOVES)
    assert Application.objects.get(pk=application.pk).status == "submitted"
