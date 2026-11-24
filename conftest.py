import tempfile
from pathlib import Path

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient


@pytest.fixture(autouse=True)
def _clear_cache():
    """Throttle counters live in the cache; reset them around every test."""
    cache.clear()
    yield
    cache.clear()


@pytest.fixture(autouse=True)
def media_root(settings):
    """Every test stores uploads in its own temporary folder, deleted afterwards.

    Autouse, so no test can ever write into the real media/ folder.
    """
    with tempfile.TemporaryDirectory(prefix="jobboard-test-media-") as folder:
        settings.MEDIA_ROOT = folder
        yield Path(folder)


@pytest.fixture(autouse=True)
def _plain_static_storage(settings):
    """Tests don't run collectstatic, so skip WhiteNoise's manifest lookup.

    With DEBUG off (as in CI) the manifest storage refuses any static file
    missing from the manifest, which would break every admin page test.
    """
    settings.STORAGES = {
        **settings.STORAGES,
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }


@pytest.fixture
def api_client():
    return APIClient()


PASSWORD = "Tr1cky-Horse-Battery"


@pytest.fixture
def employer_user(django_user_model):
    return django_user_model.objects.create_user(
        username="acme", email="hr@acme.example", password=PASSWORD, role="employer"
    )


@pytest.fixture
def employer(employer_user):
    """The EmployerProfile created automatically for employer_user, filled in."""
    profile = employer_user.employer_profile
    profile.company_name = "Acme Ltd"
    profile.location = "Lagos"
    profile.description = "We build logistics software."
    profile.save()
    return profile


@pytest.fixture
def candidate_user(django_user_model):
    return django_user_model.objects.create_user(
        username="ada", email="ada@example.com", password=PASSWORD, role="candidate"
    )


@pytest.fixture
def candidate(candidate_user):
    """The CandidateProfile created automatically for candidate_user."""
    return candidate_user.candidate_profile


@pytest.fixture
def resume(candidate):
    from candidates.models import Resume

    # Points at a path only; constraint tests never need the file on disk.
    return Resume.objects.create(
        candidate=candidate,
        file="resumes/0123456789abcdef.pdf",
        original_filename="Ada CV.pdf",
        size_bytes=1024,
        is_default=True,
    )


@pytest.fixture
def job(employer):
    from jobs.models import Job

    return Job.objects.create(
        employer=employer,
        title="Backend Developer",
        description="Build APIs with Django.",
        location="Lagos",
        job_type="full_time",
        work_mode="hybrid",
        experience_level="mid",
    )
