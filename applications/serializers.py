from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from candidates.models import CandidateProfile, Resume
from candidates.serializers import ResumeSerializer

from .models import COVER_LETTER_MAX, Application, ApplicationStatus, ApplicationStatusChange
from .workflow import allowed_moves_for


class ApplySerializer(serializers.Serializer):
    resume_id = serializers.IntegerField(
        required=False,
        allow_null=True,
        help_text="One of your resumes. Leave out to use your default resume.",
    )
    cover_letter = serializers.CharField(
        required=False, allow_blank=True, max_length=COVER_LETTER_MAX, default=""
    )


class StatusChangeRequestSerializer(serializers.Serializer):
    to_status = serializers.ChoiceField(choices=ApplicationStatus.choices)
    note = serializers.CharField(required=False, allow_blank=True, max_length=500, default="")


class WithdrawRequestSerializer(serializers.Serializer):
    note = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=500,
        default="",
        help_text="Optional reason, visible to the employer.",
    )


class StatusChangeSerializer(serializers.ModelSerializer):
    changed_by = serializers.CharField(source="changed_by.username", default=None, read_only=True)

    class Meta:
        model = ApplicationStatusChange
        fields = ["from_status", "to_status", "changed_by", "note", "created_at"]
        read_only_fields = fields


class ApplicantSerializer(serializers.ModelSerializer):
    """What the employer sees about the person who applied."""

    username = serializers.CharField(source="user.username", read_only=True)

    class Meta:
        model = CandidateProfile
        fields = ["id", "username", "headline", "location", "skills"]
        read_only_fields = fields


class SentResumeSerializer(ResumeSerializer):
    class Meta(ResumeSerializer.Meta):
        model = Resume
        fields = ["id", "original_filename", "size_bytes", "download_url"]
        read_only_fields = fields


class MyApplicationSerializer(serializers.ModelSerializer):
    """A candidate's own application, in their list."""

    job_id = serializers.IntegerField(read_only=True)
    job_title = serializers.CharField(source="job.title", read_only=True)
    company_id = serializers.IntegerField(source="job.employer_id", read_only=True)
    company_name = serializers.CharField(source="job.employer.company_name", read_only=True)

    class Meta:
        model = Application
        fields = [
            "id",
            "job_id",
            "job_title",
            "company_id",
            "company_name",
            "status",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class JobApplicationSerializer(serializers.ModelSerializer):
    """An application in the employer's list for one job."""

    candidate = ApplicantSerializer(read_only=True)
    resume = SentResumeSerializer(read_only=True)

    class Meta:
        model = Application
        fields = ["id", "candidate", "resume", "cover_letter", "status", "created_at", "updated_at"]
        read_only_fields = fields


class ApplicationDetailSerializer(serializers.ModelSerializer):
    """One application with its full status history.

    Seen by the candidate who applied and the employer who posted the job.
    """

    job_id = serializers.IntegerField(read_only=True)
    job_title = serializers.CharField(source="job.title", read_only=True)
    company_id = serializers.IntegerField(source="job.employer_id", read_only=True)
    company_name = serializers.CharField(source="job.employer.company_name", read_only=True)
    candidate = ApplicantSerializer(read_only=True)
    resume = SentResumeSerializer(read_only=True)
    history = StatusChangeSerializer(source="status_changes", many=True, read_only=True)
    allowed_moves = serializers.SerializerMethodField(
        help_text="Statuses you could move this application to now."
    )

    class Meta:
        model = Application
        fields = [
            "id",
            "job_id",
            "job_title",
            "company_id",
            "company_name",
            "candidate",
            "resume",
            "cover_letter",
            "status",
            "allowed_moves",
            "history",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    @extend_schema_field(serializers.ListField(child=serializers.CharField()))
    def get_allowed_moves(self, application):
        return allowed_moves_for(application, self.context["request"].user)


class InvalidMoveSerializer(serializers.Serializer):
    """Body of a 400 for a refused status move (for the API docs)."""

    detail = serializers.CharField()
    current_status = serializers.CharField()
    allowed_moves = serializers.ListField(child=serializers.CharField())
