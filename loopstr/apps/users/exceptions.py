"""The `{"code", "message"}` error envelope the `/auth/*` endpoints answer with.

docs/auth-api.md is the contract the frontend already ships against, and it replaces DRF's
`{"field": ["msg"]}` shape for these endpoints only. Keeping the envelope inside an exception
class is what keeps it scoped: DRF's stock handler renders a dict `detail` verbatim, so nothing
global changes and every other endpoint keeps the shapes described in
`.claude/rules/api-contract.md`.
"""

from rest_framework import status
from rest_framework.exceptions import APIException


class AuthError(APIException):
    """Base for every `/auth/*` failure; renders `{"code": ..., "message": ...}`.

    Never subclass `AuthenticationFailed` or `NotAuthenticated` for these. `APIView.handle_exception`
    rewrites their 401 into a 403 whenever the view has no authenticator, and the auth views declare
    `authentication_classes = ()` on purpose — the contract's 401 would silently become a 403.
    """

    status_code = status.HTTP_400_BAD_REQUEST
    error_code = "UNKNOWN_ERROR"

    def __init__(self, message=""):
        super().__init__(detail={"code": self.error_code, "message": message})


class InvalidRequest(AuthError):
    """The request body is missing a field or malformed.

    The contract enumerates no 400, and the frontend recognises no code for one, so this reports
    the envelope's fallback code; `message` carries the detail for whoever reads the logs.
    """


class InvalidCredentials(AuthError):
    """Unknown email, wrong password, or an inactive account — one answer for all three.

    ACC-01 #4: the response must not reveal whether an account exists.
    """

    status_code = status.HTTP_401_UNAUTHORIZED
    error_code = "INVALID_CREDENTIALS"


class EmailTaken(AuthError):
    """An account already holds the submitted address (ACC-02 #5).

    The one `/auth/*` answer that reveals whether an account exists, and deliberately so: the user
    is told to log in instead. Login and forgot-password stay generic — the inconsistency is the
    requirement, not an oversight to reconcile.
    """

    status_code = status.HTTP_409_CONFLICT
    error_code = "EMAIL_TAKEN"


class AccountLocked(AuthError):
    """The account is locked after too many consecutive failures (ACC-01 #6).

    423 rather than 429: this is state on the account, not a per-client rate limit. The contract
    accepts either, and the frontend maps both to the same message.
    """

    status_code = status.HTTP_423_LOCKED
    error_code = "ACCOUNT_LOCKED"

    def __init__(self, message="", retry_after=None):
        super().__init__(message)
        if retry_after is not None:
            # DRF's exception handler turns `wait` into a `Retry-After` header.
            self.wait = retry_after
