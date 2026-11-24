from unittest import mock

import pytest
from django.db import OperationalError
from django.urls import reverse

HEALTH = reverse("health")


@pytest.mark.django_db
def test_health_ok(api_client):
    response = api_client.get(HEALTH)
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.django_db
def test_health_is_public_even_with_stale_token(api_client):
    api_client.credentials(HTTP_AUTHORIZATION="Bearer not-a-real-token")
    assert api_client.get(HEALTH).status_code == 200


@pytest.mark.django_db
def test_health_reports_503_when_database_is_down(api_client):
    with mock.patch("config.views.connection.cursor", side_effect=OperationalError("down")):
        response = api_client.get(HEALTH)
    assert response.status_code == 503
    assert response.json() == {"status": "error"}


def test_health_rejects_post(api_client):
    assert api_client.post(HEALTH).status_code == 405
