from rest_framework.permissions import BasePermission


class IsEmployer(BasePermission):
    """Logged in with the employer role."""

    message = "Only employer accounts can do this."

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.is_employer)


class IsCandidate(BasePermission):
    """Logged in with the candidate role."""

    message = "Only candidate accounts can do this."

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.is_candidate)
