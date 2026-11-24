import pytest

from applications.models import Application, ApplicationStatusChange


@pytest.fixture
def open_job(job):
    job.status = "open"
    job.save()
    return job


@pytest.fixture
def other_employer(django_user_model):
    user = django_user_model.objects.create_user(
        username="globex", email="hr@globex.example", password="x-Pass-1234", role="employer"
    )
    profile = user.employer_profile
    profile.company_name, profile.location, profile.description = "Globex", "Abuja", "Energy."
    profile.save()
    return profile


@pytest.fixture
def other_candidate(django_user_model):
    return django_user_model.objects.create_user(
        username="grace", email="grace@example.com", password="x-Pass-1234", role="candidate"
    ).candidate_profile


@pytest.fixture
def make_application(open_job, candidate, resume):
    """An application in any status, with a history that leads to it."""

    def make(status="submitted", **overrides):
        data = {"job": open_job, "candidate": candidate, "resume": resume, "status": status}
        data.update(overrides)
        application = Application.objects.create(**data)
        ApplicationStatusChange.objects.create(
            application=application, from_status="", to_status="submitted"
        )
        if status != "submitted":
            ApplicationStatusChange.objects.create(
                application=application, from_status="submitted", to_status=status
            )
        return application

    return make


@pytest.fixture
def application(make_application):
    return make_application()
