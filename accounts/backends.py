from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend

UserModel = get_user_model()


class CaseInsensitiveModelBackend(ModelBackend):
    """Log in with any letter case of the username: "alice" finds "Alice".

    Safe because the user_username_ci_unique constraint guarantees at most one
    match. Used by the JWT login endpoint and the Django admin login alike.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None:
            username = kwargs.get(UserModel.USERNAME_FIELD)
        if username is None or password is None:
            return None
        try:
            user = UserModel._default_manager.get(
                **{f"{UserModel.USERNAME_FIELD}__iexact": username}
            )
        except UserModel.DoesNotExist:
            # Hash the password anyway so a missing user takes as long as a
            # wrong password (same timing defence as Django's ModelBackend).
            UserModel().set_password(password)
            return None
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
