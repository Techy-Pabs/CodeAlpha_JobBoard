"""docker/entrypoint.sh: which startup tasks run, and that failures stop it.

A fake "python" on PATH records each call instead of running Django, so the
shell logic is tested on its own, without a database.
"""

import os
import subprocess
from pathlib import Path

import pytest

ENTRYPOINT = Path(__file__).resolve().parents[2] / "docker" / "entrypoint.sh"

FAKE_PYTHON = """#!/bin/sh
echo "$*" >> "$FAKE_LOG"
if [ "$1" = "-" ]; then cat > /dev/null; fi
if [ -n "$FAKE_FAIL_ON" ]; then
    case "$*" in *"$FAKE_FAIL_ON"*) echo "fake failure" >&2; exit 3 ;; esac
fi
exit 0
"""


@pytest.fixture
def run_entrypoint(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "python"
    fake.write_text(FAKE_PYTHON)
    fake.chmod(0o755)
    log = tmp_path / "calls.log"

    def run(fail_on="", **env):
        full_env = {
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "FAKE_LOG": str(log),
            "FAKE_FAIL_ON": fail_on,
            **env,
        }
        result = subprocess.run(
            ["sh", str(ENTRYPOINT), "echo", "APP STARTED"],
            env=full_env,
            capture_output=True,
            text=True,
        )
        calls = log.read_text().splitlines() if log.exists() else []
        log.unlink(missing_ok=True)
        return result, calls

    return run


def test_default_start_runs_migrate_and_admin_check_but_no_demo_data(run_entrypoint):
    result, calls = run_entrypoint()
    assert result.returncode == 0, result.stderr
    assert calls == ["-", "manage.py migrate --noinput", "manage.py ensure_superuser"]
    assert "APP STARTED" in result.stdout


@pytest.mark.parametrize("value", ["True", "true", "1", "yes"])
def test_seed_demo_runs_when_enabled(run_entrypoint, value):
    result, calls = run_entrypoint(SEED_DEMO_ON_START=value)
    assert result.returncode == 0, result.stderr
    assert calls[-1] == "manage.py seed_demo --force"
    assert calls.index("manage.py ensure_superuser") < calls.index("manage.py seed_demo --force")
    assert "APP STARTED" in result.stdout


@pytest.mark.parametrize("value", ["False", "false", "0", ""])
def test_seed_demo_skipped_when_disabled(run_entrypoint, value):
    result, calls = run_entrypoint(SEED_DEMO_ON_START=value)
    assert result.returncode == 0, result.stderr
    assert "manage.py seed_demo --force" not in calls


def test_unrecognised_seed_value_stops_startup(run_entrypoint):
    result, calls = run_entrypoint(SEED_DEMO_ON_START="Ture")
    assert result.returncode != 0
    assert "SEED_DEMO_ON_START must be True or False" in result.stderr
    assert "APP STARTED" not in result.stdout


@pytest.mark.parametrize(
    ("fail_on", "message"),
    [
        ("migrate", "Database migrations failed"),
        ("ensure_superuser", "Could not create the admin account"),
        ("seed_demo", "Loading demo data failed"),
    ],
)
def test_failed_step_stops_with_clear_error(run_entrypoint, fail_on, message):
    result, calls = run_entrypoint(fail_on=fail_on, SEED_DEMO_ON_START="True")
    assert result.returncode != 0
    assert f"ERROR: {message}" in result.stderr
    assert "the app was not started" in result.stderr
    assert "APP STARTED" not in result.stdout


def test_admin_failure_skips_demo_data(run_entrypoint):
    _, calls = run_entrypoint(fail_on="ensure_superuser", SEED_DEMO_ON_START="True")
    assert "manage.py seed_demo --force" not in calls
