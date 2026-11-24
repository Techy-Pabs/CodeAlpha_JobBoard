import json

from django.db import transaction
from django.db.models import Exists, OuterRef, Q
from django.db.models.deletion import ProtectedError
from django.http import FileResponse
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_view
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.parsers import MultiPartParser
from rest_framework.renderers import BaseRenderer, JSONRenderer
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsCandidate
from applications.models import Application
from config.exceptions import Conflict

from .files import (
    CONTENT_TYPES,
    MAX_RESUMES_PER_CANDIDATE,
    clean_original_name,
    extension_of,
    safe_download_name,
)
from .models import CandidateProfile, Resume
from .serializers import ResumeSerializer, ResumeUploadSerializer

RESUME_IN_USE = (
    "This resume was sent with an application, so it is kept for the employer. "
    "Upload a new one and make it your default instead."
)
TOO_MANY = (
    f"You already have {MAX_RESUMES_PER_CANDIDATE} resumes, the maximum. "
    "Delete one before uploading another."
)

NOT_LOGGED_IN = OpenApiResponse(description="Not logged in.")
NOT_CANDIDATE = OpenApiResponse(description="Not a candidate account.")
NO_SUCH_RESUME = OpenApiResponse(description="Not one of your resumes.")


def lock_candidate(candidate):
    """Lock the candidate row so their resume changes run one at a time.

    Two uploads at once could otherwise both see 4 resumes and make 6, or both
    become the default.
    """
    CandidateProfile.objects.select_for_update().get(pk=candidate.pk)


@extend_schema_view(
    list=extend_schema(
        summary="Your resumes",
        responses={200: ResumeSerializer(many=True), 401: NOT_LOGGED_IN, 403: NOT_CANDIDATE},
    ),
    create=extend_schema(
        summary="Upload a resume (PDF or DOCX, up to 5 MB)",
        description=(
            f"multipart/form-data with a `file` field. At most {MAX_RESUMES_PER_CANDIDATE} "
            "resumes per candidate. Your first resume becomes the default."
        ),
        request={"multipart/form-data": ResumeUploadSerializer},
        responses={
            201: ResumeSerializer,
            400: OpenApiResponse(
                description="Not a real PDF/DOCX, over 5 MB, empty, or the 5-resume limit."
            ),
            401: NOT_LOGGED_IN,
            403: NOT_CANDIDATE,
        },
    ),
    destroy=extend_schema(
        summary="Delete one of your resumes",
        description="If it was the default, your newest remaining resume becomes the default.",
        responses={
            204: OpenApiResponse(description="Deleted."),
            401: NOT_LOGGED_IN,
            403: NOT_CANDIDATE,
            404: NO_SUCH_RESUME,
            409: OpenApiResponse(description="Used in an application, so it is kept."),
        },
    ),
)
class MyResumeViewSet(
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """The logged-in candidate's resumes. Other people's resumes are 404."""

    serializer_class = ResumeSerializer
    permission_classes = [IsCandidate]
    parser_classes = [MultiPartParser]
    pagination_class = None  # never more than MAX_RESUMES_PER_CANDIDATE

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Resume.objects.none()
        return Resume.objects.filter(candidate__user=self.request.user)

    def create(self, request, *args, **kwargs):
        upload_serializer = ResumeUploadSerializer(data=request.data)
        upload_serializer.is_valid(raise_exception=True)
        upload = upload_serializer.validated_data["file"]
        candidate = request.user.candidate_profile

        with transaction.atomic():
            lock_candidate(candidate)
            existing = candidate.resumes.count()
            if existing >= MAX_RESUMES_PER_CANDIDATE:
                raise ValidationError({"file": [TOO_MANY]})
            resume = Resume.objects.create(
                candidate=candidate,
                file=upload,
                original_filename=clean_original_name(upload.name),
                size_bytes=upload.size,
                is_default=existing == 0,
            )

        data = ResumeSerializer(resume, context=self.get_serializer_context()).data
        return Response(data, status=status.HTTP_201_CREATED)

    def perform_destroy(self, resume):
        candidate = resume.candidate
        with transaction.atomic():
            lock_candidate(candidate)
            if resume.applications.exists():
                raise Conflict(RESUME_IN_USE)
            was_default = resume.is_default
            name, storage = resume.file.name, resume.file.storage
            try:
                resume.delete()
            except ProtectedError as exc:  # an application arrived in between
                raise Conflict(RESUME_IN_USE) from exc
            if was_default:
                newest = candidate.resumes.order_by("-uploaded_at", "-id").first()
                if newest:
                    newest.is_default = True
                    newest.save(update_fields=["is_default"])
            # Remove the file only once the row is really gone.
            transaction.on_commit(lambda: storage.delete(name))

    @extend_schema(
        summary="Make this your default resume",
        request=None,
        responses={
            200: ResumeSerializer,
            401: NOT_LOGGED_IN,
            403: NOT_CANDIDATE,
            404: NO_SUCH_RESUME,
        },
    )
    @action(detail=True, methods=["post"], url_path="set-default")
    def set_default(self, request, pk=None):
        resume = self.get_object()
        with transaction.atomic():
            lock_candidate(resume.candidate)
            # Clear the old default first: at most one may exist at any moment.
            resume.candidate.resumes.filter(is_default=True).exclude(pk=resume.pk).update(
                is_default=False
            )
            resume.is_default = True
            resume.save(update_fields=["is_default"])
        return Response(self.get_serializer(resume).data)


class DownloadRenderer(BaseRenderer):
    """Lets any Accept header through to the file response.

    Without it a client sending e.g. Accept: application/pdf would get 406
    before the view runs. Error bodies (dicts) are still sent as JSON.
    """

    media_type = "*/*"
    format = "download"

    def render(self, data, accepted_media_type=None, renderer_context=None):
        if isinstance(data, bytes):
            return data
        return json.dumps(data).encode()


def downloadable_resumes(user):
    """Resumes this user may download: their own, or ones sent to their jobs."""
    sent_to_me = Application.objects.filter(resume=OuterRef("pk"), job__employer__user=user)
    return Resume.objects.filter(Q(candidate__user=user) | Q(Exists(sent_to_me)))


class ResumeDownloadView(APIView):
    renderer_classes = [JSONRenderer, DownloadRenderer]

    @extend_schema(
        summary="Download a resume",
        description=(
            "Allowed for the candidate who uploaded it, and for an employer it was sent "
            "to with an application to one of their jobs. Everyone else gets 404."
        ),
        responses={
            (200, CONTENT_TYPES["pdf"]): OpenApiTypes.BINARY,
            (200, CONTENT_TYPES["docx"]): OpenApiTypes.BINARY,
            401: NOT_LOGGED_IN,
            404: OpenApiResponse(description="No such resume, or not yours to download."),
        },
    )
    def get(self, request, pk):
        resume = downloadable_resumes(request.user).filter(pk=pk).first()
        if resume is None:
            raise NotFound("Resume not found.")
        kind = extension_of(resume.file.name)
        if kind not in CONTENT_TYPES:
            raise NotFound("Resume not found.")
        try:
            handle = resume.file.open("rb")
        except FileNotFoundError as exc:
            raise NotFound("The resume file is missing.") from exc

        response = FileResponse(
            handle,
            as_attachment=True,
            filename=safe_download_name(resume.original_filename, kind),
            content_type=CONTENT_TYPES[kind],
        )
        # Never let a browser guess a different type (e.g. HTML) and render it.
        response["X-Content-Type-Options"] = "nosniff"
        # Personal data: don't keep copies in shared caches or the browser cache.
        response["Cache-Control"] = "private, no-store"
        return response
