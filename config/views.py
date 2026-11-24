from django.db import DatabaseError, connection
from drf_spectacular.utils import OpenApiResponse, extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

HealthSerializer = inline_serializer("Health", fields={"status": serializers.CharField()})


@extend_schema(
    summary="Health check (public)",
    responses={
        200: HealthSerializer,
        503: OpenApiResponse(HealthSerializer, description="Database unreachable."),
    },
)
@api_view(["GET"])
@authentication_classes([])
@permission_classes([AllowAny])
def health(request):
    """Report whether the app can reach its database. Used by Docker and uptime checks."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except DatabaseError:
        return Response({"status": "error"}, status=503)
    return Response({"status": "ok"})
