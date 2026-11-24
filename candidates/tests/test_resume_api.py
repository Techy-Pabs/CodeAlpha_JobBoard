"""Resume upload, listing, default, delete and the protected download."""

import io
import zipfile

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from applications.models import Application
from candidates.files import MAX_RESUME_BYTES, safe_download_name
from candidates.models import Resume

pytestmark = pytest.mark.django_db

LIST = reverse("my-resume-list")
PDF = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def docx_bytes(include_document=True):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        if include_document:
            archive.writestr("word/document.xml", "<w:document/>")
    return buffer.getvalue()


def pdf_file(name="Ada CV.pdf", content=PDF):
    return SimpleUploadedFile(name, content, content_type="application/pdf")


def upload(client, file):
    return client.post(LIST, {"file": file}, format="multipart")


def detail(pk):
    return reverse("my-resume-detail", args=[pk])


def set_default(pk):
    return reverse("my-resume-set-default", args=[pk])


def download(pk):
    return reverse("resume-download", args=[pk])


def body(response):
    return b"".join(response.streaming_content)


@pytest.fixture
def as_candidate(api_client, candidate_user):
    api_client.force_authenticate(candidate_user)
    return api_client


@pytest.fixture
def other_candidate(django_user_model):
    return django_user_model.objects.create_user(
        username="grace", email="grace@example.com", password="x-Pass-1234", role="candidate"
    ).candidate_profile


# --- upload: accepted files ---------------------------------------------------


def test_upload_pdf(as_candidate, candidate, media_root):
    response = upload(as_candidate, pdf_file())
    assert response.status_code == 201, response.data
    assert response.data["original_filename"] == "Ada CV.pdf"
    assert response.data["size_bytes"] == len(PDF)
    assert response.data["is_default"] is True
    assert response.data["download_url"].endswith(download(response.data["id"]))
    assert "file" not in response.data  # the storage path is never shown
    resume = Resume.objects.get(pk=response.data["id"])
    assert (media_root / resume.file.name).read_bytes() == PDF


def test_upload_docx(as_candidate):
    file = SimpleUploadedFile("cv.DOCX", docx_bytes(), content_type=DOCX_TYPE)
    response = upload(as_candidate, file)
    assert response.status_code == 201, response.data
    assert Resume.objects.get(pk=response.data["id"]).file.name.endswith(".docx")


def test_exactly_5_mb_is_accepted(as_candidate):
    content = b"%PDF-" + b"0" * (MAX_RESUME_BYTES - 5)
    assert upload(as_candidate, pdf_file(content=content)).status_code == 201


def test_browser_content_type_is_ignored(as_candidate):
    # A real PDF labelled as text by the client is still a PDF.
    file = SimpleUploadedFile("cv.pdf", PDF, content_type="text/plain")
    assert upload(as_candidate, file).status_code == 201


def test_only_the_first_resume_becomes_default(as_candidate, candidate):
    first = upload(as_candidate, pdf_file("one.pdf")).data
    second = upload(as_candidate, pdf_file("two.pdf")).data
    assert first["is_default"] is True
    assert second["is_default"] is False


def test_path_in_filename_is_stripped(as_candidate):
    response = upload(as_candidate, pdf_file(name="..\\..\\secret\\cv.pdf"))
    assert response.status_code == 201
    assert response.data["original_filename"] == "cv.pdf"


# --- upload: refused files ----------------------------------------------------


@pytest.mark.parametrize(
    ("name", "content", "message"),
    [
        ("setup.pdf", b"MZ\x90\x00\x03\x00\x00\x00" + b"\x00" * 200, "not a PDF"),
        ("cv.pdf", b"<html><script>alert(1)</script></html>", "not a PDF"),
        ("cv.docx", b"This is plain text, not a zip.", "not a Word"),
        ("cv.docx", docx_bytes(include_document=False), "not a Word"),
        ("cv.docx", PDF, "not a Word"),
        ("cv.pdf", docx_bytes(), "not a PDF"),
        ("cv.exe", PDF, "PDF (.pdf) or Word (.docx)"),
        ("cv.doc", PDF, "PDF (.pdf) or Word (.docx)"),
        ("cv.txt", b"hello", "PDF (.pdf) or Word (.docx)"),
        ("cv", PDF, "PDF (.pdf) or Word (.docx)"),
        ("cv.pdf", b"", "empty"),
    ],
)
def test_bad_files_are_refused(as_candidate, name, content, message):
    response = upload(as_candidate, SimpleUploadedFile(name, content))
    assert response.status_code == 400, response.data
    assert message in str(response.data["file"][0])
    assert not Resume.objects.exists()


def test_6_mb_file_is_refused(as_candidate, media_root):
    content = b"%PDF-" + b"0" * (6 * 1024 * 1024)
    response = upload(as_candidate, pdf_file(content=content))
    assert response.status_code == 400
    assert "limit is 5 MB" in response.data["file"][0]
    assert not Resume.objects.exists()
    assert not list(media_root.rglob("*.pdf"))  # nothing written to disk


def test_missing_file_is_400(as_candidate):
    assert as_candidate.post(LIST, {}, format="multipart").status_code == 400


def test_json_body_is_415(as_candidate):
    assert as_candidate.post(LIST, {"file": "x"}, format="json").status_code == 415


def test_at_most_5_resumes(as_candidate, candidate):
    for n in range(5):
        assert upload(as_candidate, pdf_file(f"cv{n}.pdf")).status_code == 201
    response = upload(as_candidate, pdf_file("cv6.pdf"))
    assert response.status_code == 400
    assert "maximum" in response.data["file"][0]
    assert candidate.resumes.count() == 5


# --- who can upload and list --------------------------------------------------


def test_employer_cannot_upload_or_list(api_client, employer_user):
    api_client.force_authenticate(employer_user)
    assert upload(api_client, pdf_file()).status_code == 403
    assert api_client.get(LIST).status_code == 403


def test_anonymous_cannot_upload_or_list(api_client):
    assert upload(api_client, pdf_file()).status_code == 401
    assert api_client.get(LIST).status_code == 401


def test_list_shows_only_own_resumes(as_candidate, other_candidate):
    mine = upload(as_candidate, pdf_file()).data["id"]
    Resume.objects.create(
        candidate=other_candidate, file="resumes/x.pdf", original_filename="g.pdf", size_bytes=1
    )
    response = as_candidate.get(LIST)
    assert response.status_code == 200
    assert [r["id"] for r in response.data] == [mine]


# --- set default --------------------------------------------------------------


def test_set_default_moves_the_flag(as_candidate, candidate):
    first = upload(as_candidate, pdf_file("one.pdf")).data["id"]
    second = upload(as_candidate, pdf_file("two.pdf")).data["id"]
    response = as_candidate.post(set_default(second))
    assert response.status_code == 200
    assert response.data["is_default"] is True
    assert list(candidate.resumes.filter(is_default=True).values_list("id", flat=True)) == [second]
    assert Resume.objects.get(pk=first).is_default is False


def test_set_default_on_current_default_is_harmless(as_candidate, candidate):
    first = upload(as_candidate, pdf_file()).data["id"]
    assert as_candidate.post(set_default(first)).status_code == 200
    assert candidate.resumes.get().is_default


def test_cannot_set_someone_elses_resume_as_default(as_candidate, other_candidate):
    theirs = Resume.objects.create(
        candidate=other_candidate, file="resumes/x.pdf", original_filename="g.pdf", size_bytes=1
    )
    assert as_candidate.post(set_default(theirs.id)).status_code == 404
    theirs.refresh_from_db()
    assert theirs.is_default is False


# --- delete -------------------------------------------------------------------


def test_delete_removes_row_and_file(as_candidate, media_root, django_capture_on_commit_callbacks):
    resume_id = upload(as_candidate, pdf_file()).data["id"]
    stored = media_root / Resume.objects.get(pk=resume_id).file.name
    assert stored.exists()
    with django_capture_on_commit_callbacks(execute=True):
        assert as_candidate.delete(detail(resume_id)).status_code == 204
    assert not Resume.objects.filter(pk=resume_id).exists()
    assert not stored.exists()


def test_deleting_the_default_promotes_the_newest(as_candidate, candidate):
    first = upload(as_candidate, pdf_file("one.pdf")).data["id"]
    upload(as_candidate, pdf_file("two.pdf"))
    third = upload(as_candidate, pdf_file("three.pdf")).data["id"]
    assert as_candidate.delete(detail(first)).status_code == 204
    assert candidate.resumes.get(is_default=True).id == third


def test_resume_used_in_an_application_cannot_be_deleted(as_candidate, candidate, job):
    resume_id = upload(as_candidate, pdf_file()).data["id"]
    Application.objects.create(job=job, candidate=candidate, resume_id=resume_id)
    response = as_candidate.delete(detail(resume_id))
    assert response.status_code == 409
    assert "sent with an application" in response.data["detail"]
    assert Resume.objects.filter(pk=resume_id).exists()


def test_cannot_delete_someone_elses_resume(as_candidate, other_candidate):
    theirs = Resume.objects.create(
        candidate=other_candidate, file="resumes/x.pdf", original_filename="g.pdf", size_bytes=1
    )
    assert as_candidate.delete(detail(theirs.id)).status_code == 404
    assert Resume.objects.filter(pk=theirs.id).exists()


# --- download -----------------------------------------------------------------


@pytest.fixture
def uploaded(as_candidate):
    """A real PDF uploaded by the candidate."""
    return Resume.objects.get(pk=upload(as_candidate, pdf_file('Ada "CV" 2026.pdf')).data["id"])


def test_owner_downloads_as_attachment(as_candidate, uploaded):
    response = as_candidate.get(download(uploaded.id))
    assert response.status_code == 200
    assert body(response) == PDF
    assert response["Content-Type"] == "application/pdf"
    assert response["Content-Disposition"] == 'attachment; filename="Ada _CV_ 2026.pdf"'
    assert response["X-Content-Type-Options"] == "nosniff"
    assert "no-store" in response["Cache-Control"]


def test_docx_download_has_word_content_type(as_candidate):
    file = SimpleUploadedFile("cv.docx", docx_bytes())
    resume_id = upload(as_candidate, file).data["id"]
    response = as_candidate.get(download(resume_id))
    assert response["Content-Type"] == DOCX_TYPE
    assert response["Content-Disposition"] == 'attachment; filename="cv.docx"'


def test_download_works_with_any_accept_header(as_candidate, uploaded):
    response = as_candidate.get(download(uploaded.id), HTTP_ACCEPT="application/pdf")
    assert response.status_code == 200


def test_employer_downloads_resume_sent_to_their_job(
    api_client, uploaded, candidate, job, employer_user
):
    Application.objects.create(job=job, candidate=candidate, resume=uploaded)
    api_client.force_authenticate(employer_user)
    response = api_client.get(download(uploaded.id))
    assert response.status_code == 200
    assert body(response) == PDF


def test_employer_cannot_download_from_someone_who_never_applied(
    api_client, uploaded, employer_user, job
):
    api_client.force_authenticate(employer_user)
    response = api_client.get(download(uploaded.id))
    assert response.status_code == 404


def test_employer_cannot_download_resume_sent_to_another_employer(
    api_client, uploaded, candidate, job, django_user_model
):
    Application.objects.create(job=job, candidate=candidate, resume=uploaded)
    other = django_user_model.objects.create_user(
        username="globex", email="g@globex.example", password="x-Pass-1234", role="employer"
    )
    api_client.force_authenticate(other)
    assert api_client.get(download(uploaded.id)).status_code == 404


def test_employer_only_gets_the_resume_that_was_sent(
    api_client, as_candidate, uploaded, candidate, job, employer_user
):
    Application.objects.create(job=job, candidate=candidate, resume=uploaded)
    unsent = upload(as_candidate, pdf_file("private.pdf")).data["id"]
    api_client.force_authenticate(employer_user)
    assert api_client.get(download(unsent)).status_code == 404


def test_other_candidate_cannot_download(api_client, uploaded, other_candidate):
    api_client.force_authenticate(other_candidate.user)
    assert api_client.get(download(uploaded.id)).status_code == 404


def test_anonymous_cannot_download(api_client, uploaded):
    api_client.force_authenticate(None)  # the upload fixture logged this client in
    assert api_client.get(download(uploaded.id)).status_code == 401


def test_missing_file_on_disk_is_404_not_500(as_candidate, uploaded, media_root):
    (media_root / uploaded.file.name).unlink()
    assert as_candidate.get(download(uploaded.id)).status_code == 404


def test_unknown_resume_is_404(as_candidate):
    assert as_candidate.get(download(999_999)).status_code == 404


# --- safe download names ------------------------------------------------------


@pytest.mark.parametrize(
    ("original", "kind", "expected"),
    [
        ("Ada CV.pdf", "pdf", "Ada CV.pdf"),
        ("../../etc/passwd", "pdf", "passwd.pdf"),
        ('a"b;c\r\nSet-Cookie: x.pdf', "pdf", "a_b_cSet-Cookie_ x.pdf"),  # CR/LF dropped
        ("Résumé Zoë.docx", "docx", "Résumé Zoë.docx"),
        ("cv‮fdp.exe", "pdf", "cvfdp.pdf"),  # right-to-left override removed
        ("evil.exe", "pdf", "evil.pdf"),  # extension from the stored file
        ("...hidden.pdf", "pdf", "hidden.pdf"),  # no leading dots
        ("-- .pdf", "pdf", "resume.pdf"),
        ("", "docx", "resume.docx"),
    ],
)
def test_safe_download_name(original, kind, expected):
    assert safe_download_name(original, kind) == expected
