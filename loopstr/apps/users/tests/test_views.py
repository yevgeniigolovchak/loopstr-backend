import logging
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError
from django.urls import reverse
from django.utils import timezone

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from common.schema import AUTH_ERROR_CODES, ERROR_COMPONENT_NAME
from users.models import User
from users.tests.factories import USER_PASSWORD, UserFactory

pytestmark = pytest.mark.django_db

SESSION_USER_KEY = "_auth_user_id"


def fail_login(api_client, member, times):
    """Submit `times` wrong passwords and return the last response."""
    url = reverse("api:users:auth:login")
    payload = {"email": member.email, "password": "WrongPassword1", "rememberMe": False}
    for _ in range(times):
        response = api_client.post(url, payload)

    return response


class TestLoginView:
    def test_valid_credentials_open_a_session(self, api_client, credentials, member):
        response = api_client.post(reverse("api:users:auth:login"), credentials)

        assert response.status_code == status.HTTP_200_OK
        assert settings.SESSION_COOKIE_NAME in response.cookies
        assert api_client.session[SESSION_USER_KEY] == str(member.pk)

    def test_success_returns_no_body(self, api_client, credentials):
        # The contract does not have the frontend read one, and inventing a shape here would fix a
        # payload the next story has to keep.
        response = api_client.post(reverse("api:users:auth:login"), credentials)

        assert response.content == b""

    def test_remember_me_keeps_the_session_for_the_configured_age(self, api_client, credentials):
        response = api_client.post(reverse("api:users:auth:login"), {**credentials, "rememberMe": True})

        cookie = response.cookies[settings.SESSION_COOKIE_NAME]
        assert int(cookie["max-age"]) == settings.SESSION_COOKIE_AGE
        assert not api_client.session.get_expire_at_browser_close()

    def test_without_remember_me_the_cookie_dies_with_the_browser(self, api_client, credentials):
        response = api_client.post(reverse("api:users:auth:login"), {**credentials, "rememberMe": False})

        cookie = response.cookies[settings.SESSION_COOKIE_NAME]
        assert cookie["max-age"] == ""
        assert cookie["expires"] == ""
        assert api_client.session.get_expire_at_browser_close()

    def test_email_is_matched_case_insensitively(self, api_client, credentials, member):
        response = api_client.post(
            reverse("api:users:auth:login"),
            {**credentials, "email": member.email.upper()},
        )

        assert response.status_code == status.HTTP_200_OK

    def test_success_clears_the_failed_attempt_counter(self, api_client, credentials, member):
        fail_login(api_client, member, times=2)

        api_client.post(reverse("api:users:auth:login"), credentials)

        member.refresh_from_db()
        assert member.failed_login_attempts == 0

    def test_no_csrf_token_is_required(self, credentials):
        # The frontend sends none, and the view declares no authenticator so nothing enforces one.
        api_client = APIClient(enforce_csrf_checks=True)

        response = api_client.post(reverse("api:users:auth:login"), credentials)

        assert response.status_code == status.HTTP_200_OK


class TestSessionCookieFlags:
    """docs/auth-api.md fixes all three flags, and the published schema promises them.

    Without an assertion on each, deleting `SESSION_COOKIE_HTTPONLY` or moving `SameSite` to
    `"None"` leaves the whole suite green while shipping a session cookie that JavaScript can read
    or that rides along on a cross-site request.
    """

    def test_the_session_cookie_is_http_only(self, api_client, credentials):
        response = api_client.post(reverse("api:users:auth:login"), credentials)

        assert response.cookies[settings.SESSION_COOKIE_NAME]["httponly"]

    def test_the_session_cookie_is_same_site_lax(self, api_client, credentials):
        response = api_client.post(reverse("api:users:auth:login"), credentials)

        assert response.cookies[settings.SESSION_COOKIE_NAME]["samesite"] == "Lax"

    def test_the_session_cookie_is_secure_where_the_environment_says_so(self, api_client, credentials, settings):
        # The flag is environment-driven because local development speaks HTTP; what matters is
        # that turning it on reaches the cookie.
        settings.SESSION_COOKIE_SECURE = True

        response = api_client.post(reverse("api:users:auth:login"), credentials)

        assert response.cookies[settings.SESSION_COOKIE_NAME]["secure"]


class TestLoginViewRejections:
    def test_unknown_email_is_rejected(self, api_client, credentials):
        response = api_client.post(
            reverse("api:users:auth:login"),
            {**credentials, "email": "nobody@example.com"},
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.data["code"] == "INVALID_CREDENTIALS"

    def test_wrong_password_is_rejected(self, api_client, credentials):
        response = api_client.post(
            reverse("api:users:auth:login"),
            {**credentials, "password": "WrongPassword1"},
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.data["code"] == "INVALID_CREDENTIALS"

    def test_unknown_email_and_wrong_password_are_indistinguishable(self, api_client, credentials):
        # ACC-01 #4 — the response must not reveal whether the account exists.
        unknown = api_client.post(
            reverse("api:users:auth:login"),
            {**credentials, "email": "nobody@example.com"},
        )
        wrong = api_client.post(
            reverse("api:users:auth:login"),
            {**credentials, "password": "WrongPassword1"},
        )

        assert unknown.status_code == wrong.status_code
        assert unknown.data == wrong.data

    def test_the_rejection_reports_the_message_the_requirement_names(self, api_client, credentials):
        # ACC-01 #4 names the text; the frontend renders its own copy from `code`, but the two
        # saying different things is how a log line stops matching what the user was shown.
        response = api_client.post(
            reverse("api:users:auth:login"),
            {**credentials, "password": "WrongPassword1"},
        )

        assert response.data["message"] == "Email or password is incorrect"

    def test_inactive_account_is_rejected_the_same_way(self, api_client):
        member = UserFactory(email="dormant@example.com", is_active=False)

        response = api_client.post(
            reverse("api:users:auth:login"),
            {"email": member.email, "password": USER_PASSWORD, "rememberMe": False},
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.data["code"] == "INVALID_CREDENTIALS"

    def test_rejection_opens_no_session(self, api_client, credentials):
        api_client.post(reverse("api:users:auth:login"), {**credentials, "password": "WrongPassword1"})

        assert SESSION_USER_KEY not in api_client.session

    def test_wrong_password_counts_towards_the_lockout(self, api_client, credentials, member):
        api_client.post(reverse("api:users:auth:login"), {**credentials, "password": "WrongPassword1"})

        member.refresh_from_db()
        assert member.failed_login_attempts == 1

    def test_unknown_email_counts_towards_nothing(self, api_client, credentials, member):
        api_client.post(reverse("api:users:auth:login"), {**credentials, "email": "nobody@example.com"})

        member.refresh_from_db()
        assert member.failed_login_attempts == 0

    @pytest.mark.parametrize("missing", ["email", "password", "rememberMe"])
    def test_incomplete_body_is_rejected(self, api_client, credentials, missing):
        payload = {key: value for key, value in credentials.items() if key != missing}

        response = api_client.post(reverse("api:users:auth:login"), payload)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data["code"] == "UNKNOWN_ERROR"
        assert missing in response.data["message"]

    @pytest.mark.parametrize(
        "payload_change",
        [
            {"email": "nobody@example.com"},
            {"password": "WrongPassword1"},
            {"email": "not-an-email"},
        ],
    )
    def test_error_body_is_the_contract_envelope(self, api_client, credentials, payload_change):
        response = api_client.post(reverse("api:users:auth:login"), {**credentials, **payload_change})

        assert set(response.data) == {"code", "message"}
        assert response.data["code"] in AUTH_ERROR_CODES

    def test_get_is_not_allowed(self, api_client):
        response = api_client.get(reverse("api:users:auth:login"))

        assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED

    def test_the_route_carries_no_trailing_slash(self, api_client, credentials):
        # APPEND_SLASH = False, so the slashed variant is not redirected — it simply is not there.
        assert reverse("api:users:auth:login") == "/api/v1/auth/login"

        response = api_client.post("/api/v1/auth/login/", credentials)

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_neither_the_password_nor_the_email_reaches_the_log(self, api_client, credentials, caplog):
        with caplog.at_level(logging.INFO, logger="users"):
            api_client.post(reverse("api:users:auth:login"), credentials)
            api_client.post(reverse("api:users:auth:login"), {**credentials, "password": "WrongPassword1"})
            api_client.post(reverse("api:users:auth:login"), {**credentials, "email": "nobody@example.com"})

        assert caplog.text
        assert USER_PASSWORD not in caplog.text
        assert "WrongPassword1" not in caplog.text
        assert credentials["email"] not in caplog.text


class TestLoginViewLockout:
    """ACC-01 #6 — five consecutive failures, then fifteen minutes locked."""

    def test_attempts_below_the_threshold_stay_generic(self, api_client, member):
        response = fail_login(api_client, member, times=settings.AUTH_LOCKOUT_MAX_ATTEMPTS - 1)

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.data["code"] == "INVALID_CREDENTIALS"

    def test_the_attempt_that_trips_the_threshold_reports_the_lock(self, api_client, member):
        response = fail_login(api_client, member, times=settings.AUTH_LOCKOUT_MAX_ATTEMPTS)

        assert response.status_code == status.HTTP_423_LOCKED
        assert response.data["code"] == "ACCOUNT_LOCKED"
        member.refresh_from_db()
        assert member.is_locked_out

    def test_the_lock_carries_a_retry_after(self, api_client, member):
        response = fail_login(api_client, member, times=settings.AUTH_LOCKOUT_MAX_ATTEMPTS)

        assert 0 < int(response["Retry-After"]) <= settings.AUTH_LOCKOUT_MINUTES * 60

    def test_the_lock_reports_the_message_the_requirement_names(self, api_client, member, settings):
        # ACC-01 #6 quotes this sentence at the story's own fifteen-minute window; the window is
        # set here rather than read from the environment so the assertion is about the wording.
        settings.AUTH_LOCKOUT_MINUTES = 15

        response = fail_login(api_client, member, times=settings.AUTH_LOCKOUT_MAX_ATTEMPTS)

        assert response.data["message"] == "Too many failed attempts. Try again in 15 minutes."

    def test_the_message_follows_a_changed_window(self, api_client, member, settings):
        # The sentence states the window, so a deployment that changes it must not keep saying 15.
        settings.AUTH_LOCKOUT_MINUTES = 30

        response = fail_login(api_client, member, times=settings.AUTH_LOCKOUT_MAX_ATTEMPTS)

        assert response.data["message"] == "Too many failed attempts. Try again in 30 minutes."

    def test_the_correct_password_is_refused_while_locked(self, api_client, credentials, member):
        fail_login(api_client, member, times=settings.AUTH_LOCKOUT_MAX_ATTEMPTS)

        response = api_client.post(reverse("api:users:auth:login"), credentials)

        assert response.status_code == status.HTTP_423_LOCKED
        assert response.data["code"] == "ACCOUNT_LOCKED"

    def test_a_locked_account_opens_no_session(self, api_client, credentials, member):
        fail_login(api_client, member, times=settings.AUTH_LOCKOUT_MAX_ATTEMPTS)

        api_client.post(reverse("api:users:auth:login"), credentials)

        assert SESSION_USER_KEY not in api_client.session

    def test_the_lock_lifts_when_the_window_has_passed(self, api_client, credentials, member):
        fail_login(api_client, member, times=settings.AUTH_LOCKOUT_MAX_ATTEMPTS)
        member.refresh_from_db()
        member.locked_until = timezone.now() - timedelta(seconds=1)
        member.save(update_fields=("locked_until",))

        response = api_client.post(reverse("api:users:auth:login"), credentials)

        assert response.status_code == status.HTTP_200_OK

    def test_the_threshold_comes_from_settings(self, api_client, member, settings):
        settings.AUTH_LOCKOUT_MAX_ATTEMPTS = 2

        response = fail_login(api_client, member, times=2)

        assert response.status_code == status.HTTP_423_LOCKED

    def test_a_success_between_failures_resets_the_run(self, api_client, credentials, member):
        # "Consecutive" is the whole of the requirement: four failures either side of a success
        # must not add up to a lock.
        fail_login(api_client, member, times=settings.AUTH_LOCKOUT_MAX_ATTEMPTS - 1)
        api_client.post(reverse("api:users:auth:login"), credentials)

        response = fail_login(api_client, member, times=settings.AUTH_LOCKOUT_MAX_ATTEMPTS - 1)

        assert response.status_code == status.HTTP_401_UNAUTHORIZED


class TestRegisterView:
    """ACC-02 — a new Member account, signed in as soon as it exists."""

    def test_a_valid_body_creates_the_account(self, api_client, registration):
        response = api_client.post(reverse("api:users:auth:register"), registration)

        assert response.status_code == status.HTTP_201_CREATED
        user = User.objects.get(email=registration["email"])
        assert user.full_name == "Maya Lindqvist"
        assert user.is_active

    def test_the_new_account_is_a_member(self, api_client, registration):
        # ACC-02 #6 — the role is the model's default, and this is what stops that default from
        # changing underneath registration unnoticed.
        api_client.post(reverse("api:users:auth:register"), registration)

        user = User.objects.get(email=registration["email"])
        assert user.role == User.ROLES.member
        assert not user.is_staff
        assert not user.is_superuser

    def test_the_password_is_stored_hashed(self, api_client, registration):
        api_client.post(reverse("api:users:auth:register"), registration)

        user = User.objects.get(email=registration["email"])
        assert user.check_password(USER_PASSWORD)
        assert user.password != USER_PASSWORD

    def test_the_new_account_is_signed_in(self, api_client, registration):
        # ACC-02 #6 — the account is created *and* logged in; the frontend only redirects.
        response = api_client.post(reverse("api:users:auth:register"), registration)

        assert settings.SESSION_COOKIE_NAME in response.cookies
        user = User.objects.get(email=registration["email"])
        assert api_client.session[SESSION_USER_KEY] == str(user.pk)

    def test_the_new_account_can_log_in(self, api_client, registration):
        # The registration is only worth anything if the credentials it stored are the ones login
        # accepts — the normalised address included.
        api_client.post(reverse("api:users:auth:register"), registration)

        response = api_client.post(
            reverse("api:users:auth:login"),
            {"email": registration["email"], "password": registration["password"], "rememberMe": False},
        )

        assert response.status_code == status.HTTP_200_OK

    def test_success_returns_no_body(self, api_client, registration):
        response = api_client.post(reverse("api:users:auth:register"), registration)

        assert response.content == b""

    def test_the_session_cookie_dies_with_the_browser(self, api_client, registration):
        # The contract's registration cookie carries no `Max-Age`: ACC-02 has no "remember me".
        # Without an explicit `set_expiry(0)` Django applies `SESSION_COOKIE_AGE` and ships a
        # thirty-day session instead, silently.
        response = api_client.post(reverse("api:users:auth:register"), registration)

        cookie = response.cookies[settings.SESSION_COOKIE_NAME]
        assert cookie["max-age"] == ""
        assert cookie["expires"] == ""
        assert api_client.session.get_expire_at_browser_close()

    def test_the_session_cookie_carries_the_same_flags_as_login(self, api_client, registration):
        response = api_client.post(reverse("api:users:auth:register"), registration)

        cookie = response.cookies[settings.SESSION_COOKIE_NAME]
        assert cookie["httponly"]
        assert cookie["samesite"] == "Lax"

    def test_the_address_is_stored_lowercase(self, api_client, registration):
        # The contract says the frontend already lowercased it; another client has not promised
        # anything, and one row per address is what the unique index means.
        api_client.post(reverse("api:users:auth:register"), {**registration, "email": "Maya@Example.COM"})

        assert User.objects.filter(email="maya@example.com").exists()

    def test_the_full_name_is_trimmed(self, api_client, registration):
        api_client.post(reverse("api:users:auth:register"), {**registration, "fullName": "  Maya Lindqvist  "})

        assert User.objects.get(email=registration["email"]).full_name == "Maya Lindqvist"

    def test_no_csrf_token_is_required(self, registration):
        api_client = APIClient(enforce_csrf_checks=True)

        response = api_client.post(reverse("api:users:auth:register"), registration)

        assert response.status_code == status.HTTP_201_CREATED

    def test_get_is_not_allowed(self, api_client):
        response = api_client.get(reverse("api:users:auth:register"))

        assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED

    def test_the_route_carries_no_trailing_slash(self, api_client, registration):
        assert reverse("api:users:auth:register") == "/api/v1/auth/register"

        response = api_client.post("/api/v1/auth/register/", registration)

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_no_personal_data_reaches_the_log(self, api_client, registration, member, caplog):
        # The password and the address for the same reasons as on the login path; the full name
        # because it is personal data the audit trail has no use for.
        with caplog.at_level(logging.INFO, logger="users"):
            api_client.post(reverse("api:users:auth:register"), registration)
            api_client.post(reverse("api:users:auth:register"), {**registration, "email": member.email})

        assert caplog.text
        assert USER_PASSWORD not in caplog.text
        assert registration["email"] not in caplog.text
        assert registration["fullName"] not in caplog.text


class TestRegisterViewRejections:
    def test_a_taken_email_is_refused(self, api_client, registration, member):
        # ACC-02 #5 — the one place the API says out loud that an account exists.
        response = api_client.post(reverse("api:users:auth:register"), {**registration, "email": member.email})

        assert response.status_code == status.HTTP_409_CONFLICT
        assert response.data["code"] == "EMAIL_TAKEN"

    def test_the_refusal_reports_the_message_the_criterion_names(self, api_client, registration, member):
        response = api_client.post(reverse("api:users:auth:register"), {**registration, "email": member.email})

        assert response.data["message"] == "An account with this email already exists."

    def test_a_taken_email_is_refused_regardless_of_case(self, api_client, registration, member):
        response = api_client.post(
            reverse("api:users:auth:register"),
            {**registration, "email": member.email.upper()},
        )

        assert response.status_code == status.HTTP_409_CONFLICT

    def test_a_taken_email_creates_no_second_account(self, api_client, registration, member):
        api_client.post(reverse("api:users:auth:register"), {**registration, "email": member.email.upper()})

        assert User.objects.count() == 1

    def test_a_taken_email_leaves_the_existing_account_untouched(self, api_client, registration, member):
        full_name_before = member.full_name

        api_client.post(reverse("api:users:auth:register"), {**registration, "email": member.email})

        member.refresh_from_db()
        assert member.full_name == full_name_before
        assert member.check_password(USER_PASSWORD)

    def test_a_taken_email_opens_no_session(self, api_client, registration, member):
        api_client.post(reverse("api:users:auth:register"), {**registration, "email": member.email})

        assert SESSION_USER_KEY not in api_client.session

    def test_an_inactive_account_still_holds_its_address(self, api_client, registration):
        # A deactivated account keeps its address: registering over one would be a way to take it
        # over. Reactivation is the admin's job, not this endpoint's.
        UserFactory(email="dormant@example.com", is_active=False)

        response = api_client.post(reverse("api:users:auth:register"), {**registration, "email": "dormant@example.com"})

        assert response.status_code == status.HTTP_409_CONFLICT
        assert response.data["code"] == "EMAIL_TAKEN"

    def test_a_race_on_the_unique_index_answers_the_same_409(self, api_client, registration, monkeypatch):
        # The existence check is stale the instant it returns; two identical requests can both pass
        # it. Only the pre-flight lookup is made to miss — the row is really there and the INSERT
        # really is refused, so this reaches the broken transaction the `atomic()` block exists to
        # unwind. Raising `IntegrityError` from a patched `create_user` instead would never touch
        # the database, and would pass with that block deleted.
        UserFactory(email=registration["email"])
        real_filter = User.objects.filter
        missed = []

        def miss_the_pre_flight_lookup(*args, **kwargs):
            # Every later lookup — the one the `IntegrityError` handler makes — sees the real table.
            if missed:
                return real_filter(*args, **kwargs)

            missed.append(True)
            return User.objects.none()

        monkeypatch.setattr(User.objects, "filter", miss_the_pre_flight_lookup)

        response = api_client.post(reverse("api:users:auth:register"), registration)

        assert response.status_code == status.HTTP_409_CONFLICT
        assert response.data["code"] == "EMAIL_TAKEN"
        assert User.objects.count() == 1

    def test_an_integrity_error_that_is_not_the_taken_address_is_not_a_409(self, api_client, registration, monkeypatch):
        # Any other constraint this table grows must not be reported as an address the caller does
        # not hold — it has to surface as the failure it is.
        def violate_some_other_constraint(*args, **kwargs):
            raise IntegrityError('null value in column "role" violates not-null constraint')

        monkeypatch.setattr(User.objects, "create_user", violate_some_other_constraint)

        with pytest.raises(IntegrityError):
            api_client.post(reverse("api:users:auth:register"), registration)

    @pytest.mark.parametrize("missing", ["fullName", "email", "password"])
    def test_an_incomplete_body_is_rejected(self, api_client, registration, missing):
        # ACC-02 #2 disables the button until every field is filled; that is the client's, and the
        # API refuses the request anyway.
        payload = {key: value for key, value in registration.items() if key != missing}

        response = api_client.post(reverse("api:users:auth:register"), payload)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data["code"] == "UNKNOWN_ERROR"
        assert missing in response.data["message"]

    @pytest.mark.parametrize("password", ["hedger4", "abcdefghij", "1234567890"])
    def test_a_password_the_criterion_refuses_is_rejected(self, api_client, registration, password):
        # ACC-02 #3. The contract has no code for a rejected password, so it lands as the envelope's
        # fallback with the reasons in `message`.
        response = api_client.post(reverse("api:users:auth:register"), {**registration, "password": password})

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data["code"] == "UNKNOWN_ERROR"
        assert response.data["message"]

    @pytest.mark.parametrize(
        "payload_change",
        [
            {"password": "short"},
            {"email": "not-an-email"},
            {"fullName": "   "},
        ],
    )
    def test_a_rejected_registration_creates_nothing(self, api_client, registration, payload_change):
        api_client.post(reverse("api:users:auth:register"), {**registration, **payload_change})

        assert not User.objects.exists()

    @pytest.mark.parametrize(
        "payload_change",
        [
            {"password": "short"},
            {"email": "not-an-email"},
            {"email": "member@example.com"},
        ],
    )
    def test_error_body_is_the_contract_envelope(self, api_client, registration, member, payload_change):
        response = api_client.post(reverse("api:users:auth:register"), {**registration, **payload_change})

        assert set(response.data) == {"code", "message"}
        assert response.data["code"] in AUTH_ERROR_CODES


class TestForgotPasswordView:
    def test_a_known_address_is_accepted(self, api_client, member):
        response = api_client.post(reverse("api:users:auth:forgot-password"), {"email": member.email})

        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert response.content == b""

    def test_an_unknown_address_answers_identically(self, api_client, member):
        # ACC-01 #5 — a neutral answer, or the endpoint becomes an account oracle.
        known = api_client.post(reverse("api:users:auth:forgot-password"), {"email": member.email})
        unknown = api_client.post(reverse("api:users:auth:forgot-password"), {"email": "nobody@example.com"})

        assert known.status_code == unknown.status_code
        assert known.content == unknown.content

    def test_an_inactive_account_answers_identically(self, api_client):
        UserFactory(email="dormant@example.com", is_active=False)

        response = api_client.post(
            reverse("api:users:auth:forgot-password"),
            {"email": "dormant@example.com"},
        )

        assert response.status_code == status.HTTP_204_NO_CONTENT

    @pytest.mark.parametrize("payload", [{}, {"email": ""}, {"email": "not-an-email"}])
    def test_a_malformed_address_is_rejected(self, api_client, payload):
        response = api_client.post(reverse("api:users:auth:forgot-password"), payload)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data["code"] == "UNKNOWN_ERROR"

    def test_it_does_not_touch_the_login_lockout(self, api_client, member):
        fail_login(api_client, member, times=2)

        api_client.post(reverse("api:users:auth:forgot-password"), {"email": member.email})

        member.refresh_from_db()
        assert member.failed_login_attempts == 2

    def test_no_csrf_token_is_required(self, member):
        api_client = APIClient(enforce_csrf_checks=True)

        response = api_client.post(reverse("api:users:auth:forgot-password"), {"email": member.email})

        assert response.status_code == status.HTTP_204_NO_CONTENT

    def test_the_route_carries_no_trailing_slash(self, api_client, member):
        assert reverse("api:users:auth:forgot-password") == "/api/v1/auth/forgot-password"

        response = api_client.post("/api/v1/auth/forgot-password/", {"email": member.email})

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_the_address_never_reaches_the_log(self, api_client, member, caplog):
        with caplog.at_level(logging.INFO, logger="users"):
            api_client.post(reverse("api:users:auth:forgot-password"), {"email": member.email})

        assert caplog.text
        assert member.email not in caplog.text


class TestCorsPreflight:
    """The frontend is a separate origin sending `credentials: "include"`; without the grant below
    the browser drops the login response before any code sees it."""

    def test_a_listed_origin_is_granted_credentials(self, api_client, settings):
        settings.CORS_ALLOWED_ORIGINS = ["http://localhost:3000"]

        response = api_client.options(
            reverse("api:users:auth:login"),
            headers={"origin": "http://localhost:3000", "access-control-request-method": "POST"},
        )

        assert response.status_code == status.HTTP_200_OK
        assert response["Access-Control-Allow-Origin"] == "http://localhost:3000"
        assert response["Access-Control-Allow-Credentials"] == "true"

    def test_an_unlisted_origin_is_granted_nothing(self, api_client, settings):
        settings.CORS_ALLOWED_ORIGINS = ["http://localhost:3000"]

        response = api_client.options(
            reverse("api:users:auth:login"),
            headers={"origin": "http://elsewhere.example.com", "access-control-request-method": "POST"},
        )

        assert "Access-Control-Allow-Origin" not in response


class TestAuthSchema:
    """The statuses are chosen in the view, so only `@extend_schema` puts them in the document."""

    def test_login_declares_every_status_the_contract_names(self, api_client):
        schema = api_client.get(reverse("common:schema")).data

        operation = schema["paths"][reverse("api:users:auth:login")]["post"]
        assert set(operation["responses"]) == {"200", "400", "401", "423"}

    def test_login_declares_the_session_cookie_it_sets(self, api_client):
        schema = api_client.get(reverse("common:schema")).data

        operation = schema["paths"][reverse("api:users:auth:login")]["post"]
        assert "Set-Cookie" in operation["responses"]["200"]["headers"]

    def test_register_declares_every_status_the_contract_names(self, api_client):
        schema = api_client.get(reverse("common:schema")).data

        operation = schema["paths"][reverse("api:users:auth:register")]["post"]
        assert set(operation["responses"]) == {"201", "400", "409"}

    def test_register_declares_the_session_cookie_it_sets(self, api_client):
        # On 201, not 200: the header is attached to the status the endpoint actually answers with.
        schema = api_client.get(reverse("common:schema")).data

        operation = schema["paths"][reverse("api:users:auth:register")]["post"]
        assert "Set-Cookie" in operation["responses"]["201"]["headers"]

    def test_register_does_not_promise_a_remember_me_it_has_no_field_for(self, api_client):
        schema = api_client.get(reverse("common:schema")).data

        operation = schema["paths"][reverse("api:users:auth:register")]["post"]
        assert "rememberMe" not in operation["responses"]["201"]["headers"]["Set-Cookie"]["description"]

    def test_forgot_password_declares_its_statuses(self, api_client):
        schema = api_client.get(reverse("common:schema")).data

        operation = schema["paths"][reverse("api:users:auth:forgot-password")]["post"]
        assert set(operation["responses"]) == {"204", "400"}

    @pytest.mark.parametrize(
        "url_name,error_statuses",
        [
            ("api:users:auth:login", ["400", "401", "423"]),
            ("api:users:auth:register", ["400", "409"]),
            ("api:users:auth:forgot-password", ["400"]),
        ],
    )
    def test_errors_point_at_the_shared_component(self, api_client, url_name, error_statuses):
        schema = api_client.get(reverse("common:schema")).data

        operation = schema["paths"][reverse(url_name)]["post"]
        for code in error_statuses:
            body = operation["responses"][code]["content"]["application/json"]["schema"]
            assert body["$ref"] == f"#/components/schemas/{ERROR_COMPONENT_NAME}"
