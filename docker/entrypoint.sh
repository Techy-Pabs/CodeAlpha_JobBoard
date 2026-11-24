#!/bin/sh
# Wait for Postgres, apply migrations, run the startup tasks, then run the
# container's command (gunicorn by default, or e.g. "python manage.py ...").
#
# Any failure stops the container with a non-zero exit code before the app
# starts, so it never runs half set up. On Render that marks the deploy as
# failed and keeps the previous version serving.
set -e

fail() {
    echo "ERROR: $1" >&2
    echo "ERROR: Startup stopped; the app was not started." >&2
    exit 1
}

python - <<'PY'
import os
import sys
import time

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from django.db import connection
from django.db.utils import OperationalError

for attempt in range(1, 31):
    try:
        connection.ensure_connection()
        print("Postgres is ready.", flush=True)
        break
    except OperationalError:
        print(f"Waiting for Postgres ({attempt}/30)...", flush=True)
        time.sleep(1)
else:
    sys.exit("Postgres was not reachable after 30 seconds.")
PY

python manage.py migrate --noinput || fail "Database migrations failed (see above)."

# Render's free plan has no shell, so the admin account and demo data are
# created here, from environment variables. Both steps are safe to repeat.

# Creates DJANGO_SUPERUSER_USERNAME if all three DJANGO_SUPERUSER_* variables
# are set and the user doesn't exist yet. Does nothing if none are set.
python manage.py ensure_superuser || fail "Could not create the admin account (see above)."

case "${SEED_DEMO_ON_START:-}" in
    True | true | TRUE | 1 | yes | Yes | on)
        echo "SEED_DEMO_ON_START is on: loading demo data."
        python manage.py seed_demo --force || fail "Loading demo data failed (see above)."
        ;;
    "" | False | false | FALSE | 0 | no | No | off)
        ;;
    *)
        fail "SEED_DEMO_ON_START must be True or False, got '$SEED_DEMO_ON_START'."
        ;;
esac

exec "$@"
