import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from accounts.models import Role, User

pytestmark = pytest.mark.django_db

PASSWORD = "pw-12345!"


def test_custom_user_model_is_active():
    assert get_user_model() is User


@pytest.mark.parametrize("role", [Role.EMPLOYER, Role.CANDIDATE])
def test_user_with_a_role_is_saved(role):
    user = User.objects.create_user(username="alice", password=PASSWORD, role=role)
    assert user.role == role


def test_db_rejects_non_staff_user_without_role():
    with (
        pytest.raises(IntegrityError, match="user_role_required_unless_staff"),
        transaction.atomic(),
    ):
        User.objects.create_user(username="alice", password=PASSWORD)


def test_db_rejects_unknown_role():
    with (
        pytest.raises(IntegrityError, match="user_role_required_unless_staff"),
        transaction.atomic(),
    ):
        User.objects.create_user(username="alice", password=PASSWORD, role="recruiter")


def test_superuser_needs_no_role():
    admin = User.objects.create_superuser("root", "root@example.com", PASSWORD)
    assert admin.role == ""


def test_staff_user_needs_no_role():
    staff = User.objects.create_user(username="helper", password=PASSWORD, is_staff=True)
    assert staff.role == ""


def test_removing_staff_from_roleless_user_is_rejected():
    staff = User.objects.create_user(username="helper", password=PASSWORD, is_staff=True)
    staff.is_staff = False
    with pytest.raises(IntegrityError), transaction.atomic():
        staff.save()


def test_model_validation_explains_missing_role():
    """The admin form runs this check, so it shows a clear error, not a 500."""
    with pytest.raises(ValidationError, match="Choose a role"):
        User(username="alice").validate_constraints()
