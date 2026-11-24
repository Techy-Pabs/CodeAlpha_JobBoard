import re

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction

from candidates.models import Resume, resume_upload_to

pytestmark = pytest.mark.django_db

RANDOM_NAME = re.compile(r"^resumes/[0-9a-f]{32}(\.pdf|\.docx?)?$")


def make_resume(candidate, **overrides):
    data = {
        "candidate": candidate,
        "file": "resumes/abc.pdf",
        "original_filename": "cv.pdf",
        "size_bytes": 2048,
    }
    data.update(overrides)
    return Resume.objects.create(**data)


# --- at most one default resume per candidate --------------------------------


def test_db_rejects_second_default_resume(candidate, resume):
    assert resume.is_default
    with (
        pytest.raises(IntegrityError, match="resume_one_default_per_candidate"),
        transaction.atomic(),
    ):
        make_resume(candidate, is_default=True)


def test_many_non_default_resumes_are_allowed(candidate, resume):
    make_resume(candidate)
    make_resume(candidate)
    assert candidate.resumes.count() == 3
    assert candidate.resumes.filter(is_default=True).count() == 1


def test_different_candidates_each_have_a_default(candidate, resume, django_user_model):
    other = django_user_model.objects.create_user(
        username="grace", password="pw-12345!", role="candidate"
    ).candidate_profile
    make_resume(other, is_default=True)
    assert Resume.objects.filter(is_default=True).count() == 2


def test_db_rejects_negative_size(candidate):
    with pytest.raises(IntegrityError), transaction.atomic():
        make_resume(candidate, size_bytes=-1)


# --- random file names ---------------------------------------------------------


@pytest.mark.parametrize(
    ("uploaded", "suffix"),
    [
        ("Ada Lovelace CV.pdf", ".pdf"),
        ("ada.DOCX", ".docx"),
        ("resume.doc", ".doc"),
        ("../../etc/passwd", ""),
        ("ada.exe", ""),
        ("no-extension", ""),
    ],
)
def test_upload_to_uses_a_random_name(uploaded, suffix):
    path = resume_upload_to(None, uploaded)
    assert RANDOM_NAME.match(path), path
    assert path.endswith(suffix)
    # The regex already proves the name is 32 hex digits. (Don't test for "ada":
    # a random hex string can contain those letters.)
    assert ".." not in path and "passwd" not in path and "exe" not in path


def test_upload_to_never_repeats():
    assert resume_upload_to(None, "cv.pdf") != resume_upload_to(None, "cv.pdf")


def test_saved_file_does_not_contain_users_name(candidate, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    upload = SimpleUploadedFile("Ada Lovelace CV.pdf", b"%PDF-1.4 test", "application/pdf")
    resume = Resume.objects.create(
        candidate=candidate,
        file=upload,
        original_filename=upload.name,
        size_bytes=upload.size,
    )
    assert RANDOM_NAME.match(resume.file.name), resume.file.name
    assert "lovelace" not in resume.file.name.lower()  # not hex, so never there by chance
    assert resume.original_filename == "Ada Lovelace CV.pdf"
    assert (tmp_path / resume.file.name).read_bytes() == b"%PDF-1.4 test"
