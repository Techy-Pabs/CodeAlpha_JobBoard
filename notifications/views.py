from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from .models import Notification
from .serializers import NotificationSerializer, ReadAllSerializer

NOT_LOGGED_IN = OpenApiResponse(description="Not logged in.")
UNREAD_VALUES = {"true": True, "1": True, "false": False, "0": False}


class NotificationViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """The logged-in user's own notifications. Anyone else's are 404."""

    serializer_class = NotificationSerializer
    lookup_value_regex = r"\d+"

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Notification.objects.none()
        return Notification.objects.filter(recipient=self.request.user).order_by(
            "-created_at", "-id"
        )

    def filter_queryset(self, queryset):
        if self.action != "list":
            return queryset
        raw = (self.request.query_params.get("unread") or "").strip().lower()
        if not raw:
            return queryset
        if raw not in UNREAD_VALUES:
            raise ValidationError({"unread": ["Use true or false."]})
        return queryset.filter(read_at__isnull=UNREAD_VALUES[raw])

    @extend_schema(
        summary="Your notifications, newest first",
        parameters=[
            OpenApiParameter("unread", bool, description="true: only unread. false: only read.")
        ],
        responses={
            200: NotificationSerializer(many=True),
            400: OpenApiResponse(description="unread is not true or false."),
            401: NOT_LOGGED_IN,
        },
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(
        summary="Mark one notification as read",
        description="Marking one that is already read keeps its first read time.",
        request=None,
        responses={
            200: NotificationSerializer,
            401: NOT_LOGGED_IN,
            404: OpenApiResponse(description="Not one of your notifications."),
        },
    )
    @action(detail=True, methods=["post"])
    def read(self, request, pk=None):
        notification = self.get_object()
        if notification.read_at is None:
            notification.read_at = timezone.now()
            notification.save(update_fields=["read_at"])
        return Response(self.get_serializer(notification).data)

    @extend_schema(
        summary="Mark all your notifications as read",
        request=None,
        responses={200: ReadAllSerializer, 401: NOT_LOGGED_IN},
    )
    @action(detail=False, methods=["post"], url_path="read-all")
    def read_all(self, request):
        # One UPDATE, only touching unread rows.
        count = self.get_queryset().filter(read_at__isnull=True).update(read_at=timezone.now())
        return Response({"marked_read": count})
