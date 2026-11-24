import re

from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from .models import Job

CURRENCY = re.compile(r"^[A-Z]{3}$")
SALARY_RANGE = "Maximum salary must be at least the minimum salary."


class JobSerializer(serializers.ModelSerializer):
    company_id = serializers.IntegerField(source="employer_id", read_only=True)
    company_name = serializers.CharField(source="employer.company_name", read_only=True)
    company_location = serializers.CharField(source="employer.location", read_only=True)
    is_open = serializers.BooleanField(read_only=True)
    application_count = serializers.SerializerMethodField(
        help_text="Number of applications. Only included for the employer who posted the job."
    )

    class Meta:
        model = Job
        fields = [
            "id",
            "title",
            "description",
            "location",
            "job_type",
            "work_mode",
            "experience_level",
            "salary_min",
            "salary_max",
            "salary_currency",
            "skills",
            "status",
            "closes_at",
            "is_open",
            "company_id",
            "company_name",
            "company_location",
            "application_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def _is_owner(self, job):
        request = self.context.get("request")
        user = getattr(request, "user", None)
        return bool(user and user.is_authenticated and job.employer.user_id == user.id)

    @extend_schema_field(OpenApiTypes.INT)
    def get_application_count(self, job):
        if not self._is_owner(job):
            return None  # dropped in to_representation; no query is run
        # The list and detail querysets annotate this. A job just created or
        # updated may not have it, so count directly then.
        count = getattr(job, "application_count", None)
        return job.applications.count() if count is None else count

    def to_representation(self, job):
        data = super().to_representation(job)
        if not self._is_owner(job):
            data.pop("application_count", None)
        return data

    def validate_salary_currency(self, value):
        value = value.strip().upper()
        if not CURRENCY.match(value):
            raise serializers.ValidationError("Use a three-letter currency code, e.g. NGN or USD.")
        return value

    def validate_closes_at(self, value):
        if value is not None and value <= timezone.now():
            raise serializers.ValidationError("The closing date must be in the future.")
        return value

    def validate(self, attrs):
        # On PATCH, compare with the stored value for the bound that wasn't sent.
        low = attrs.get("salary_min", getattr(self.instance, "salary_min", None))
        high = attrs.get("salary_max", getattr(self.instance, "salary_max", None))
        if low is not None and high is not None and high < low:
            raise serializers.ValidationError({"salary_max": [SALARY_RANGE]})
        return attrs
