from django.db import IntegrityError

import pytest

from users.models import User
from users.tests.factories import USER_PASSWORD, UserFactory

pytestmark = pytest.mark.django_db


class TestUserManager:
    def test_create_user(self):
        user = User.objects.create_user(
            email="Member@Example.COM",
            password=USER_PASSWORD,
            full_name="Member One",
        )

        assert User.objects.filter(pk=user.pk).exists()
        assert user.email == "Member@example.com"  # normalize_email lowercases the domain
        assert user.full_name == "Member One"
        assert user.role == User.ROLES.member
        assert user.check_password(USER_PASSWORD)
        assert user.is_active
        assert not user.is_staff
        assert not user.is_superuser

    def test_create_user_without_email_is_rejected(self):
        with pytest.raises(ValueError, match="The given email must be set"):
            User.objects.create_user(email="", password=USER_PASSWORD)

    def test_create_superuser(self):
        user = User.objects.create_superuser(email="admin@example.com", password=USER_PASSWORD)

        assert user.is_staff
        assert user.is_superuser
        assert user.role == User.ROLES.member

    @pytest.mark.parametrize(
        "extra_fields,message",
        [
            ({"is_staff": False}, "Superuser must have is_staff=True."),
            ({"is_superuser": False}, "Superuser must have is_superuser=True."),
        ],
    )
    def test_create_superuser_requires_both_flags(self, extra_fields, message):
        with pytest.raises(ValueError, match=message):
            User.objects.create_superuser(email="admin@example.com", password=USER_PASSWORD, **extra_fields)


class TestUser:
    def test_email_is_the_username_field(self):
        assert User.USERNAME_FIELD == "email"
        assert User.REQUIRED_FIELDS == ()
        assert not hasattr(User, "username")

    def test_email_is_unique(self, user):
        with pytest.raises(IntegrityError):
            User.objects.create_user(email=user.email, password=USER_PASSWORD)

    def test_defaults_to_the_member_role(self):
        assert UserFactory().role == User.ROLES.member

    def test_str_is_the_email(self, user):
        assert str(user) == user.email

    def test_name_methods(self):
        user = UserFactory(full_name="Member One")

        assert user.get_full_name() == "Member One"
        assert user.get_short_name() == "Member One"

    def test_short_name_falls_back_to_the_email(self):
        user = UserFactory(full_name="")

        assert user.get_short_name() == user.email
