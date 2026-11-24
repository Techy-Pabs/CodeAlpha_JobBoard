"""gunicorn settings, read from the environment.

Render sets PORT and expects the app to listen on 0.0.0.0:$PORT. Locally
PORT is unset, so the app listens on 8000 as before.
"""

import os


def _positive_int(name, default):
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        raise SystemExit(f"{name} must be a whole number, got {raw!r}.") from None
    if value < 1:
        raise SystemExit(f"{name} must be at least 1, got {value}.")
    return value


bind = f"0.0.0.0:{_positive_int('PORT', 8000)}"

# Each worker is a full copy of Django (roughly 60-80 MB). Two fit easily in
# the 512 MB of Render's free plan; raise WEB_CONCURRENCY on a bigger plan.
workers = _positive_int("WEB_CONCURRENCY", 2)

# Log every request to stdout, where Docker and Render collect it.
accesslog = "-"
