from drf_spectacular.utils import (
    OpenApiResponse,
    PolymorphicProxySerializer,
    extend_schema,
    extend_schema_view,
)
from rest_framework import generics, status
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView

from candidates.serializers import MyCandidateProfileSerializer
from companies.serializers import MyEmployerProfileSerializer

from .serializers import LogoutSerializer, RegisterSerializer, UserSerializer


class RegisterView(generics.CreateAPIView):
    """Create an account as an employer or a candidate. Public."""

    serializer_class = RegisterSerializer
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_scope = "register"


class LoginView(TokenObtainPairView):
    """Exchange username and password for an access and a refresh token."""

    throttle_scope = "login"


class LogoutView(generics.GenericAPIView):
    """Blacklist a refresh token so it can no longer be used."""

    serializer_class = LogoutSerializer

    @extend_schema(
        responses={
            205: OpenApiResponse(description="Refresh token blacklisted."),
            400: OpenApiResponse(description="Invalid, expired or already used token."),
        }
    )
    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            token = RefreshToken(serializer.validated_data["refresh"])
            if token.get("user_id") != str(request.user.pk):
                raise TokenError("Token does not belong to this user")
            token.blacklist()
        except TokenError:
            return Response(
                {"detail": "Invalid or expired refresh token."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(status=status.HTTP_205_RESET_CONTENT)


class MeView(generics.RetrieveAPIView):
    """The logged-in user's own profile."""

    serializer_class = UserSerializer

    def get_object(self):
        return self.request.user


MyProfileSerializer = PolymorphicProxySerializer(
    component_name="MyProfile",
    serializers=[MyEmployerProfileSerializer, MyCandidateProfileSerializer],
    resource_type_field_name=None,
)
NO_PROFILE = OpenApiResponse(description="Not logged in (401), or an account without a role (403).")


@extend_schema_view(
    get=extend_schema(
        summary="Your own employer or candidate profile",
        responses={200: MyProfileSerializer, 401: NO_PROFILE, 403: NO_PROFILE},
    ),
    patch=extend_schema(
        summary="Update your own profile",
        description=(
            "Employers must end up with company_name, location and description filled in; "
            "candidates with headline and location. The role cannot be changed."
        ),
        request=MyProfileSerializer,
        responses={
            200: MyProfileSerializer,
            400: OpenApiResponse(description="A required field is blank, or role was sent."),
            401: NO_PROFILE,
            403: NO_PROFILE,
        },
    ),
)
class MyProfileView(generics.RetrieveUpdateAPIView):
    """The logged-in user's employer or candidate profile, picked by their role."""

    http_method_names = ["get", "patch", "head", "options"]

    def get_serializer_class(self):
        if getattr(self, "swagger_fake_view", False) or not self.request.user.is_candidate:
            return MyEmployerProfileSerializer
        return MyCandidateProfileSerializer

    def get_object(self):
        user = self.request.user
        # Every employer and candidate gets a profile at sign-up (signals), so
        # a missing one means a staff account with no role.
        if user.is_employer and hasattr(user, "employer_profile"):
            return user.employer_profile
        if user.is_candidate and hasattr(user, "candidate_profile"):
            return user.candidate_profile
        raise PermissionDenied("Only employer and candidate accounts have a profile.")
