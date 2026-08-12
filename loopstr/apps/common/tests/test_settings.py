from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ImproperlyConfigured, ValidationError

import pytest

from config.settings import positive_int
from users.models import User


class TestLockoutConfiguration:
    """A lockout threshold below 1 does not disable the policy — it inverts it, invisibly."""

    @pytest.mark.parametrize("value", [0, -1])
    def test_a_non_positive_value_is_refused(self, value):
        with pytest.raises(ImproperlyConfigured, match="DJANGO_AUTH_LOCKOUT_MAX_ATTEMPTS"):
            positive_int("DJANGO_AUTH_LOCKOUT_MAX_ATTEMPTS", value)

    def test_the_message_names_the_variable_and_the_value(self):
        with pytest.raises(ImproperlyConfigured, match="must be 1 or greater; got 0"):
            positive_int("DJANGO_AUTH_LOCKOUT_MINUTES", 0)

    @pytest.mark.parametrize("value", [1, 5, 15])
    def test_a_usable_value_passes_through(self, value):
        assert positive_int("DJANGO_AUTH_LOCKOUT_MAX_ATTEMPTS", value) == value

    def test_the_running_configuration_is_usable(self, settings):
        # The guard runs at import; this is the assertion that the values it let through are the
        # ones the lockout actually reads.
        assert settings.AUTH_LOCKOUT_MAX_ATTEMPTS >= 1
        assert settings.AUTH_LOCKOUT_MINUTES >= 1


class TestPasswordValidators:
    """ACC-02 #3 — the rule the registration endpoint enforces is the one the criterion states.

    A validator the client knows nothing about answers 400 `UNKNOWN_ERROR` after the client's own
    check has already passed, which reads as a bug rather than as a password problem. These
    assertions are what makes re-adding one a failing test instead of a support ticket.
    """

    def test_the_configured_set_is_the_one_the_criterion_states(self, settings):
        names = [validator["NAME"] for validator in settings.AUTH_PASSWORD_VALIDATORS]

        assert names == [
            "django.contrib.auth.password_validation.MinimumLengthValidator",
            "common.validators.LetterAndNumberValidator",
        ]

    def test_the_minimum_length_is_the_eight_the_criterion_names(self, settings):
        minimum_length = settings.AUTH_PASSWORD_VALIDATORS[0]

        assert minimum_length["OPTIONS"]["min_length"] == 8

    @pytest.mark.parametrize("password", ["hedgero4", "SecretPassword1", "  8 spaces 8  ", "abcdefg1"])
    def test_a_password_the_criterion_allows_is_accepted(self, password):
        # `hedgero4` sits exactly on the eight-character boundary. `abcdefg1` is in Django's
        # common-password list and is accepted anyway: the criterion is the whole rule, and
        # `CommonPasswordValidator` is not configured.
        assert validate_password(password) is None

    def test_a_password_equal_to_an_address_is_accepted(self):
        # `UserAttributeSimilarityValidator` is not configured either — this is what that costs.
        assert validate_password("maya1lindqvist", user=User(email="maya1lindqvist@example.com")) is None

    @pytest.mark.parametrize(
        "password,reason",
        [
            ("hedger4", "8 characters"),
            ("abcdefghij", "letter and one number"),
            ("1234567890", "letter and one number"),
        ],
    )
    def test_a_password_the_criterion_refuses_is_rejected(self, password, reason):
        with pytest.raises(ValidationError) as failure:
            validate_password(password)

        assert any(reason in message for message in failure.value.messages)
