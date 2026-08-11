from datetime import timedelta

from django.db import IntegrityError
from django.utils import timezone

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
        assert user.email == "member@example.com"  # normalize_email lowercases the whole address
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

    def test_email_is_unique_regardless_of_case(self, user):
        # The address is lowercased before it is written, so a differently-cased duplicate collides
        # with the existing row on the column's own unique index rather than becoming a second
        # account the login lookup would then have to choose between.
        with pytest.raises(IntegrityError):
            User.objects.create_user(email=user.email.upper(), password=USER_PASSWORD)

    def test_save_lowercases_the_address(self):
        # The manager is not the only way in — the admin, a factory and a plain `User(...)` all
        # reach `save()` directly.
        user = User(email="Mixed@Example.COM")
        user.set_password(USER_PASSWORD)
        user.save()

        user.refresh_from_db()
        assert user.email == "mixed@example.com"

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


class TestUserLockout:
    """ACC-01 #6 — five consecutive failures lock the account for fifteen minutes."""

    def test_is_not_locked_out_by_default(self, user):
        assert user.failed_login_attempts == 0
        assert user.locked_until is None
        assert not user.is_locked_out

    def test_is_locked_out_while_the_window_is_open(self, user):
        user.locked_until = timezone.now() + timedelta(minutes=1)

        assert user.is_locked_out

    def test_is_not_locked_out_once_the_window_has_passed(self, user):
        user.locked_until = timezone.now() - timedelta(seconds=1)

        assert not user.is_locked_out

    def test_lockout_seconds_remaining_is_zero_when_usable(self, user):
        assert user.lockout_seconds_remaining == 0

    def test_lockout_seconds_remaining_counts_the_window_down(self, user):
        user.locked_until = timezone.now() + timedelta(minutes=15)

        assert 890 < user.lockout_seconds_remaining <= 900

    def test_register_failed_login_increments_the_counter(self, user):
        user.register_failed_login()

        user.refresh_from_db()
        assert user.failed_login_attempts == 1
        assert user.locked_until is None

    def test_register_failed_login_locks_on_the_configured_attempt(self, user, settings):
        settings.AUTH_LOCKOUT_MAX_ATTEMPTS = 3

        for _ in range(2):
            user.register_failed_login()
        assert not user.is_locked_out

        user.register_failed_login()

        user.refresh_from_db()
        assert user.is_locked_out

    def test_register_failed_login_clears_the_counter_when_it_locks(self, user, settings):
        settings.AUTH_LOCKOUT_MAX_ATTEMPTS = 2

        for _ in range(2):
            user.register_failed_login()

        user.refresh_from_db()
        # A fresh set of attempts waits on the other side of the window, so nothing has to notice
        # that the lock expired.
        assert user.failed_login_attempts == 0

    def test_lock_duration_comes_from_settings(self, user, settings):
        settings.AUTH_LOCKOUT_MAX_ATTEMPTS = 1
        settings.AUTH_LOCKOUT_MINUTES = 30

        user.register_failed_login()

        user.refresh_from_db()
        assert timedelta(minutes=29) < user.locked_until - timezone.now() <= timedelta(minutes=30)

    def test_reset_login_lockout_clears_the_counter_and_the_lock(self, user):
        user.failed_login_attempts = 4
        user.locked_until = timezone.now() - timedelta(minutes=1)
        user.save(update_fields=("failed_login_attempts", "locked_until"))

        user.reset_login_lockout()

        user.refresh_from_db()
        assert user.failed_login_attempts == 0
        assert user.locked_until is None

    def test_reset_login_lockout_writes_nothing_when_already_clear(self, user, django_assert_num_queries):
        with django_assert_num_queries(0):
            user.reset_login_lockout()
