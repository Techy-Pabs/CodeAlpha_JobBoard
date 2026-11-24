from rest_framework import serializers

from accounts.serializers import ProfileSerializerMixin

from .models import CANDIDATE_REQUIRED_FIELDS, CandidateProfile


class MyCandidateProfileSerializer(ProfileSerializerMixin, serializers.ModelSerializer):
    """The logged-in candidate's own profile (GET and PATCH)."""

    required_to_complete = CANDIDATE_REQUIRED_FIELDS

    role = serializers.CharField(source="user.role", read_only=True)
    username = serializers.CharField(source="user.username", read_only=True)
    is_complete = serializers.BooleanField(read_only=True)

    class Meta:
        model = CandidateProfile
        fields = [
            "id",
            "role",
            "username",
            "headline",
            "location",
            "skills",
            "is_complete",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]
