import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError

from applications.models import (
    COVER_LETTER_MAX,
    Application,
    ApplicationStatus,
    ApplicationStatusChange,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def application(job, candidate, resume):
    return Application.objects.create(job=job, candidate=candidate, resume=resume)


def test_default_status_is_submitted(application):
    assert application.status == ApplicationStatus.SUBMITTED


def test_db_rejects_second_application_to_same_job(application, job, candidate, resume):
    with (
        pytest.raises(IntegrityError, match="application_one_per_job_candidate"),
        transaction.atomic(),
    ):
        Application.objects.create(job=job, candidate=candidate, resume=resume)


def test_same_candidate_can_apply_to_another_job(application, job, candidate, resume):
    job.pk = None  # copy of the job as a new row
    job.save()
    Application.objects.create(job=job, candidate=candidate, resume=resume)
    assert candidate.applications.count() == 2


def test_db_rejects_unknown_status(application):
    application.status = "hired"
    with (
        pytest.raises(IntegrityError, match="application_status_valid"),
        transaction.atomic(),
    ):
        application.save()


def test_every_status_choice_is_accepted(application):
    for status in ApplicationStatus.values:
        application.status = status
        application.save()


def test_db_rejects_cover_letter_over_2000(job, candidate, resume):
    with (
        pytest.raises(IntegrityError, match="application_cover_letter_max_2000"),
        transaction.atomic(),
    ):
        Application.objects.create(
            job=job, candidate=candidate, resume=resume, cover_letter="x" * (COVER_LETTER_MAX + 1)
        )


def test_cover_letter_of_exactly_2000_is_accepted(job, candidate, resume):
    app = Application.objects.create(
        job=job, candidate=candidate, resume=resume, cover_letter="x" * COVER_LETTER_MAX
    )
    assert len(app.cover_letter) == COVER_LETTER_MAX


def test_job_with_applications_cannot_be_deleted(application, job):
    with pytest.raises(ProtectedError):
        job.delete()


def test_resume_used_in_an_application_cannot_be_deleted(application, resume):
    with pytest.raises(ProtectedError):
        resume.delete()


def test_resume_must_belong_to_the_applicant(job, resume, django_user_model):
    other = django_user_model.objects.create_user(
        username="grace", password="pw-12345!", role="candidate"
    ).candidate_profile
    app = Application(job=job, candidate=other, resume=resume)
    with pytest.raises(ValidationError, match="different candidate"):
        app.full_clean()


# --- status history ------------------------------------------------------------


def test_status_history_is_kept_in_order(application, employer_user):
    for old, new in [("submitted", "reviewing"), ("reviewing", "shortlisted")]:
        ApplicationStatusChange.objects.create(
            application=application, from_status=old, to_status=new, changed_by=employer_user
        )
    steps = [c.to_status for c in application.status_changes.all()]
    assert steps == ["reviewing", "shortlisted"]


def test_history_survives_when_the_changer_is_deleted(application, django_user_model):
    reviewer = django_user_model.objects.create_user(
        username="temp_hr", password="pw-12345!", role="employer"
    )
    change = ApplicationStatusChange.objects.create(
        application=application, from_status="submitted", to_status="reviewing", changed_by=reviewer
    )
    reviewer.delete()
    change.refresh_from_db()
    assert change.changed_by is None
