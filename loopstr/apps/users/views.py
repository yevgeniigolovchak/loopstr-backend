from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from common.schema import ErrorSerializer
from users.exceptions import InvalidRequest
from users.serializers import ForgotPasswordSerializer, LoginSerializer
from users.services import authenticate_member, request_password_reset

# The cookie is the entire result of a login, and nothing in the response body implies it, so it is
# declared as a response header rather than left for a reader to infer.
SESSION_COOKIE_HEADER = OpenApiParameter(
    name="Set-Cookie",
    type=str,
    location=OpenApiParameter.HEADER,
    response=[status.HTTP_200_OK],
    description=(
        "The session cookie: `HttpOnly`, `Secure`, `SameSite=Lax`. It carries `Max-Age` only when "
        "`rememberMe` was true; otherwise it expires when the browser closes."
    ),
)


def describe_errors(errors):
    """Flatten DRF's field errors onto one line for the envelope's `message`.

    `message` is for logs and debugging — the frontend renders its own copy from `code` — so this
    keeps the detail readable without promising a shape anyone should parse.
    """
    return "; ".join(f"{field}: {' '.join(str(error) for error in errors[field])}" for field in errors)


@extend_schema(
    tags=["auth"],
    summary="Log in",
    description=(
        "Verifies the credentials and establishes the session cookie. The body of a success is "
        "empty: the session is the result, and no token is ever returned."
    ),
    request=LoginSerializer,
    # This endpoint establishes the session rather than requiring one.
    auth=[],
    parameters=[SESSION_COOKIE_HEADER],
    responses={
        status.HTTP_200_OK: OpenApiResponse(description="Signed in. The session cookie is set."),
        status.HTTP_400_BAD_REQUEST: OpenApiResponse(
            response=ErrorSerializer,
            description="`UNKNOWN_ERROR` — the request body is missing a field or malformed.",
        ),
        status.HTTP_401_UNAUTHORIZED: OpenApiResponse(
            response=ErrorSerializer,
            description=(
                "`INVALID_CREDENTIALS` — one answer for an unknown email, a wrong password and an "
                "inactive account, so the response never reveals whether an account exists."
            ),
        ),
        status.HTTP_423_LOCKED: OpenApiResponse(
            response=ErrorSerializer,
            description=(
                "`ACCOUNT_LOCKED` — the account is locked after five consecutive failures and "
                "stays locked for fifteen minutes, correct password included."
            ),
        ),
    },
)
class LoginView(APIView):
    """`POST /auth/login` — docs/auth-api.md.

    No authenticator and `AllowAny` are both deliberate: DRF defaults to `IsAuthenticated`, and an
    empty `authentication_classes` is what keeps `SessionAuthentication.enforce_csrf` from running
    on a request the frontend sends without a CSRF token. Everything reachable after login keeps
    both.
    """

    authentication_classes = ()
    permission_classes = (AllowAny,)

    def post(self, request, *args, **kwargs):
        serializer = LoginSerializer(data=request.data)
        if not serializer.is_valid():
            # Not `raise_exception=True`: that produces DRF's `{"field": ["msg"]}`, and every
            # non-2xx answer from `/auth/*` has to carry the contract's envelope instead.
            raise InvalidRequest(describe_errors(serializer.errors))

        # `request._request` — the service hands it to `login()`, whose `rotate_token()` flags the
        # request object it is given, and `CsrfViewMiddleware` only ever reads the original one.
        authenticate_member(request._request, **serializer.validated_data)

        return Response(status=status.HTTP_200_OK)


@extend_schema(
    tags=["auth"],
    summary="Request a password reset",
    description=(
        "The entry point behind \"Forgot password?\" (ACC-01 #5). Answers 204 for any well-formed "
        "address, whether or not an account exists, so the response cannot be used to enumerate "
        "accounts. The rest of the reset flow is out of PoC scope."
    ),
    request=ForgotPasswordSerializer,
    auth=[],
    responses={
        status.HTTP_204_NO_CONTENT: OpenApiResponse(description="Accepted. Neutral by design."),
        status.HTTP_400_BAD_REQUEST: OpenApiResponse(
            response=ErrorSerializer,
            description="`UNKNOWN_ERROR` — the email is missing or malformed.",
        ),
    },
)
class ForgotPasswordView(APIView):
    """`POST /auth/forgot-password` — docs/auth-api.md."""

    authentication_classes = ()
    permission_classes = (AllowAny,)

    def post(self, request, *args, **kwargs):
        serializer = ForgotPasswordSerializer(data=request.data)
        if not serializer.is_valid():
            raise InvalidRequest(describe_errors(serializer.errors))

        request_password_reset(**serializer.validated_data)

        return Response(status=status.HTTP_204_NO_CONTENT)
