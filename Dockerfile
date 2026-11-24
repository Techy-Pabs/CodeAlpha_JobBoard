FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Unprivileged user that runs the app. It owns nothing in /app except the
# media folder, so a compromised process can't rewrite the code.
RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin app

# Dependencies first, in their own layer: rebuilt only when
# requirements.txt changes, not on every code edit.
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Collect static files into the image. Settings need these variables to
# load, but nothing connects to a database here, so placeholders are enough.
RUN SECRET_KEY=collectstatic-only JWT_SIGNING_KEY=collectstatic-only \
    DATABASE_URL=sqlite:////tmp/unused.db \
    python manage.py collectstatic --noinput

# Resumes are stored here when R2 isn't configured (local Docker). The only
# folder the app user can write to. docker-compose.yml mounts a volume on it
# so uploads survive a rebuild.
RUN mkdir -p /app/media && chown app:app /app/media

USER app

EXPOSE 8000

# Port, worker count and logging come from gunicorn.conf.py, which reads
# PORT (set by Render, 8000 locally) and WEB_CONCURRENCY (default 2).
# --no-control-socket: gunicorn 27's runtime control socket would live in the
# user's home directory, which this user doesn't have (and we don't use it).

ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["gunicorn", "config.wsgi:application", "--config", "gunicorn.conf.py", "--no-control-socket"]
