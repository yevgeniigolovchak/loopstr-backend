import pytest
from rest_framework.test import APIClient

from users.tests.factories import UserFactory


@pytest.fixture
def api_client() -> APIClient:
    """Unauthenticated DRF client; authenticate it inside the test that needs a user."""
    return APIClient()


@pytest.fixture
def user():
    return UserFactory()
