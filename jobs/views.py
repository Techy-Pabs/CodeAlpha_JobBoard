from django.db import IntegrityError, transaction
from django.db.models import Count, IntegerField, OuterRef, Q, Subquery
from django.db.models.deletion import ProtectedError
from django.db.models.functions import Coalesce
from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_view
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from accounts.permissions import IsCandidate, IsEmployer
from applications.models import Application, ApplicationStatus, ApplicationStatusChange
from applications.serializers import (
    ApplicationDetailSerializer,
    ApplySerializer,
    JobApplicationSerializer,
)
from applications.views import STATUS_PARAM, filter_by_status, with_details
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

ALREADY_APPLIED = "You have already applied to this job."
NO_DEFAULT_RESUME = "You have no default resume. Upload one at /api/me/resumes/ or send resume_id."
NO_SUCH_RESUME = "This is not one of your resumes."

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
        if self.action == "apply":
            return [IsAuthenticated(), IsCandidate()]
        # create, update, delete and the applicant list
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

    @extend_schema(
        summary="Apply to an open job (candidates)",
        description=(
            "resume_id is optional and defaults to your default resume. One application per job."
        ),
        request=ApplySerializer,
        responses={
            201: ApplicationDetailSerializer,
            400: OpenApiResponse(description="No default resume, not your resume, or bad body."),
            401: NOT_LOGGED_IN,
            403: OpenApiResponse(description="Not a candidate account."),
            404: OpenApiResponse(description="Job not found or not open for applications."),
            409: OpenApiResponse(description="You have already applied to this job."),
        },
    )
    @action(detail=True, methods=["post"])
    def apply(self, request, pk=None):
        # For a candidate the queryset holds only open, unexpired jobs, so
        # drafts, closed and expired jobs are a 404 here, as everywhere else.
        job = self.get_object()
        body = ApplySerializer(data=request.data)
        body.is_valid(raise_exception=True)
        candidate = request.user.candidate_profile

        resume_id = body.validated_data.get("resume_id")
        resumes = candidate.resumes.all()
        if resume_id is None:
            resume = resumes.filter(is_default=True).first()
            if resume is None:
                raise ValidationError({"resume_id": [NO_DEFAULT_RESUME]})
        else:
            resume = resumes.filter(pk=resume_id).first()
            if resume is None:
                raise ValidationError({"resume_id": [NO_SUCH_RESUME]})

        if Application.objects.filter(job=job, candidate=candidate).exists():
            raise Conflict(ALREADY_APPLIED)
        try:
            with transaction.atomic():
                application = Application.objects.create(
                    job=job,
                    candidate=candidate,
                    resume=resume,
                    cover_letter=body.validated_data["cover_letter"],
                )
                # First history row: from nothing to submitted.
                ApplicationStatusChange.objects.create(
                    application=application,
                    from_status="",
                    to_status=ApplicationStatus.SUBMITTED,
                    changed_by=request.user,
                )
        except IntegrityError as exc:  # a double-click raced past the check above
            raise Conflict(ALREADY_APPLIED) from exc

        application = with_details(Application.objects).get(pk=application.pk)
        data = ApplicationDetailSerializer(application, context=self.get_serializer_context()).data
        return Response(data, status=status.HTTP_201_CREATED)

    @extend_schema(
        summary="Applications to one of your jobs (its employer)",
        parameters=[STATUS_PARAM],
        responses={
            200: JobApplicationSerializer(many=True),
            400: OpenApiResponse(description="Unknown status."),
            401: NOT_LOGGED_IN,
            403: NOT_EMPLOYER,
            404: NOT_FOUND,
        },
    )
    @action(detail=True, methods=["get"], serializer_class=JobApplicationSerializer)
    def applications(self, request, pk=None):
        job = self.get_object()  # 403 unless this employer posted it
        queryset = job.applications.select_related("candidate__user", "resume")
        queryset = filter_by_status(request, queryset).order_by("-created_at", "-id")
        page = self.paginate_queryset(queryset)
        serializer = JobApplicationSerializer(
            page, many=True, context=self.get_serializer_context()
        )
        return self.get_paginated_response(serializer.data)
