from django.contrib.postgres.search import SearchQuery, SearchRank, SearchVector
from django.db.models import F
from rest_framework.exceptions import ValidationError
from rest_framework.filters import BaseFilterBackend

from .models import ExperienceLevel, JobType, WorkMode

SEARCH_CONFIG = "english"  # stemming: "developers" matches "Developer"
MAX_QUERY_LENGTH = 200

CHOICE_PARAMS = {
    "job_type": JobType,
    "work_mode": WorkMode,
    "experience_level": ExperienceLevel,
}
ORDERINGS = ("newest", "salary", "relevance")


def search_vector():
    """Title counts most, then skills, then description."""
    return (
        SearchVector("title", weight="A", config=SEARCH_CONFIG)
        + SearchVector("skills", weight="B", config=SEARCH_CONFIG)
        + SearchVector("description", weight="C", config=SEARCH_CONFIG)
    )


class JobSearchFilter(BaseFilterBackend):
    """Search, filters and ordering for the job list.

    ?q=          full-text search over title (A), skills (B), description (C)
    ?location=   contains, ignoring case
    ?job_type= ?work_mode= ?experience_level=   exact choice
    ?min_salary= jobs whose salary_max is at least this
    ?ordering=   newest (default), salary (highest first), relevance (needs q;
                 the default when q is given)

    Every bad value is reported at once as a 400.
    """

    def filter_queryset(self, request, queryset, view):
        # Only the list is searched. Detail, update and the custom actions use
        # the same queryset and must not be affected by stray query params.
        if getattr(view, "action", None) != "list":
            return queryset

        params = request.query_params
        errors = {}

        def get(name):
            return (params.get(name) or "").strip()

        q = get("q")
        if len(q) > MAX_QUERY_LENGTH:
            errors["q"] = [f"Use at most {MAX_QUERY_LENGTH} characters."]

        if location := get("location"):
            queryset = queryset.filter(location__icontains=location)

        for name, choices in CHOICE_PARAMS.items():
            value = get(name)
            if not value:
                continue
            if value not in choices.values:
                errors[name] = [f"Choose one of: {', '.join(choices.values)}."]
            else:
                queryset = queryset.filter(**{name: value})

        if raw := get("min_salary"):
            if raw.isdigit() and int(raw) <= 2_147_483_647:
                queryset = queryset.filter(salary_max__gte=int(raw))
            else:
                errors["min_salary"] = ["Enter a whole number, 0 or more."]

        ordering = get("ordering") or ("relevance" if q else "newest")
        if ordering not in ORDERINGS:
            errors["ordering"] = [f"Choose one of: {', '.join(ORDERINGS)}."]
        elif ordering == "relevance" and not q:
            errors["ordering"] = ["relevance ordering needs a search term in q."]

        if errors:
            raise ValidationError(errors)

        if q:
            query = SearchQuery(q, config=SEARCH_CONFIG, search_type="websearch")
            vector = search_vector()
            queryset = queryset.annotate(search=vector, rank=SearchRank(vector, query)).filter(
                search=query
            )

        # -id last so pages are stable when the other keys tie.
        if ordering == "relevance":
            return queryset.order_by("-rank", "-created_at", "-id")
        if ordering == "salary":
            return queryset.order_by(F("salary_max").desc(nulls_last=True), "-created_at", "-id")
        return queryset.order_by("-created_at", "-id")

    def get_schema_operation_parameters(self, view):
        # Read by drf-spectacular so Swagger lists the query parameters.
        def param(name, description, schema):
            return {
                "name": name,
                "in": "query",
                "required": False,
                "description": description,
                "schema": schema,
            }

        string = {"type": "string"}
        return [
            param("q", "Full-text search over title, skills and description.", string),
            param("location", "Location contains this text (any case).", string),
            *[
                param(name, f"Exact {name}.", {"type": "string", "enum": list(choices.values)})
                for name, choices in CHOICE_PARAMS.items()
            ],
            param(
                "min_salary",
                "Jobs whose maximum salary is at least this.",
                {"type": "integer", "minimum": 0},
            ),
            param(
                "ordering",
                "newest (default), salary (highest first) or relevance (needs q; "
                "the default when q is given).",
                {"type": "string", "enum": list(ORDERINGS)},
            ),
        ]
