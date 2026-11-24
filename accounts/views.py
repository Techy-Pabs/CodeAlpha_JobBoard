from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import generics, status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView

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
