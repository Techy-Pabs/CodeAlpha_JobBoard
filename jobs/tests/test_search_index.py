"""The job search can use the GIN index on its search vector.

Postgres only uses an expression index when the query's expression is the
same as the indexed one. If someone changes the search without changing the
index (or the other way round), this test fails.
"""

import pytest
from django.db import connection
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from jobs.filters import JobSearchFilter
from jobs.models import Job
from jobs.search import SEARCH_INDEX_NAME

pytestmark = pytest.mark.django_db


class ListView:
    action = "list"


def search_queryset(q):
    """The queryset the job list runs for ?q=, built by the real filter."""
    request = Request(APIRequestFactory().get("/api/jobs/", {"q": q}))
    return JobSearchFilter().filter_queryset(request, Job.objects.open(), ListView())


def test_index_exists_on_the_jobs_table():
    with connection.cursor() as cursor:
        constraints = connection.introspection.get_constraints(cursor, Job._meta.db_table)
    assert constraints[SEARCH_INDEX_NAME]["type"] == "gin"


def test_search_query_uses_the_index(job):
    # With a handful of rows a sequential scan is cheaper, so turn it off for
    # this transaction: the planner then shows whether the index can be used.
    with connection.cursor() as cursor:
        cursor.execute("SET LOCAL enable_seqscan = off")
    plan = search_queryset("backend developer").explain()
    assert f"Bitmap Index Scan on {SEARCH_INDEX_NAME}" in plan, plan


def test_search_still_finds_jobs_with_the_index(job):
    job.status = "open"
    job.save()
    assert list(search_queryset("developers")) == [job]
