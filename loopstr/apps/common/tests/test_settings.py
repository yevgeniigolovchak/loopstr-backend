from django.core.exceptions import ImproperlyConfigured

import pytest

from config.settings import positive_int


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
