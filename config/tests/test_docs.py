import pytest
from django.urls import reverse


@pytest.mark.django_db
def test_schema_is_public(api_client):
    response = api_client.get(reverse("schema"))
    assert response.status_code == 200
    assert b"CodeAlpha Job Board API" in response.content


@pytest.mark.django_db
def test_schema_ignores_stale_bearer_token(api_client):
    api_client.credentials(HTTP_AUTHORIZATION="Bearer not-a-real-token")
    assert api_client.get(reverse("schema")).status_code == 200


@pytest.mark.django_db
def test_swagger_ui_is_public(api_client):
    assert api_client.get(reverse("swagger-ui")).status_code == 200


def test_root_redirects_to_swagger_ui(api_client):
    response = api_client.get("/")
    assert response.status_code == 302
    assert response["Location"] == reverse("swagger-ui")
