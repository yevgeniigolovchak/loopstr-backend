from importlib import import_module

from django.apps import apps

import pytest

from users.models import User
from users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db

normalize_email_case = import_module("users.migrations.0003_normalize_email_case").normalize_email_case


class TestNormalizeEmailCase:
    """The backfill that brings rows written before `save()` normalised addresses into line."""

    def test_a_collision_is_named_rather_than_raised_as_an_integrity_error(self, user):
        UserFactory(email="taken@example.com")
        User.objects.filter(pk=user.pk).update(email="Taken@Example.com")

        with pytest.raises(RuntimeError, match="Taken@Example.com"):
            normalize_email_case(apps, None)

    def test_a_row_written_around_save_is_lowercased(self, user):
        # `update()` is how a row reaches the table without passing through `save()` — a bulk
        # insert, a data migration, a hand-written `UPDATE`.
        User.objects.filter(pk=user.pk).update(email="Mixed@Example.COM")

        normalize_email_case(apps, None)

        user.refresh_from_db()
        assert user.email == "mixed@example.com"

    def test_a_row_that_is_already_lowercase_is_left_alone(self, user):
        modified_before = user.modified

        normalize_email_case(apps, None)

        user.refresh_from_db()
        assert user.modified == modified_before

    def test_it_can_run_twice(self, user):
        User.objects.filter(pk=user.pk).update(email="Mixed@Example.COM")

        normalize_email_case(apps, None)
        normalize_email_case(apps, None)

        user.refresh_from_db()
        assert user.email == "mixed@example.com"
