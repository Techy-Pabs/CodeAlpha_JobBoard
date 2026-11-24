import itertools
from io import StringIO

import pytest
from django.contrib.auth import authenticate, get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import CommandError, call_command

from applications.models import Application
from candidates.files import check_resume_upload
from candidates.models import Resume
from jobs.models import Job
from notifications.models import Notification

User = get_user_model()

pytestmark = pytest.mark.django_db

DEMO_PASSWORD = "Demo-Pass-For-Tests-1"
USERNAMES = [
    "employer_brightpath",
    "employer_greenleaf",
    "candidate_amara",
    "candidate_ben",
    "candidate_chioma",
]


@pytest.fixture
def demo_env(settings, monkeypatch):
    settings.DEBUG = True
    monkeypatch.setenv("DEMO_PASSWORD", DEMO_PASSWORD)


def seed(*args):
    out = StringIO()
    call_command("seed_demo", *args, stdout=out)
    return out.getvalue()


def snapshot():
    """Everything the command creates, in a comparable form."""
    return {
        "users": sorted(User.objects.values_list("username", "role")),
        "jobs": sorted(Job.objects.values_list("title", "status", "job_type", "work_mode")),
        "resumes": sorted(Resume.objects.values_list("candidate__user__username", "file")),
        "applications": sorted(
            Application.objects.values_list("candidate__user__username", "job__title", "status")
        ),
        "history": Application.objects.values_list("status_changes__id").count(),
        "notifications": sorted(
            Notification.objects.values_list("recipient__username", "kind", "message")
        ),
    }


def test_creates_expected_data(demo_env, media_root):
    output = seed()
    assert "Demo data ready" in output
    assert DEMO_PASSWORD not in output  # never echo the password

    assert User.objects.filter(role="employer").count() == 2
    assert User.objects.filter(role="candidate").count() == 3
    for user in User.objects.filter(role="employer"):
        assert user.employer_profile.is_complete
        assert user.employer_profile.website
    for user in User.objects.filter(role="candidate"):
        assert user.candidate_profile.is_complete

    assert Job.objects.count() == 6
    assert Job.objects.filter(status="draft").count() == 1
    assert Job.objects.filter(status="closed").count() == 1
    assert set(Job.objects.values_list("job_type", flat=True)) == {
        "full_time",
        "part_time",
        "contract",
        "internship",
    }
    assert set(Job.objects.values_list("work_mode", flat=True)) == {"onsite", "remote", "hybrid"}

    statuses = set(Application.objects.values_list("status", flat=True))
    assert len(statuses) >= 5
    assert {"submitted", "interview", "offered", "rejected", "withdrawn"} <= statuses
    assert Notification.objects.exists()
    assert Notification.objects.filter(read_at__isnull=False).exists()
    assert Notification.objects.filter(read_at__isnull=True).exists()


def test_each_candidate_has_one_valid_default_pdf(demo_env, media_root):
    seed()
    for user in User.objects.filter(role="candidate"):
        [resume] = user.candidate_profile.resumes.all()
        assert resume.is_default
        content = (media_root / resume.file.name).read_bytes()
        assert resume.size_bytes == len(content)
        assert content.startswith(b"%PDF-") and content.rstrip().endswith(b"%%EOF")
        # Passes the same content check as a real upload.
        upload = SimpleUploadedFile(resume.original_filename, content)
        assert check_resume_upload(upload) == "pdf"


def test_generated_pdf_xref_offsets_point_at_objects(demo_env, media_root):
    seed()
    resume = Resume.objects.first()
    content = (media_root / resume.file.name).read_bytes()
    xref_at = int(content.rsplit(b"startxref\n", 1)[1].split(b"\n")[0])
    assert content[xref_at:].startswith(b"xref\n")
    entries = content[xref_at:].split(b"\n")[3:8]
    for number, entry in enumerate(entries, start=1):
        offset = int(entry[:10])
        assert content[offset:].startswith(b"%d 0 obj" % number)


def test_history_leads_to_each_status(demo_env):
    seed()
    for application in Application.objects.all():
        steps = list(application.status_changes.order_by("created_at", "id"))
        assert steps[0].from_status == "" and steps[0].to_status == "submitted"
        for before, after in itertools.pairwise(steps):
            assert after.from_status == before.to_status
            assert after.created_at > before.created_at
        assert steps[-1].to_status == application.status
        assert application.resume.candidate_id == application.candidate_id


def test_withdrawal_was_made_by_the_candidate(demo_env):
    seed()
    withdrawn = Application.objects.get(status="withdrawn")
    last = withdrawn.status_changes.order_by("-created_at").first()
    assert last.changed_by == withdrawn.candidate.user
    note = withdrawn.notifications.get(kind="status_changed")
    assert note.recipient == withdrawn.job.employer.user


def test_running_twice_creates_nothing_new(demo_env):
    seed()
    first = snapshot()
    seed()
    assert snapshot() == first
    assert User.objects.count() == 5
    assert Job.objects.count() == 6
    assert Application.objects.count() == 8


def test_demo_users_can_log_in_with_demo_password(demo_env):
    seed()
    for username in USERNAMES:
        assert authenticate(username=username, password=DEMO_PASSWORD) is not None


def test_rerun_picks_up_new_password(demo_env, monkeypatch):
    seed()
    monkeypatch.setenv("DEMO_PASSWORD", "A-Different-Pass-2")
    seed()
    assert authenticate(username="candidate_ben", password="A-Different-Pass-2") is not None
    assert authenticate(username="candidate_ben", password=DEMO_PASSWORD) is None


def test_rerun_restores_a_demo_application_moved_through_the_api(demo_env):
    seed()
    first = snapshot()
    from applications import workflow

    app = Application.objects.get(status="submitted")
    workflow.move(app.pk, "reviewing", by=app.job.employer.user, moves=workflow.EMPLOYER_MOVES)
    seed()
    assert snapshot() == first


def test_rerun_restores_a_deleted_resume_file(demo_env, media_root):
    seed()
    resume = Resume.objects.first()
    (media_root / resume.file.name).unlink()
    seed()
    resume.refresh_from_db()
    assert (media_root / resume.file.name).exists()
    assert Resume.objects.count() == 3


def test_rerun_leaves_other_data_alone(demo_env, django_user_model):
    seed()
    visitor = django_user_model.objects.create_user(
        username="visitor", email="v@example.com", password="x-Pass-1234", role="employer"
    )
    seed()
    assert User.objects.filter(pk=visitor.pk).exists()


def test_refuses_when_debug_is_false(settings, monkeypatch):
    settings.DEBUG = False
    monkeypatch.setenv("DEMO_PASSWORD", DEMO_PASSWORD)
    with pytest.raises(CommandError, match="--force"):
        seed()
    assert not User.objects.exists()


def test_force_runs_when_debug_is_false(settings, monkeypatch):
    settings.DEBUG = False
    monkeypatch.setenv("DEMO_PASSWORD", DEMO_PASSWORD)
    seed("--force")
    assert Job.objects.count() == 6


@pytest.mark.parametrize("value", [None, ""])
def test_requires_demo_password(settings, monkeypatch, value):
    settings.DEBUG = True
    if value is None:
        monkeypatch.delenv("DEMO_PASSWORD", raising=False)
    else:
        monkeypatch.setenv("DEMO_PASSWORD", value)
    with pytest.raises(CommandError, match="DEMO_PASSWORD"):
        seed()
    assert not User.objects.exists()
