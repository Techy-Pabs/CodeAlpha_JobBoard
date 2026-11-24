from django.urls import reverse
from rest_framework import serializers

from accounts.serializers import ProfileSerializerMixin

from .files import check_resume_upload
from .models import CANDIDATE_REQUIRED_FIELDS, CandidateProfile, Resume


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


class ResumeSerializer(serializers.ModelSerializer):
    """A resume as listed to its owner. The storage path is never shown."""

    download_url = serializers.SerializerMethodField()

    class Meta:
        model = Resume
        fields = [
            "id",
            "original_filename",
            "size_bytes",
            "is_default",
            "uploaded_at",
            "download_url",
        ]
        read_only_fields = fields

    def get_download_url(self, resume) -> str:
        path = reverse("resume-download", args=[resume.pk])
        request = self.context.get("request")
        return request.build_absolute_uri(path) if request else path


class ResumeUploadSerializer(serializers.Serializer):
    file = serializers.FileField(
        help_text="PDF or DOCX, up to 5 MB. The content is checked, not just the extension."
    )

    def validate_file(self, upload):
        check_resume_upload(upload)
        return upload
