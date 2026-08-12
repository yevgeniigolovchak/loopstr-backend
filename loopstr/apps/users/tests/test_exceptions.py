import pytest
from rest_framework import status
from rest_framework.exceptions import AuthenticationFailed, NotAuthenticated

from common.schema import AUTH_ERROR_CODES
from users.exceptions import AccountLocked, AuthError, EmailTaken, InvalidCredentials, InvalidRequest

AUTH_ERRORS = (AuthError, InvalidRequest, InvalidCredentials, EmailTaken, AccountLocked)


class TestAuthError:
    @pytest.mark.parametrize("error_class", AUTH_ERRORS)
    def test_uses_a_code_the_contract_declares(self, error_class):
        # A code outside the list renders as UNKNOWN_ERROR on the client, which would make a
        # deliberate 401 indistinguishable from a bug.
        assert error_class.error_code in AUTH_ERROR_CODES

    @pytest.mark.parametrize("error_class", AUTH_ERRORS)
    def test_detail_is_the_contract_envelope(self, error_class):
        detail = error_class("something for the logs").detail

        assert set(detail) == {"code", "message"}
        assert detail["code"] == error_class.error_code
        assert detail["message"] == "something for the logs"

    @pytest.mark.parametrize("error_class", AUTH_ERRORS)
    def test_message_is_optional(self, error_class):
        assert error_class().detail["message"] == ""

    @pytest.mark.parametrize("error_class", AUTH_ERRORS)
    def test_is_not_an_authentication_exception(self, error_class):
        # `APIView.handle_exception` rewrites 401 into 403 for these two whenever the view has no
        # authenticator, which is exactly how the auth views are declared.
        assert not issubclass(error_class, (AuthenticationFailed, NotAuthenticated))

    @pytest.mark.parametrize(
        "error_class,expected_status",
        [
            (AuthError, status.HTTP_400_BAD_REQUEST),
            (InvalidRequest, status.HTTP_400_BAD_REQUEST),
            (InvalidCredentials, status.HTTP_401_UNAUTHORIZED),
            (EmailTaken, status.HTTP_409_CONFLICT),
            (AccountLocked, status.HTTP_423_LOCKED),
        ],
    )
    def test_carries_the_status_the_contract_names(self, error_class, expected_status):
        assert error_class().status_code == expected_status


class TestAccountLocked:
    def test_retry_after_becomes_the_wait_the_handler_reads(self):
        assert AccountLocked(retry_after=900).wait == 900

    def test_wait_is_absent_without_a_retry_after(self):
        assert getattr(AccountLocked(), "wait", None) is None
