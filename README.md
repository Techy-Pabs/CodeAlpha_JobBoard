# CodeAlpha Job Board

[![CI](https://github.com/Techy-Pabs/CodeAlpha_JobBoard/actions/workflows/ci.yml/badge.svg)](https://github.com/Techy-Pabs/CodeAlpha_JobBoard/actions/workflows/ci.yml)

**Live demo:** coming soon.

A REST API for a job board. Employers post jobs and move applications
through a hiring pipeline. Candidates search for jobs, upload resumes and
apply. I built it for the CodeAlpha Backend Development internship, Task 4.

## Features

- Sign up as an employer or a candidate, then log in and out with JWT access
  and refresh tokens. Usernames and emails are unique regardless of letter
  case.
- Employers fill in a company profile before they can post jobs. Jobs can be
  drafts, open or closed, and can have a closing date.
- Anyone can browse and search open jobs. Drafts, closed jobs and jobs past
  their closing date return 404 to everyone except the employer who posted
  them.
- Full-text search over title, skills and description, ranked by relevance,
  plus filters for location, job type, work mode, experience level and
  minimum salary.
- Candidates upload up to five resumes (PDF or DOCX, 5 MB each) and pick a
  default. Uploads are checked by their content, not just their name.
- Candidates apply once per job. Employers move each application through a
  fixed set of stages, and every move is kept in a history.
- Resumes are only downloadable by their owner and by employers who received
  them with an application.
- In-app notifications and emails when someone applies, when an employer
  moves an application, and when a candidate withdraws.
- Employer stats: how many applications each job has in each stage.
- Swagger UI, a health check, Docker setup, demo data and CI.

## Tech stack

- Python 3.14, Django 5.2, Django REST Framework 3.18
- PostgreSQL 16 (full-text search and a GIN index)
- Simple JWT for tokens, with a refresh token blacklist
- drf-spectacular for the OpenAPI schema and Swagger UI
- django-storages and boto3 for Cloudflare R2 (optional)
- gunicorn and WhiteNoise in the Docker image
- pytest and pytest-django for tests, ruff for linting and formatting
- GitHub Actions for CI

## Data model

| Model | What it holds | Key rules |
| --- | --- | --- |
| `User` | Django's user plus a `role` (`employer` or `candidate`) | Username and email unique ignoring case. Every user needs a role, except staff accounts. |
| `EmployerProfile` | Company name, website, location, description | One per employer, created at sign-up. Must be complete before posting a job. |
| `CandidateProfile` | Headline, location, skills | One per candidate, created at sign-up. |
| `Resume` | The file (under a random name), original filename, size, default flag | At most one default per candidate. Can't be deleted once sent with an application. |
| `Job` | Title, description, location, type, work mode, experience level, salary range, skills, status, closing date | `salary_max` at least `salary_min`. A company with jobs can't be deleted. GIN index for search. |
| `Application` | Job, candidate, resume, cover letter, status | One per candidate per job. Status must be one of the seven stages. Cover letter at most 2000 characters. |
| `ApplicationStatusChange` | From status, to status, who made the change, note, time | One row per move, starting with the move into `submitted`. |
| `Notification` | Recipient, kind, message, related application, read time | Indexed on recipient and read time for the unread list. |

The rules in the last column are database constraints, so they also hold for
data written from the admin or the Django shell.

## Application stages

An application starts as `submitted`. The job's employer moves it forward
one step at a time, or rejects it. The candidate can withdraw at any point
before a final decision.

```
Employer moves (one step at a time):

  submitted --> reviewing --> shortlisted --> interview --> offered
      |             |              |              |
      +-------------+--------------+--------------+------> rejected

Candidate moves:

  submitted, reviewing, shortlisted or interview --------> withdrawn

offered, rejected and withdrawn are final.
```

Any other move returns 400 with the current status and the moves that are
allowed from it:

```json
{
  "detail": "Cannot move an application from submitted to offered. Allowed: reviewing, rejected.",
  "current_status": "submitted",
  "allowed_moves": ["reviewing", "rejected"]
}
```

Each move locks the application row (`SELECT ... FOR UPDATE`) and writes the
new status and its history row in one transaction. Two people acting at the
same moment can't both move it from the same old status, and the history
always ends at the current status.

## How resume security works

**Content checks.** Only `.pdf` and `.docx` are accepted, up to 5 MB. The
first bytes must match the extension: a PDF has to start with `%PDF-`, and a
DOCX has to be a zip that contains `word/document.xml`. Only the zip's list
of files is read, nothing is extracted, so a zip bomb can't fill memory or
disk. The Content-Type the browser sends is ignored, since the client chooses
it.

**Stored under random names.** Each file is saved as
`resumes/<random hex>.pdf`. The name the user uploaded is kept in the
database for display only and never reaches the file system.

**Protected downloads.** There is no public URL for a resume, not even in
development. The only way to get one is `GET /api/resumes/{id}/download/`,
which allows the candidate who uploaded it and any employer who received it
with an application to one of their jobs. Everyone else gets 404, so they
can't even tell whether the resume exists. The response is sent as an
attachment with a cleaned filename, `X-Content-Type-Options: nosniff` and
`Cache-Control: private, no-store`.

**Private storage.** Locally, files live in `media/`, which is not served.
When the four `R2_*` variables are set, files go to a Cloudflare R2 bucket
instead, as private objects: no ACL is ever set, the bucket has no public
access, and the API streams the file to the user after the same permission
check. Setting only some of the `R2_*` variables stops the app at startup
with a message naming the missing ones, so a typo can't make it fall back to
the container's disk without you noticing.

## How search works

`GET /api/jobs/?q=python developer` runs a PostgreSQL full-text search.

- **Stemming.** The `english` configuration reduces words to their stem, so
  "developers" matches "Developer".
- **Search syntax.** The query uses `websearch_to_tsquery`, so people can
  type the way they would in a search engine: `"data analyst"` for a phrase,
  `python -django` to leave a word out, `react or vue` for either.
- **Weighting.** A match in the title counts most (weight A), then skills
  (B), then the description (C). Results are ordered by `ts_rank` on that
  weighted vector, newest first on ties. You can still order by `newest` or
  `salary` instead.
- **GIN index.** The weighted vector is indexed with a GIN expression index.
  The index is built from the same Python function the search uses
  (`jobs/search.py`), so the expressions always match and Postgres can use
  it. With 20,000 jobs the planner picks `Bitmap Index Scan on
  job_search_vector_gin` and the search takes about 2 ms. A test runs
  `EXPLAIN` on the real search query and fails if the index stops being used.

## Notifications

| Event | Who is told |
| --- | --- |
| A candidate applies | The job's employer |
| The employer moves an application | The candidate |
| The candidate withdraws | The employer |

Each event creates an in-app notification and sends an email. Both are
queued with `transaction.on_commit`, so they only go out once the
application or the status change is really saved. If the save fails and
rolls back, nobody is told about something that didn't happen. A failed
email is logged and never fails the request.

Locally, emails are printed to the console. In production they are sent over
SMTP if `EMAIL_HOST` is set, and written to the log otherwise.

## API endpoints

Interactive docs are at `/api/docs/` (Swagger UI) and the raw schema at
`/api/schema/`.

| Method | Path | Who | What it does |
| --- | --- | --- | --- |
| GET | `/api/health/` | Anyone | Health check (also checks the database) |
| POST | `/api/auth/register/` | Anyone | Create an employer or candidate account |
| POST | `/api/auth/token/` | Anyone | Log in: get access and refresh tokens |
| POST | `/api/auth/token/refresh/` | Anyone | Get a new access token |
| POST | `/api/auth/logout/` | Logged in | Blacklist a refresh token |
| GET | `/api/auth/me/` | Logged in | Your account |
| GET, PATCH | `/api/me/profile/` | Logged in | Your employer or candidate profile |
| GET | `/api/companies/{id}/` | Anyone | A company's public profile |
| GET | `/api/jobs/` | Anyone | Open jobs, with search, filters and ordering |
| POST | `/api/jobs/` | Employer | Post a job |
| GET | `/api/jobs/{id}/` | Anyone | One job |
| PUT, PATCH | `/api/jobs/{id}/` | The job's employer | Edit a job |
| DELETE | `/api/jobs/{id}/` | The job's employer | Delete a draft with no applications |
| POST | `/api/jobs/{id}/apply/` | Candidate | Apply (uses your default resume unless you send `resume_id`) |
| GET | `/api/jobs/{id}/applications/` | The job's employer | Applications to that job, `?status=` filter |
| GET | `/api/me/applications/` | Candidate | Your applications, `?status=` filter |
| GET | `/api/applications/{id}/` | Applicant or employer | One application with its history and `allowed_moves` |
| POST | `/api/applications/{id}/status/` | The job's employer | Move to the next stage or reject |
| POST | `/api/applications/{id}/withdraw/` | The applicant | Withdraw |
| GET, POST | `/api/me/resumes/` | Candidate | List or upload resumes |
| DELETE | `/api/me/resumes/{id}/` | Candidate | Delete a resume not used in an application |
| POST | `/api/me/resumes/{id}/set-default/` | Candidate | Make a resume your default |
| GET | `/api/resumes/{id}/download/` | Owner or receiving employer | Download a resume |
| GET | `/api/me/notifications/` | Logged in | Your notifications, newest first, `?unread=true` |
| POST | `/api/me/notifications/{id}/read/` | Logged in | Mark one as read |
| POST | `/api/me/notifications/read-all/` | Logged in | Mark all as read |
| GET | `/api/me/stats/` | Employer | Applications per job by status, plus totals |

Job list parameters: `q`, `location`, `job_type`, `work_mode`,
`experience_level`, `min_salary`, `ordering` (`newest`, `salary`,
`relevance`) and `page`. Bad values return one 400 that lists every problem.

## Auth flow

1. `POST /api/auth/register/` with `username`, `email`, `password` and
   `role` (`employer` or `candidate`).
2. `POST /api/auth/token/` with `username` and `password`. You get an
   `access` token (valid 15 minutes) and a `refresh` token (valid 7 days).
3. Send `Authorization: Bearer <access>` with each request. In Swagger UI,
   click **Authorize** and paste the access token.
4. When the access token expires, `POST /api/auth/token/refresh/` with the
   refresh token. You get a new pair and the old refresh token stops working.
5. `POST /api/auth/logout/` with the refresh token blacklists it.

Login and sign-up are limited to 5 requests a minute per IP address.

## Running with Docker

You need Docker with Compose.

```bash
cp .env.example .env
# Edit .env: set SECRET_KEY, JWT_SIGNING_KEY, POSTGRES_PASSWORD (and the
# same password inside DATABASE_URL) and DEMO_PASSWORD.
docker compose up --build
```

The web container waits for Postgres, runs the migrations and starts
gunicorn on http://localhost:8003. Swagger UI is at
http://localhost:8003/api/docs/ and the admin at http://localhost:8003/admin/.
Uploaded resumes are kept in the `media_data` volume.

To load demo data and create an admin account:

```bash
docker compose exec web python manage.py seed_demo
docker compose exec web python manage.py createsuperuser
```

Or set the three `DJANGO_SUPERUSER_*` variables in `.env`, and the container
creates the admin account itself on start.

`seed_demo` creates two employers (`employer_brightpath`,
`employer_greenleaf`), three candidates (`candidate_amara`, `candidate_ben`,
`candidate_chioma`), each with a generated PDF resume, six jobs (one draft,
one closed), eight applications spread over every stage with their history,
and the notifications they would have produced. Every demo account uses the
`DEMO_PASSWORD` from `.env`. Running it again changes nothing, except that
demo applications someone has moved since are put back to their demo state.
It refuses to run when `DEBUG` is `False` unless you pass `--force`.

## Running without Docker

You still need Postgres. The easiest way is to start only the database
container with `docker compose up -d db`, which listens on port 5436.

```bash
python3.14 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env        # then edit it as above
python manage.py migrate
python manage.py seed_demo
python manage.py runserver
```

## Environment variables

| Variable | Example or default | What it does |
| --- | --- | --- |
| `SECRET_KEY` | *(required)* | Django's secret key |
| `JWT_SIGNING_KEY` | *(required)* | Signs JWTs. Keep it different from `SECRET_KEY`, so you can log every API user out without touching anything else |
| `DEBUG` | `False` | `True` only for local development |
| `ALLOWED_HOSTS` | `localhost,127.0.0.1` | Host names the app answers to |
| `DATABASE_URL` | `postgres://job_user:change-me@localhost:5436/job_board` | Database connection. Docker Compose points it at the `db` service inside the container |
| `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` | `job_board`, `job_user` | Used by the Postgres container in Docker Compose |
| `DATABASE_CONN_MAX_AGE` | `60` | Seconds to reuse a database connection. `0` reconnects on every request |
| `DEMO_PASSWORD` | *(unset)* | Password for the accounts `seed_demo` creates |
| `SEED_DEMO_ON_START` | `False` | `True` runs `seed_demo --force` every time the container starts |
| `DJANGO_SUPERUSER_USERNAME`, `DJANGO_SUPERUSER_EMAIL`, `DJANGO_SUPERUSER_PASSWORD` | *(unset)* | If all three are set, the container creates this admin account on start (once) |
| `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET_NAME` | *(unset)* | All four set: resumes go to a private Cloudflare R2 bucket. None set: local `media/` folder |
| `EMAIL_HOST` | *(unset)* | SMTP server. Unset: emails are printed (`DEBUG=True`) or logged (`DEBUG=False`) |
| `EMAIL_PORT`, `EMAIL_USE_TLS` | `587`, `True` | SMTP port and TLS |
| `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD` | *(unset)* | SMTP login |
| `DEFAULT_FROM_EMAIL` | `Job Board <noreply@jobboard.local>` | Sender of notification emails |
| `CSRF_TRUSTED_ORIGINS` | *(unset)* | Full origins (with `https://`) allowed to submit forms such as the admin login |
| `SECURE_SSL_REDIRECT` | `False` | Redirect HTTP to HTTPS and send a one-day HSTS header. `/api/health/` is never redirected |
| `SECURE_COOKIES` | `False` | Session and CSRF cookies only over HTTPS (when `DEBUG=False`) |
| `NUM_PROXIES` | *(unset)* | Proxies in front of the app, so rate limits see each client's real IP |
| `WEB_CONCURRENCY` | `2` | gunicorn worker processes (Docker image only) |
| `PORT` | `8000` | Port gunicorn listens on (Docker image only). Render sets it |

## Tests, linter and CI

```bash
pytest              # 489 tests, needs the Postgres container running
ruff check .
ruff format --check .
```

The tests cover the stage rules (every allowed and refused move, and who may
make it), the database constraints, resume content checks and download
permissions, search ranking and the index, notifications (including that a
failed save sends nothing and a broken email server doesn't break applying),
the stats query count, the storage switch to R2 (with no real R2 calls), the
Docker entrypoint, production settings and the demo data command.

GitHub Actions runs ruff and the full test suite against Postgres 16 on every
push and pull request, with `DEBUG=False` as in production.

## Secret check

A pre-commit hook in `.githooks/pre-commit` blocks a commit if it stages a
`.env` file or a key file, contains something that looks like a secret
(private keys, Django insecure keys, GitHub and AWS tokens), or contains any
value copied from your local `.env`. Turn it on once per clone:

```bash
git config core.hooksPath .githooks
```

## Production notes

- The Docker image runs as an unprivileged user that can only write to the
  media folder. Static files are collected into the image and served by
  WhiteNoise with long cache headers.
- `docker/entrypoint.sh` waits for the database, runs migrations, creates the
  admin account and (if asked) loads demo data. If any step fails it stops
  with an `ERROR:` line and the app never starts half set up.
- Resumes on a container's own disk are lost on every redeploy. Use R2 (or
  another persistent store) in production.
- Rate limit counters live in each gunicorn worker's memory, so with two
  workers a client can get roughly twice the limit. Point `CACHES` at Redis
  for strict limits.
- Emails are sent during the request, after the commit. A slow mail server
  slows that response down (there is a 10 second timeout). A task queue would
  move this out of the request.

## Screenshots

Taken from the Docker setup after running `seed_demo`.

### Swagger UI

![Swagger UI](docs/screenshots/swagger.png)

### Job search, ranked by relevance

`GET /api/jobs/?q=python developer`: the job with "Python Developer" in its
title ranks above the one that only lists Python in its skills.

![Job search](docs/screenshots/search.png)

### A candidate's applications

![Candidate applications](docs/screenshots/candidate-applications.png)

### A refused status move

![Refused move](docs/screenshots/refused-move.png)

### Employer stats

![Employer stats](docs/screenshots/employer-stats.png)

### Notifications

![Notifications](docs/screenshots/notifications.png)

### Admin: an application with its status history

![Admin application page](docs/screenshots/admin-application.png)
