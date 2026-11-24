"""Which status moves are allowed, and the one function that makes them.

Every status change goes through move(), which locks the application row and
writes the new status and its history row in one transaction. So the history
always ends at the current status, even when two people act at once.
"""

from django.db import transaction
from rest_framework import status as http
from rest_framework.exceptions import APIException

from .models import Application, ApplicationStatus, ApplicationStatusChange

S = ApplicationStatus

# What the job's employer may do from each status.
EMPLOYER_MOVES = {
    S.SUBMITTED: (S.REVIEWING, S.REJECTED),
    S.REVIEWING: (S.SHORTLISTED, S.REJECTED),
    S.SHORTLISTED: (S.INTERVIEW, S.REJECTED),
    S.INTERVIEW: (S.OFFERED, S.REJECTED),
}

# What the candidate may do: withdraw, until a final decision.
CANDIDATE_MOVES = {
    status: (S.WITHDRAWN,) for status in (S.SUBMITTED, S.REVIEWING, S.SHORTLISTED, S.INTERVIEW)
}

FINAL = frozenset({S.OFFERED, S.REJECTED, S.WITHDRAWN})


class InvalidMove(APIException):
    """400 that says where the application is and where it may go."""

    status_code = http.HTTP_400_BAD_REQUEST
    default_code = "invalid_move"

    def __init__(self, current, wanted, allowed):
        if current in FINAL:
            message = f"This application is {current}, which is final. It cannot be moved."
        elif not allowed:
            message = f"You cannot move an application that is {current}."
        else:
            message = (
                f"Cannot move an application from {current} to {wanted}. "
                f"Allowed: {', '.join(allowed)}."
            )
        super().__init__(
            {
                "detail": message,
                "current_status": current,
                "allowed_moves": list(allowed),
            }
        )


def move(application_id, to_status, *, by, note="", moves):
    """Move one application to to_status if `moves` allows it from its status now.

    The row is locked (SELECT ... FOR UPDATE) and its status re-read under the
    lock, so two requests can't both move it from the same old status.
    """
    with transaction.atomic():
        application = Application.objects.select_for_update().get(pk=application_id)
        current = application.status
        allowed = tuple(str(s) for s in moves.get(current, ()))
        if to_status not in allowed:
            raise InvalidMove(current, to_status, allowed)
        application.status = to_status
        application.save(update_fields=["status", "updated_at"])
        ApplicationStatusChange.objects.create(
            application=application,
            from_status=current,
            to_status=to_status,
            changed_by=by,
            note=note,
        )
    return application


def allowed_moves_for(application, user):
    """The moves this user could make right now (shown on the detail page)."""
    if application.job.employer.user_id == user.id:
        return [str(s) for s in EMPLOYER_MOVES.get(application.status, ())]
    if application.candidate.user_id == user.id:
        return [str(s) for s in CANDIDATE_MOVES.get(application.status, ())]
    return []
