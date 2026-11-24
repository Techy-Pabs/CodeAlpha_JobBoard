from rest_framework.permissions import BasePermission


class IsJobEmployer(BasePermission):
    """Object-level: the application is for one of this employer's jobs."""

    message = (
        "Only the employer who posted this job can change the status. "
        "Candidates can withdraw instead."
    )

    def has_object_permission(self, request, view, obj):
        return obj.job.employer.user_id == request.user.id


class IsApplicant(BasePermission):
    """Object-level: the logged-in candidate made this application."""

    message = "Only the candidate who applied can withdraw an application."

    def has_object_permission(self, request, view, obj):
        return obj.candidate.user_id == request.user.id
