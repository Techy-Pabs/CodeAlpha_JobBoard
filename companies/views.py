from django.db.models import Count
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import generics
from rest_framework.permissions import AllowAny

from jobs.models import open_jobs_q

from .models import EmployerProfile
from .serializers import CompanySerializer


@extend_schema(
    summary="A company's public profile (public)",
    responses={200: CompanySerializer, 404: OpenApiResponse(description="No such company.")},
)
class CompanyDetailView(generics.RetrieveAPIView):
    """An employer's public profile, with how many jobs it has open right now."""

    serializer_class = CompanySerializer
    permission_classes = [AllowAny]
    # Public: a stale or broken Authorization header must not turn this into a 401.
    authentication_classes = []

    def get_queryset(self):
        return EmployerProfile.objects.filter(user__is_active=True).annotate(
            open_jobs_count=Count("jobs", filter=open_jobs_q("jobs__"))
        )
