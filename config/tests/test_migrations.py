import pytest
from django.core.management import call_command


@pytest.mark.django_db
def test_no_missing_migrations():
    """Fails if a model change (e.g. new status choice) has no migration."""
    call_command("makemigrations", "--check", "--dry-run", verbosity=0)
