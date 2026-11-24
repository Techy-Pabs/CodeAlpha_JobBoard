from rest_framework import serializers

from accounts.serializers import ProfileSerializerMixin

from .models import EMPLOYER_REQUIRED_FIELDS, EmployerProfile


class MyEmployerProfileSerializer(ProfileSerializerMixin, serializers.ModelSerializer):
    """The logged-in employer's own company profile (GET and PATCH)."""

    required_to_complete = EMPLOYER_REQUIRED_FIELDS

    role = serializers.CharField(source="user.role", read_only=True)
    username = serializers.CharField(source="user.username", read_only=True)
    is_complete = serializers.BooleanField(read_only=True)

    class Meta:
        model = EmployerProfile
        fields = [
            "id",
            "role",
            "username",
            "company_name",
            "website",
            "location",
            "description",
            "is_complete",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class CompanySerializer(serializers.ModelSerializer):
    """An employer's public profile. No account details (username, email)."""

    open_jobs_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = EmployerProfile
        fields = ["id", "company_name", "website", "location", "description", "open_jobs_count"]
        read_only_fields = fields
