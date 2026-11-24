"""Create the admin account from environment variables, if it doesn't exist.

Render's free plan has no shell for "createsuperuser", so the container runs
this on every start. It reads DJANGO_SUPERUSER_USERNAME, DJANGO_SUPERUSER_EMAIL
and DJANGO_SUPERUSER_PASSWORD:

- none set: nothing to do
- some but not all set: error (probably a typo on the host)
- the username already exists (ignoring case): left exactly as it is, so a
  password changed in the admin isn't overwritten on the next start
- otherwise: the superuser is created

The password is never printed, not even in error messages.
"""

import os

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import validate_email
from django.db import IntegrityError, transaction

VARS = ("DJANGO_SUPERUSER_USERNAME", "DJANGO_SUPERUSER_EMAIL", "DJANGO_SUPERUSER_PASSWORD")


class Command(BaseCommand):
    help = "Create the superuser from DJANGO_SUPERUSER_* env vars if it doesn't exist."

    def handle(self, *args, **options):
        User = get_user_model()
        username = os.environ.get("DJANGO_SUPERUSER_USERNAME", "").strip()
        email = os.environ.get("DJANGO_SUPERUSER_EMAIL", "").strip()
        password = os.environ.get("DJANGO_SUPERUSER_PASSWORD", "")
        values = dict(zip(VARS, (username, email, password), strict=True))

        if not any(values.values()):
            self.stdout.write("No DJANGO_SUPERUSER_* variables set; skipping admin account.")
            return
        missing = [name for name, value in values.items() if not value]
        if missing:
            raise CommandError(
                "Set all three DJANGO_SUPERUSER_* variables or none. "
                f"Missing: {', '.join(missing)}."
            )

        if User.objects.filter(username__iexact=username).exists():
            self.stdout.write(f"Admin account '{username}' already exists; left unchanged.")
            return

        try:
            validate_email(email)
        except ValidationError:
            raise CommandError("DJANGO_SUPERUSER_EMAIL is not a valid email address.") from None
        if User.objects.filter(email__iexact=email).exists():
            raise CommandError(
                "DJANGO_SUPERUSER_EMAIL already belongs to another user. "
                "Use a different email or that user's username."
            )
        try:
            validate_password(password, user=User(username=username, email=email))
        except ValidationError as exc:
            # Django's messages describe the problem, never the password.
            reasons = " ".join(exc.messages)
            raise CommandError(f"DJANGO_SUPERUSER_PASSWORD was rejected: {reasons}") from None

        try:
            with transaction.atomic():
                User.objects.create_superuser(username=username, email=email, password=password)
        except IntegrityError:
            # Another process created the same user or email a moment ago.
            raise CommandError(
                f"Could not create admin account '{username}': the username or email is taken."
            ) from None

        self.stdout.write(self.style.SUCCESS(f"Created admin account '{username}'."))
