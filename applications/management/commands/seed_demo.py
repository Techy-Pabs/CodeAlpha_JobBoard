"""Create demo employers, candidates, jobs, applications and notifications.

Safe to run more than once. Rows are looked up by username, or by employer
and job title, and updated in place, so a second run adds nothing. A demo
application that someone has since moved through the API is put back to its
demo state (with its history and notifications), so the demo always starts
from the same place. Anything else created through the API is left alone.

Refuses to run when DEBUG is False unless --force is given. The password for
every demo account comes from DEMO_PASSWORD and is never printed.
"""

import os
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from accounts.models import Role
from applications.management.demo_pdf import resume_pdf
from applications.models import Application, ApplicationStatusChange
from candidates.models import Resume
from jobs.models import Job
from notifications.models import Notification, NotificationKind

User = get_user_model()

EMPLOYERS = {
    "employer_brightpath": {
        "company_name": "BrightPath Logistics",
        "website": "https://brightpath.example.com",
        "location": "Lagos",
        "description": "Delivery and warehouse software for shops across West Africa.",
    },
    "employer_greenleaf": {
        "company_name": "Greenleaf Health",
        "website": "https://greenleaf.example.com",
        "location": "Abuja",
        "description": "Patient records and appointment booking for clinics.",
    },
}

# username: (full name, headline, location, skills, lines on the CV)
CANDIDATES = {
    "candidate_amara": (
        "Amara Okafor",
        "Backend developer, Python and Django",
        "Lagos",
        "Python, Django, PostgreSQL, Docker",
        [
            "3 years building REST APIs with Django REST Framework.",
            "Moved a monolith's reports to background jobs, cutting page loads by half.",
            "BSc Computer Science, University of Lagos.",
        ],
    ),
    "candidate_ben": (
        "Ben Adeyemi",
        "Frontend developer, React and TypeScript",
        "Ibadan",
        "JavaScript, TypeScript, React, CSS",
        [
            "2 years on customer dashboards in React and TypeScript.",
            "Built a component library used by four product teams.",
            "HND Computer Science, The Polytechnic, Ibadan.",
        ],
    ),
    "candidate_chioma": (
        "Chioma Eze",
        "Data analyst learning backend development",
        "Abuja",
        "Python, SQL, Excel, Power BI",
        [
            "2 years of sales reporting in SQL and Power BI.",
            "Automated weekly reports with Python and pandas.",
            "BSc Statistics, University of Abuja.",
        ],
    ),
}

# (employer, title): fields. days_ago spreads the posting dates.
JOBS = {
    ("employer_brightpath", "Backend Developer (Django)"): {
        "description": "Build and run the APIs behind our delivery tracking app.",
        "location": "Lagos",
        "job_type": "full_time",
        "work_mode": "hybrid",
        "experience_level": "mid",
        "salary_min": 450000,
        "salary_max": 700000,
        "skills": "Python, Django, PostgreSQL, REST APIs",
        "status": "open",
        "days_ago": 20,
    },
    ("employer_brightpath", "Frontend Engineer (React)"): {
        "description": "Six-month contract on our warehouse dashboard in React.",
        "location": "Remote, Nigeria",
        "job_type": "contract",
        "work_mode": "remote",
        "experience_level": "mid",
        "salary_min": 350000,
        "salary_max": 500000,
        "skills": "React, TypeScript, CSS",
        "status": "open",
        "days_ago": 16,
    },
    ("employer_brightpath", "Data Analyst Intern"): {
        "description": "Help the operations team turn delivery data into weekly reports.",
        "location": "Lagos",
        "job_type": "internship",
        "work_mode": "onsite",
        "experience_level": "entry",
        "salary_min": 100000,
        "salary_max": 150000,
        "skills": "SQL, Excel, Python",
        "status": "open",
        "days_ago": 12,
    },
    ("employer_brightpath", "DevOps Engineer"): {
        "description": "Own our deployments, monitoring and cloud costs. Still being written.",
        "location": "Remote, Nigeria",
        "job_type": "full_time",
        "work_mode": "remote",
        "experience_level": "senior",
        "salary_min": 800000,
        "salary_max": 1200000,
        "skills": "Docker, Linux, CI/CD, Terraform",
        "status": "draft",
        "days_ago": 3,
    },
    ("employer_greenleaf", "Python Developer, Health Records"): {
        "description": "Part-time role on the Python service that stores patient records.",
        "location": "Abuja",
        "job_type": "part_time",
        "work_mode": "remote",
        "experience_level": "entry",
        "salary_min": 200000,
        "salary_max": 300000,
        "skills": "Python, Django, SQL",
        "status": "open",
        "days_ago": 18,
    },
    ("employer_greenleaf", "Mobile Developer (Flutter)"): {
        "description": "Build the clinic booking app for Android and iOS. Position filled.",
        "location": "Abuja",
        "job_type": "full_time",
        "work_mode": "onsite",
        "experience_level": "mid",
        "salary_min": 500000,
        "salary_max": 750000,
        "skills": "Flutter, Dart, Firebase",
        "status": "closed",
        "days_ago": 30,
    },
}

C, E = "candidate", "employer"

# (candidate, (employer, job title), days ago it was submitted, steps after
# submitting as (to_status, who moved it, note)).
APPLICATIONS = [
    (
        "candidate_amara",
        ("employer_brightpath", "Backend Developer (Django)"),
        14,
        [
            ("reviewing", E, ""),
            ("shortlisted", E, "Strong Django experience."),
            ("interview", E, "Technical interview booked."),
        ],
    ),
    (
        "candidate_ben",
        ("employer_brightpath", "Backend Developer (Django)"),
        10,
        [("reviewing", E, "")],
    ),
    (
        "candidate_chioma",
        ("employer_brightpath", "Backend Developer (Django)"),
        9,
        [("reviewing", E, ""), ("rejected", E, "Looking for more backend experience.")],
    ),
    (
        "candidate_amara",
        ("employer_greenleaf", "Python Developer, Health Records"),
        15,
        [
            ("reviewing", E, ""),
            ("shortlisted", E, ""),
            ("interview", E, ""),
            ("offered", E, "Offer sent by email."),
        ],
    ),
    (
        "candidate_ben",
        ("employer_brightpath", "Frontend Engineer (React)"),
        8,
        [("withdrawn", C, "I accepted another offer.")],
    ),
    ("candidate_chioma", ("employer_brightpath", "Data Analyst Intern"), 2, []),
    (
        "candidate_ben",
        ("employer_greenleaf", "Mobile Developer (Flutter)"),
        25,
        [("reviewing", E, ""), ("shortlisted", E, "")],
    ),
    (
        "candidate_chioma",
        ("employer_greenleaf", "Python Developer, Health Records"),
        6,
        [("reviewing", E, ""), ("shortlisted", E, "Good SQL background.")],
    ),
]


class Command(BaseCommand):
    help = "Create demo employers, candidates, jobs, applications and notifications (idempotent)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Run even when DEBUG is False (e.g. on a demo server).",
        )

    def handle(self, *args, force=False, **options):
        if not settings.DEBUG and not force:
            raise CommandError(
                "DEBUG is False, so this looks like production. "
                "Refusing to create demo accounts. Pass --force to run anyway."
            )
        password = os.environ.get("DEMO_PASSWORD", "")
        if not password:
            raise CommandError("Set DEMO_PASSWORD in the environment (or .env) first.")

        self.now = timezone.now()
        with transaction.atomic():
            employers = {
                username: self._employer(username, password, fields)
                for username, fields in EMPLOYERS.items()
            }
            candidates = {
                username: self._candidate(username, password, *spec)
                for username, spec in CANDIDATES.items()
            }
            jobs = {
                key: self._job(employers[key[0]], key[1], dict(fields))
                for key, fields in JOBS.items()
            }
            for username, job_key, days_ago, steps in APPLICATIONS:
                self._application(candidates[username], jobs[job_key], days_ago, steps)

        self.stdout.write(
            self.style.SUCCESS(
                f"Demo data ready: {len(EMPLOYERS)} employers ({', '.join(EMPLOYERS)}), "
                f"{len(CANDIDATES)} candidates ({', '.join(CANDIDATES)}), {len(JOBS)} jobs, "
                f"{len(APPLICATIONS)} applications. Password: the DEMO_PASSWORD value."
            )
        )

    def _ago(self, days, hours=0):
        return self.now - timedelta(days=days, hours=hours)

    def _user(self, username, password, role):
        user, _ = User.objects.get_or_create(
            username=username, defaults={"email": f"{username}@example.com", "role": role}
        )
        user.role = role
        user.is_active = True
        user.set_password(password)  # follows DEMO_PASSWORD if it changes
        user.save()  # the profile signal creates the profile if it's missing
        return user

    def _employer(self, username, password, fields):
        profile = self._user(username, password, Role.EMPLOYER).employer_profile
        for name, value in fields.items():
            setattr(profile, name, value)
        profile.save()
        return profile

    def _candidate(self, username, password, full_name, headline, location, skills, lines):
        profile = self._user(username, password, Role.CANDIDATE).candidate_profile
        profile.headline, profile.location, profile.skills = headline, location, skills
        profile.save()
        profile.demo_resume = self._resume(profile, full_name, headline, lines)
        return profile

    def _resume(self, candidate, full_name, headline, lines):
        filename = f"{full_name} CV.pdf"
        resume = candidate.resumes.filter(original_filename=filename).first()
        if resume and resume.file.storage.exists(resume.file.name):
            pass  # already seeded, file still there
        else:
            content = resume_pdf(full_name, headline, lines)
            if resume is None:
                resume = Resume(candidate=candidate, original_filename=filename)
            resume.size_bytes = len(content)
            # Saves the file under a new random name, like a real upload.
            resume.file.save(filename, ContentFile(content), save=False)
            resume.save()
        # The demo CV is the candidate's default, so "apply" works with no body.
        candidate.resumes.filter(is_default=True).exclude(pk=resume.pk).update(is_default=False)
        if not resume.is_default:
            resume.is_default = True
            resume.save(update_fields=["is_default"])
        return resume

    def _job(self, employer, title, fields):
        days_ago = fields.pop("days_ago")
        job, _ = Job.objects.update_or_create(
            employer=employer, title=title, defaults={**fields, "closes_at": None}
        )
        # Spread posting dates so "newest first" means something.
        Job.objects.filter(pk=job.pk).update(created_at=self._ago(days_ago))
        return job

    def _application(self, candidate, job, days_ago, steps):
        expected = ["submitted", *[to for to, _, _ in steps]]
        application = Application.objects.filter(job=job, candidate=candidate).first()
        if application is not None:
            history = list(
                application.status_changes.order_by("created_at", "id").values_list(
                    "to_status", flat=True
                )
            )
            if history == expected and application.status == expected[-1]:
                return  # unchanged since the last run
            # Moved through the API since: rebuild it. CASCADE removes its
            # history and notifications too.
            application.delete()

        employer_user = job.employer.user
        candidate_user = candidate.user
        submitted_at = self._ago(days_ago)
        application = Application.objects.create(
            job=job,
            candidate=candidate,
            resume=candidate.demo_resume,
            cover_letter=f"I would like to apply for the {job.title} role.",
            status=expected[-1],
        )

        moves = [("", "submitted", candidate_user, "", submitted_at)]
        current = "submitted"
        for number, (to_status, who, note) in enumerate(steps, start=1):
            by = candidate_user if who == C else employer_user
            moves.append((current, to_status, by, note, submitted_at + timedelta(days=number)))
            current = to_status
        for from_status, to_status, by, note, at in moves:
            change = ApplicationStatusChange.objects.create(
                application=application,
                from_status=from_status,
                to_status=to_status,
                changed_by=by,
                note=note,
            )
            ApplicationStatusChange.objects.filter(pk=change.pk).update(created_at=at)
        last_at = moves[-1][4]
        Application.objects.filter(pk=application.pk).update(
            created_at=submitted_at, updated_at=last_at
        )

        # The notifications the real flow would have sent. The employer has
        # read "new application" once they moved it on.
        self._notification(
            employer_user,
            NotificationKind.NEW_APPLICATION,
            f"{candidate_user.username} applied to {job.title}.",
            application,
            submitted_at,
            read=len(moves) > 1,
        )
        if len(moves) > 1:
            from_status, to_status, by, _, at = moves[-1]
            if by == candidate_user:
                recipient = employer_user
                message = f"{candidate_user.username} withdrew their application to {job.title}."
            else:
                recipient = candidate_user
                message = (
                    f"Your application to {job.title} at {job.employer.company_name} "
                    f"moved from {from_status} to {to_status}."
                )
            self._notification(
                recipient, NotificationKind.STATUS_CHANGED, message, application, at, read=False
            )

    def _notification(self, recipient, kind, message, application, at, read):
        note = Notification.objects.create(
            recipient=recipient, kind=kind, message=message, application=application
        )
        Notification.objects.filter(pk=note.pk).update(
            created_at=at, read_at=at + timedelta(hours=2) if read else None
        )
