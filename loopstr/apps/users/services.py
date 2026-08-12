"""Orchestration behind the `/auth/*` views: credentials, the lockout policy and the session."""

import logging

from django.conf import settings
from django.contrib.auth import authenticate, login
from django.db import IntegrityError, transaction

from users.exceptions import AccountLocked, EmailTaken, InvalidCredentials
from users.models import User

logger = logging.getLogger(__name__)

# One string for every way a login can fail on credentials. `message` travels in the response body,
# so two different texts would tell a caller whether the email exists — which is exactly what the
# shared `INVALID_CREDENTIALS` code exists to prevent (ACC-01 #4). The distinction that is useful
# to us lives in the log lines instead. Quoted from ACC-01 #4 exactly, down to the missing full
# stop — the two other criteria that name a message end in one and are quoted with it.
INVALID_CREDENTIALS_MESSAGE = "Email or password is incorrect"

# ACC-01 #6 names this text too. The frontend renders its own copy from `code` and never shows
# `message`, so this is what a log line says — but the wording is the requirement's, and the wait
# is interpolated rather than spelled out so the sentence cannot drift from the configured window.
ACCOUNT_LOCKED_MESSAGE = "Too many failed attempts. Try again in {minutes} minutes."

# ACC-02 #5 names this text. Unlike the login messages above, saying it out loud is the point: the
# user is being told to go and log in instead.
EMAIL_TAKEN_MESSAGE = "An account with this email already exists."


def authenticate_member(request, email, password, remember_me):
    """Verify credentials, apply the lockout policy and open a session. Returns the signed-in user.

    `request` is the underlying `HttpRequest`, not DRF's wrapper — `login()` calls `rotate_token()`,
    which flags the object it is handed, and `CsrfViewMiddleware` only ever reads the original one.

    Raises `InvalidCredentials` (ACC-01 #4) or `AccountLocked` (ACC-01 #6).
    """
    user = User.objects.filter(email=User.objects.normalize_email(email)).first()
    if user is None or not user.is_active:
        # Hash regardless, so an unknown email does not answer measurably sooner than a known one
        # and turn the generic error into an enumeration oracle. `ModelBackend` does the same.
        User().set_password(password)
        logger.info("Login rejected: no usable account for the submitted email.")
        raise InvalidCredentials(INVALID_CREDENTIALS_MESSAGE)

    # Before the password is checked: a locked account is refused whether or not the password is
    # right, which is what "try again in 15 minutes" means.
    if user.is_locked_out:
        logger.info("Login rejected: user %s is locked out until %s.", user.pk, user.locked_until)
        raise _account_locked(user)

    # `user.email` from the row, not the submitted string: `ModelBackend` resolves the natural key
    # exactly, and the payload may differ in case from what is stored. Passing it through would
    # fail to authenticate a correct password — and charge the account an attempt for it.
    authenticated_user = authenticate(request, username=user.email, password=password)
    if authenticated_user is None:
        _count_failed_login(user)
        # The attempt that trips the lock reports the lock, not another wrong password: ACC-01 #6
        # shows "try again in 15 minutes" after the fifth failure, not before the sixth.
        if user.is_locked_out:
            raise _account_locked(user)

        raise InvalidCredentials(INVALID_CREDENTIALS_MESSAGE)

    authenticated_user.reset_login_lockout()
    login(request, authenticated_user)
    # After `login()`, which cycles the session key. `0` is Django's "expire when the browser
    # closes", which is the unchecked "remember me" (ACC-01 #7).
    request.session.set_expiry(settings.SESSION_COOKIE_AGE if remember_me else 0)
    logger.info("Login succeeded for user %s (remember_me=%s).", authenticated_user.pk, remember_me)

    return authenticated_user


def register_member(request, full_name, email, password):
    """Create a Member account and sign it in (ACC-02 #6). Returns the new user.

    `request` is the underlying `HttpRequest` for the same reason login needs it: `login()` calls
    `rotate_token()`, which flags the object it is handed, and `CsrfViewMiddleware` only ever reads
    the original one.

    Raises `EmailTaken` (ACC-02 #5).
    """
    normalized_email = User.objects.normalize_email(email)

    # The address is looked up exactly, against the normalised form — the same query the login path
    # uses. Every stored address is already lowercase, so this is what the column's `unique=True`
    # means, and `iexact` would only cost the index.
    taken_by = User.objects.filter(email=normalized_email).values_list("pk", flat=True).first()
    if taken_by is not None:
        logger.info("Registration rejected: the address already belongs to user %s.", taken_by)
        raise EmailTaken(EMAIL_TAKEN_MESSAGE)

    try:
        with transaction.atomic():
            # `create_user` rather than `User(...)`: it is what hashes the password. The role is left
            # to the model's default, which is what ACC-02 #6 means by "the role Member by default".
            user = User.objects.create_user(email=normalized_email, password=password, full_name=full_name)
    except IntegrityError:
        # The check above is a moment out of date the instant it returns. Two identical requests can
        # both pass it; the unique index refuses the second insert, and it gets the same answer the
        # first-past-the-post one would have. `except` sits outside `atomic()` — catching inside a
        # block that has already broken the transaction is how this turns into a later, stranger
        # failure, and it is also what makes the query below safe to issue.
        #
        # Only that collision is a 409. Every other way this INSERT can violate a constraint — a
        # column added NOT NULL, a CHECK, any second unique index this table grows — would otherwise
        # be answered as a taken address the caller does not hold and logged as a race that never
        # happened, with the real fault visible nowhere.
        if not User.objects.filter(email=normalized_email).exists():
            raise

        logger.info("Registration rejected: the address was taken between the check and the insert.")
        raise EmailTaken(EMAIL_TAKEN_MESSAGE)

    # Nothing called `authenticate()`, so the user carries no `backend` for `login()` to read. With
    # exactly one configured Django would pick it silently — and the day a second one is added,
    # registration starts raising `ValueError` with no other change to this file.
    login(request, user, backend=settings.AUTHENTICATION_BACKENDS[0])
    # ACC-02 has no "remember me": the contract's registration cookie carries no `Max-Age`. Django
    # would otherwise apply `SESSION_COOKIE_AGE` and ship a thirty-day session.
    request.session.set_expiry(0)
    logger.info("Registration succeeded for user %s.", user.pk)

    return user


def request_password_reset(email):
    """Entry point for "Forgot password?" (ACC-01 #5). Answers the same way for any address.

    The rest of the reset flow is out of PoC scope, so nothing is sent yet: there is no
    reset-confirm endpoint for a link to land on, and no mail backend configured to send it. This
    is the one seam where that plugs in, and the caller's response must not change when it does.
    """
    user = User.objects.filter(email=User.objects.normalize_email(email), is_active=True).first()
    if user is None:
        logger.info("Password reset requested for an address with no active account.")
        return

    logger.info("Password reset requested for user %s.", user.pk)


def _account_locked(user):
    """The ACC-01 #6 refusal, carrying how long the caller has to wait.

    The message names the full window, which is what the requirement's sentence says; `Retry-After`
    carries what is actually left on this particular lock.
    """
    return AccountLocked(
        ACCOUNT_LOCKED_MESSAGE.format(minutes=settings.AUTH_LOCKOUT_MINUTES),
        retry_after=user.lockout_seconds_remaining,
    )


def _count_failed_login(user):
    """Record the failure under a row lock, so two concurrent attempts cannot share one increment."""
    with transaction.atomic():
        locked_row = User.objects.select_for_update().get(pk=user.pk)
        locked_row.register_failed_login()

    user.refresh_from_db(fields=("failed_login_attempts", "locked_until"))
    if user.is_locked_out:
        logger.warning("User %s locked out until %s.", user.pk, user.locked_until)
    else:
        logger.info("Login failed for user %s (%s consecutive).", user.pk, user.failed_login_attempts)
