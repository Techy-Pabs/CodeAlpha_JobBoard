"""The full-text search vector for jobs, shared by the search and its index.

The GIN index in Job.Meta is built from search_vector() itself, so the
indexed expression is exactly the one the search filters on. Postgres only
uses an expression index when the query's expression matches it, so if this
function changes, `makemigrations` produces a new index to match.
"""

from django.contrib.postgres.search import SearchVector

SEARCH_CONFIG = "english"  # stemming: "developers" matches "Developer"
SEARCH_INDEX_NAME = "job_search_vector_gin"


def search_vector():
    """Title counts most, then skills, then description."""
    return (
        SearchVector("title", weight="A", config=SEARCH_CONFIG)
        + SearchVector("skills", weight="B", config=SEARCH_CONFIG)
        + SearchVector("description", weight="C", config=SEARCH_CONFIG)
    )
