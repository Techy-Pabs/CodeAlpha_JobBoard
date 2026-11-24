# Reuse the application fixtures (open_job, application, ...) in these tests.
from applications.tests.conftest import (  # noqa: F401
    application,
    make_application,
    open_job,
    other_candidate,
    other_employer,
)
