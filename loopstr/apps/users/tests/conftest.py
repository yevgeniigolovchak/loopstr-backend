import pytest

from users.tests.factories import USER_PASSWORD, UserFactory


@pytest.fixture
def member():
    """An active member whose password is `USER_PASSWORD`."""
    return UserFactory(email="member@example.com")


@pytest.fixture
def credentials(member):
    """A valid login payload, in the camelCase the frontend sends."""
    return {"email": member.email, "password": USER_PASSWORD, "rememberMe": False}


@pytest.fixture
def registration():
    """A valid registration payload for an address no fixture holds, in the frontend's camelCase."""
    return {"fullName": "Maya Lindqvist", "email": "maya@example.com", "password": USER_PASSWORD}
