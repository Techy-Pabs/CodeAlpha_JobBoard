from rest_framework.permissions import BasePermission


class IsJobOwner(BasePermission):
    """Object-level: the logged-in employer posted this job."""

    message = "Only the employer who posted this job can do that."

    def has_object_permission(self, request, view, obj):
        return obj.employer.user_id == request.user.id
