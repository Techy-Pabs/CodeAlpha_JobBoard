from django.db.models import Count, IntegerField, OuterRef, Q, Subquery
from django.db.models.deletion import ProtectedError
from django.db.models.functions import Coalesce
from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_view
from rest_framework import viewsets
from rest_framework.permissions import AllowAny, IsAuthenticated

from accounts.permissions import IsEmployer
from applications.models import Application
from config.exceptions import BadRequest, Conflict

from .filters import JobSearchFilter
from .models import Job, JobStatus, open_jobs_q
from .permissions import IsJobOwner
from .serializers import JobSerializer

PROFILE_INCOMPLETE = (
    "Complete your company profile (company_name, location and description) "
    "at /api/me/profile/ before posting a job."
)
CANNOT_DELETE = (
    "Only a draft job with no applications can be deleted. "
    "Close it instead: PATCH the job with status=closed."
)

NOT_FOUND = OpenApiResponse(description="Job not found or not visible to you.")
NOT_LOGGED_IN = OpenApiResponse(description="Not logged in.")
NOT_EMPLOYER = OpenApiResponse(description="Not an employer, or not your job.")
BAD = OpenApiResponse(description="Validation error.")


def application_count():
    """Applications per job as a subquery, so the list needs no GROUP BY."""
    counts = (
        Application.objects.filter(job=OuterRef("pk"))
        .order_by()
        .values("job")
        .annotate(n=Count("pk"))
        .values("n")
    )
    return Coalesce(Subquery(counts, output_field=IntegerField()), 0)


@extend_schema_view(
    list=extend_schema(
        summary="List open jobs (public; employers also see all their own)",
        responses={200: JobSerializer(many=True), 400: BAD},
    ),
    retrieve=extend_schema(
        summary="Job detail (public for open jobs)",
        responses={200: JobSerializer, 404: NOT_FOUND},
    ),
    create=extend_schema(
        summary="Post a job (employers with a complete profile)",
        responses={
            201: JobSerializer,
            400: OpenApiResponse(description="Validation error, or company profile incomplete."),
            401: NOT_LOGGED_IN,
            403: NOT_EMPLOYER,
        },
    ),
    update=extend_schema(
        summary="Replace a job (its employer only)",
        responses={
            200: JobSerializer,
            400: BAD,
            401: NOT_LOGGED_IN,
            403: NOT_EMPLOYER,
            404: NOT_FOUND,
        },
    ),
    partial_update=extend_schema(
        summary="Update a job (its employer only)",
        responses={
            200: JobSerializer,
            400: BAD,
            401: NOT_LOGGED_IN,
            403: NOT_EMPLOYER,
            404: NOT_FOUND,
        },
    ),
    destroy=extend_schema(
        summary="Delete a draft job with no applications (its employer only)",
        responses={
            204: OpenApiResponse(description="Deleted."),
            401: NOT_LOGGED_IN,
            403: NOT_EMPLOYER,
            404: NOT_FOUND,
            409: OpenApiResponse(description="Not a draft, or has applications: close it instead."),
        },
    ),
)
class JobViewSet(viewsets.ModelViewSet):
    """Job posts. Hidden jobs (drafts, closed, past closes_at) return 404 to
    everyone except the employer who posted them."""

    serializer_class = JobSerializer
    filter_backends = [JobSearchFilter]

    def get_permissions(self):
        if self.action in ("list", "retrieve"):
            return [AllowAny()]
        return [IsAuthenticated(), IsEmployer(), IsJobOwner()]

    def get_queryset(self):
        user = self.request.user
        is_employer = user.is_authenticated and user.is_employer
        visible = open_jobs_q()
        if is_employer:
            visible |= Q(employer__user=user)  # own drafts, closed and expired jobs
        queryset = Job.objects.filter(visible).select_related("employer")
        if is_employer:
            # Only employers can own jobs, so only they can ever see the count.
            queryset = queryset.annotate(application_count=application_count())
        return queryset

    def create(self, request, *args, **kwargs):
        # Checked before the body, so the employer learns about it first.
        if not request.user.employer_profile.is_complete:
            raise BadRequest(PROFILE_INCOMPLETE)
        return super().create(request, *args, **kwargs)

    def perform_create(self, serializer):
        # Always the logged-in employer: never taken from the request body.
        serializer.save(employer=self.request.user.employer_profile)

    def perform_destroy(self, job):
        if job.status != JobStatus.DRAFT or job.applications.exists():
            raise Conflict(CANNOT_DELETE)
        try:
            job.delete()
        except ProtectedError as exc:  # an application arrived in between
            raise Conflict(CANNOT_DELETE) from exc
