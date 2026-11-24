from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from rest_framework import serializers

from .models import DUPLICATE_USERNAME, Role

User = get_user_model()

DUPLICATE_EMAIL = "A user with that email already exists."


def _constraint_name(exc):
    """Name of the constraint Postgres reports for an IntegrityError, or ""."""
    diag = getattr(exc.__cause__, "diag", None)
    return getattr(diag, "constraint_name", None) or ""


class UserSerializer(serializers.ModelSerializer):
    """Public view of a user. Never includes the password."""

    class Meta:
        model = User
        fields = ["id", "username", "email", "role"]
        read_only_fields = fields


class RegisterSerializer(serializers.ModelSerializer):
    # Required, and only employer or candidate. Blank (staff only) is not
    # offered here: admin accounts are made with createsuperuser.
    role = serializers.ChoiceField(choices=Role.choices)
    password = serializers.CharField(
        write_only=True,
        trim_whitespace=False,
        style={"input_type": "password"},
    )

    class Meta:
        model = User
        fields = ["id", "username", "email", "password", "role"]
        read_only_fields = ["id"]
        extra_kwargs = {"email": {"required": True, "allow_blank": False}}

    def validate_username(self, value):
        # The built-in unique check is case-sensitive; this one is not.
        if User.objects.filter(username__iexact=value).exists():
            raise serializers.ValidationError(DUPLICATE_USERNAME)
        return value

    def validate_email(self, value):
        email = value.strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise serializers.ValidationError(DUPLICATE_EMAIL)
        return email

    def validate(self, attrs):
        # Unsaved user so the similarity validator can compare the password
        # against the username and email.
        candidate = User(username=attrs.get("username"), email=attrs.get("email"))
        try:
            validate_password(attrs["password"], user=candidate)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"password": list(exc.messages)}) from exc
        return attrs

    def create(self, validated_data):
        try:
            # Savepoint so a failed insert doesn't break an outer transaction.
            # The matching profile is created by a post_save signal inside
            # this same transaction, so a user never exists without one.
            with transaction.atomic():
                return User.objects.create_user(**validated_data)
        except IntegrityError as exc:
            # Two sign-ups racing past the checks above: the database
            # constraint catches the second one. Report the right field.
            if "username" in _constraint_name(exc):
                raise serializers.ValidationError({"username": [DUPLICATE_USERNAME]}) from exc
            raise serializers.ValidationError({"email": [DUPLICATE_EMAIL]}) from exc


class LogoutSerializer(serializers.Serializer):
    refresh = serializers.CharField()
