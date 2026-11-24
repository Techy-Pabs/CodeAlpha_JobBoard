from rest_framework import serializers

from .models import Notification


class NotificationSerializer(serializers.ModelSerializer):
    application_id = serializers.IntegerField(read_only=True, allow_null=True)
    is_read = serializers.SerializerMethodField()

    class Meta:
        model = Notification
        fields = ["id", "kind", "message", "application_id", "is_read", "read_at", "created_at"]
        read_only_fields = fields

    def get_is_read(self, notification) -> bool:
        return notification.read_at is not None


class ReadAllSerializer(serializers.Serializer):
    """Body of the read-all response (for the API docs)."""

    marked_read = serializers.IntegerField(help_text="How many notifications were unread.")
