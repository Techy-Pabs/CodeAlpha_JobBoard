from django.db.models import Prefetch, Q
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import generics, mixins, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from accounts.permissions import IsCandidate, IsEmployer

from . import workflow
from .models import Application, ApplicationStatus, ApplicationStatusChange
from .permissions import IsApplicant, IsJobEmployer
from .serializers import (
    ApplicationDetailSerializer,
    InvalidMoveSerializer,
    MyApplicationSerializer,
    StatusChangeRequestSerializer,
    WithdrawRequestSerializer,
)

NOT_LOGGED_IN = OpenApiResponse(description="Not logged in.")
NOT_FOUND = OpenApiResponse(description="No such application, or not yours to see.")
INVALID_MOVE = OpenApiResponse(
    InvalidMoveSerializer, description="Move not allowed from the current status."
)

STATUS_PARAM = OpenApiParameter(
    "status",
    str,
    description="Only applications with this status.",
    enum=list(ApplicationStatus.values),
)


def filter_by_status(request, queryset):
    """Apply ?status= if given; 400 for a value that isn't a status."""
    value = (request.query_params.get("status") or "").strip()
    if not value:
        return queryset
    if value not in ApplicationStatus.values:
        raise ValidationError(
            {"status": [f"Choose one of: {', '.join(ApplicationStatus.values)}."]}
        )
    return queryset.filter(status=value)


def with_details(queryset):
    """Everything ApplicationDetailSerializer reads, in a fixed number of queries."""
    return queryset.select_related("job__employer", "candidate__user", "resume").prefetch_related(
        Prefetch(
            "status_changes",
            queryset=ApplicationStatusChange.objects.select_related("changed_by"),
        )
    )


@extend_schema(
    summary="Your applications (candidates)",
    parameters=[STATUS_PARAM],
    responses={
        200: MyApplicationSerializer(many=True),
        400: OpenApiResponse(description="Unknown status."),
        401: NOT_LOGGED_IN,
        403: OpenApiResponse(description="Not a candidate account."),
    },
)
class MyApplicationsView(generics.ListAPIView):
    serializer_class = MyApplicationSerializer
    permission_classes = [IsCandidate]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Application.objects.none()
        queryset = Application.objects.filter(candidate__user=self.request.user).select_related(
            "job__employer"
        )
        return filter_by_status(self.request, queryset).order_by("-created_at", "-id")


class ApplicationViewSet(mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """One application: seen only by the candidate who applied and the
    employer who posted the job. Everyone else gets 404."""

    serializer_class = ApplicationDetailSerializer

    def get_permissions(self):
        if self.action == "status":
            return [IsAuthenticated(), IsEmployer(), IsJobEmployer()]
        if self.action == "withdraw":
            return [IsAuthenticated(), IsCandidate(), IsApplicant()]
        return [IsAuthenticated()]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Application.objects.none()
        user = self.request.user
        mine = Q(candidate__user=user) | Q(job__employer__user=user)
        return with_details(Application.objects.filter(mine))

    def _move(self, to_status, note, moves):
        application = self.get_object()  # 404 if not visible, 403 if wrong side
        workflow.move(application.pk, to_status, by=self.request.user, note=note, moves=moves)
        fresh = self.get_queryset().get(pk=application.pk)
        return Response(self.get_serializer(fresh).data)

    @extend_schema(
        summary="An application with its full status history",
        responses={200: ApplicationDetailSerializer, 401: NOT_LOGGED_IN, 404: NOT_FOUND},
    )
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)

    @extend_schema(
        summary="Move an application to its next stage (the job's employer)",
        description=(
            "Allowed: submitted -> reviewing or rejected; reviewing -> shortlisted or rejected; "
            "shortlisted -> interview or rejected; interview -> offered or rejected. "
            "offered, rejected and withdrawn are final."
        ),
        request=StatusChangeRequestSerializer,
        responses={
            200: ApplicationDetailSerializer,
            400: INVALID_MOVE,
            401: NOT_LOGGED_IN,
            403: OpenApiResponse(description="You are the candidate, not the job's employer."),
            404: NOT_FOUND,
        },
    )
    @action(detail=True, methods=["post"])
    def status(self, request, pk=None):
        body = StatusChangeRequestSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        return self._move(
            body.validated_data["to_status"],
            body.validated_data["note"],
            workflow.EMPLOYER_MOVES,
        )

    @extend_schema(
        summary="Withdraw your application (the candidate who applied)",
        description="Possible from submitted, reviewing, shortlisted or interview.",
        request=WithdrawRequestSerializer,
        responses={
            200: ApplicationDetailSerializer,
            400: INVALID_MOVE,
            401: NOT_LOGGED_IN,
            403: OpenApiResponse(description="You are the employer, not the candidate."),
            404: NOT_FOUND,
        },
    )
    @action(detail=True, methods=["post"])
    def withdraw(self, request, pk=None):
        body = WithdrawRequestSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        return self._move(
            ApplicationStatus.WITHDRAWN, body.validated_data["note"], workflow.CANDIDATE_MOVES
        )
