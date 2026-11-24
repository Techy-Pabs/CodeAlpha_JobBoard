"""Resumes go to whichever storage is active, and downloads read from it.

R2 is tested through settings overrides with django-storages' S3 storage.
Its network-facing methods are mocked, and any real HTTP request fails the
test, so no call ever reaches Cloudflare.
"""

from unittest import mock

import pytest
from django.core.files.base import ContentFile
from django.core.files.storage import FileSystemStorage, storages
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from storages.backends.s3 import S3Storage

from applications.models import Application
from candidates.models import Resume

pytestmark = pytest.mark.django_db

PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"

R2_STORAGES = {
    "default": {
        "BACKEND": "storages.backends.s3.S3Storage",
        "OPTIONS": {
            "endpoint_url": "https://test-account.r2.cloudflarestorage.com",
            "access_key": "test-key",
            "secret_key": "test-secret",
            "bucket_name": "codealpha-jobboard",
            "region_name": "auto",
            "signature_version": "s3v4",
            "default_acl": None,
            "querystring_auth": True,
            "querystring_expire": 300,
            "custom_domain": None,
            "file_overwrite": False,
        },
    },
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}


@pytest.fixture
def no_network():
    """Fail loudly if botocore tries to send anything."""
    with mock.patch(
        "botocore.endpoint.Endpoint.make_request",
        side_effect=AssertionError("a real request to R2 was attempted"),
    ):
        yield


@pytest.fixture
def r2(settings, no_network):
    """R2 is the active storage; saving and opening objects are faked."""
    settings.STORAGES = R2_STORAGES
    saved = {}

    def fake_save(self, name, content):
        content.seek(0)
        saved[name] = content.read()
        return name

    def fake_open(self, name, mode="rb"):
        if name not in saved:
            raise FileNotFoundError(name)
        return ContentFile(saved[name], name=name)

    with (
        mock.patch.object(S3Storage, "_save", fake_save),
        mock.patch.object(S3Storage, "_open", fake_open),
        mock.patch.object(S3Storage, "exists", lambda self, name: name in saved),
    ):
        yield saved


@pytest.fixture
def as_candidate(api_client, candidate_user):
    api_client.force_authenticate(candidate_user)
    return api_client


def upload(client, content=PDF, name="Ada CV.pdf"):
    file = SimpleUploadedFile(name, content, content_type="application/pdf")
    return client.post(reverse("my-resume-list"), {"file": file}, format="multipart")


def download(client, resume_id):
    return client.get(reverse("resume-download", args=[resume_id]))


def test_local_disk_is_the_default(as_candidate, media_root):
    assert isinstance(storages["default"], FileSystemStorage)
    response = upload(as_candidate)
    resume = Resume.objects.get(pk=response.data["id"])
    assert (media_root / resume.file.name).read_bytes() == PDF


def test_r2_settings_switch_the_resume_storage(r2):
    storage = storages["default"]
    assert isinstance(storage, S3Storage)
    assert storage.bucket_name == "codealpha-jobboard"
    assert storage.endpoint_url == "https://test-account.r2.cloudflarestorage.com"
    # Private: no ACL on objects, and any URL built is signed.
    assert storage.default_acl is None
    assert storage.querystring_auth is True
    assert storage.custom_domain is None


def test_upload_goes_to_r2_not_local_disk(r2, as_candidate, media_root):
    response = upload(as_candidate)
    assert response.status_code == 201, response.data
    resume = Resume.objects.get(pk=response.data["id"])
    assert list(r2) == [resume.file.name]
    assert resume.file.name.startswith("resumes/") and resume.file.name.endswith(".pdf")
    assert r2[resume.file.name] == PDF
    assert not any(media_root.rglob("*.pdf"))  # nothing written locally


def test_download_streams_from_r2(r2, as_candidate):
    resume_id = upload(as_candidate).data["id"]
    response = download(as_candidate, resume_id)
    assert response.status_code == 200
    assert response.streaming
    assert b"".join(response.streaming_content) == PDF
    assert response["Content-Type"] == "application/pdf"
    assert response["Content-Disposition"] == 'attachment; filename="Ada CV.pdf"'
    assert response["Cache-Control"] == "private, no-store"


def test_r2_download_keeps_the_permission_check(r2, as_candidate, api_client, other_user):
    resume_id = upload(as_candidate).data["id"]
    with mock.patch.object(S3Storage, "_open") as opened:
        api_client.force_authenticate(other_user)
        assert download(api_client, resume_id).status_code == 404
    opened.assert_not_called()  # the object is never even fetched


def test_employer_can_download_from_r2_once_sent(
    r2, as_candidate, api_client, candidate, employer_user, job
):
    resume_id = upload(as_candidate).data["id"]
    api_client.force_authenticate(employer_user)
    assert download(api_client, resume_id).status_code == 404
    Application.objects.create(job=job, candidate=candidate, resume_id=resume_id)
    response = download(api_client, resume_id)
    assert response.status_code == 200
    assert b"".join(response.streaming_content) == PDF


def test_missing_r2_object_is_404(r2, as_candidate):
    resume_id = upload(as_candidate).data["id"]
    r2.clear()
    response = download(as_candidate, resume_id)
    assert response.status_code == 404
    assert response.json() == {"detail": "The resume file is missing."}


@pytest.fixture
def other_user(django_user_model):
    return django_user_model.objects.create_user(
        username="mallory", email="m@example.com", password="x-Pass-1234", role="candidate"
    )
