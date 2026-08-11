from django.conf import settings
from django.urls import NoReverseMatch, reverse

import pytest
from rest_framework import status

from common.schema import AUTH_ERROR_CODES, COOKIE_SECURITY_SCHEME_NAME, ERROR_COMPONENT_NAME


class TestHealthCheckView:
    def test_answers_ok_without_authentication(self, api_client):
        response = api_client.get(reverse("common:health-check"))

        assert response.status_code == status.HTTP_200_OK
        assert response.data == {"status": "ok"}


class TestApiDocumentation:
    def test_swagger_ui_is_served_without_authentication(self, api_client):
        response = api_client.get(reverse("common:docs"))

        assert response.status_code == status.HTTP_200_OK

    def test_schema_is_served_without_authentication(self, api_client):
        response = api_client.get(reverse("common:schema"))

        assert response.status_code == status.HTTP_200_OK
        assert response.data["openapi"].startswith("3.")

    def test_schema_declares_the_session_cookie(self, api_client):
        response = api_client.get(reverse("common:schema"))

        cookie_scheme = response.data["components"]["securitySchemes"][COOKIE_SECURITY_SCHEME_NAME]
        assert cookie_scheme["type"] == "apiKey"
        assert cookie_scheme["in"] == "cookie"
        assert cookie_scheme["name"] == settings.SESSION_COOKIE_NAME

    def test_schema_declares_the_error_envelope(self, api_client):
        response = api_client.get(reverse("common:schema"))

        error = response.data["components"]["schemas"][ERROR_COMPONENT_NAME]
        assert error["required"] == ["code"]
        assert error["properties"]["code"]["enum"] == list(AUTH_ERROR_CODES)
        assert set(error["properties"]) == {"code", "message"}

    def test_documentation_is_absent_when_disabled(self, api_client, api_docs_disabled):
        # Hardcoded paths, because the point of the assertion is that there is nothing to reverse.
        assert api_client.get("/docs/").status_code == status.HTTP_404_NOT_FOUND
        assert api_client.get("/schema/").status_code == status.HTTP_404_NOT_FOUND

        with pytest.raises(NoReverseMatch):
            reverse("common:docs")

        with pytest.raises(NoReverseMatch):
            reverse("common:schema")
