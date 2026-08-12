from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from common.schema import DetailSerializer, ErrorSerializer
from users.exceptions import InvalidRequest
from users.serializers import (
    ForgotPasswordSerializer,
    LoginSerializer,
    RegisterSerializer,
    SessionUserSerializer,
)
from users.services import authenticate_member, register_member, request_password_reset


def session_cookie_header(response_status, expiry):
    """The `Set-Cookie` a successful authentication answers with.

    The cookie is what actually authenticates the next request — the account in the response body
    is a convenience, not a credential — so it is declared rather than left for a reader to infer.
    Both endpoints set the same cookie with the same flags — stated once here — and differ in the
    status that carries it (login answers 200, registration 201) and in how long it lives, which is
    what `expiry` says.
    """
    return OpenApiParameter(
        name="Set-Cookie",
        type=str,
        location=OpenApiParameter.HEADER,
        response=[response_status],
        description=f"The session cookie: `HttpOnly`, `Secure`, `SameSite=Lax`. {expiry}",
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
        "Verifies the credentials and establishes the session cookie, then answers with the "
        "signed-in account. What authenticates the next request is the cookie: the body carries no "
        "token, and nothing in it is a credential."
    ),
    request=LoginSerializer,
    # This endpoint establishes the session rather than requiring one.
    auth=[],
    parameters=[
        session_cookie_header(
            status.HTTP_200_OK,
            "It carries `Max-Age` only when `rememberMe` was true; otherwise it expires when the "
            "browser closes.",
        ),
    ],
    responses={
        status.HTTP_200_OK: OpenApiResponse(
            response=SessionUserSerializer,
            description="Signed in. The session cookie is set and the body carries the account.",
        ),
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
        user = authenticate_member(request._request, **serializer.validated_data)

        return Response(SessionUserSerializer({"user": user}).data, status=status.HTTP_200_OK)


@extend_schema(
    tags=["auth"],
    summary="Register",
    description=(
        "Creates a Member account and establishes the session cookie, so the new user is already "
        "signed in (ACC-02 #6), and answers with that account in the same shape login uses. "
        "\"Confirm password\" is not part of the request: the mismatch check is the client's."
    ),
    request=RegisterSerializer,
    auth=[],
    parameters=[
        session_cookie_header(
            status.HTTP_201_CREATED,
            "It never carries `Max-Age`: registration has no \"remember me\", so the session ends "
            "when the browser closes.",
        ),
    ],
    responses={
        status.HTTP_201_CREATED: OpenApiResponse(
            response=SessionUserSerializer,
            description="Account created and signed in. The session cookie is set.",
        ),
        status.HTTP_400_BAD_REQUEST: OpenApiResponse(
            response=ErrorSerializer,
            description=(
                "`UNKNOWN_ERROR` — the request body is missing a field or malformed, or the "
                "password fails `AUTH_PASSWORD_VALIDATORS`. The contract has no code for a rejected "
                "password; the reasons are in `message`."
            ),
        ),
        status.HTTP_409_CONFLICT: OpenApiResponse(
            response=ErrorSerializer,
            description=(
                "`EMAIL_TAKEN` — an account already holds that address. The one `/auth/*` answer "
                "that reveals whether an account exists, so the user can be told to log in instead."
            ),
        ),
    },
)
class RegisterView(APIView):
    """`POST /auth/register` — docs/auth-api.md.

    Declared like `LoginView`, and for the same reasons: no authenticator, so nothing enforces a
    CSRF token the frontend does not send, and `AllowAny` because DRF defaults to `IsAuthenticated`.
    """

    authentication_classes = ()
    permission_classes = (AllowAny,)

    def post(self, request, *args, **kwargs):
        serializer = RegisterSerializer(data=request.data)
        if not serializer.is_valid():
            raise InvalidRequest(describe_errors(serializer.errors))

        # `request._request` for `login()`'s `rotate_token()`, as on the login path.
        user = register_member(request._request, **serializer.validated_data)

        return Response(SessionUserSerializer({"user": user}).data, status=status.HTTP_201_CREATED)


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


@extend_schema(
    tags=["users"],
    summary="The signed-in account",
    description=(
        "Reads the account behind the session cookie, in the same shape login and registration "
        "answer with. It is how a client that reloads the page — or one that was signed in on an "
        "earlier visit — finds out who it is, since the cookie is `HttpOnly` and nothing in the "
        "browser can read it.\n\n"
        "It is not an `/auth/*` endpoint: it establishes no session and answers a failure in the "
        "project's own DRF shape (`{\"detail\": ...}`), not the contract's `{\"code\", \"message\"}` "
        "envelope."
    ),
    responses={
        status.HTTP_200_OK: OpenApiResponse(
            response=SessionUserSerializer,
            description="The account the session cookie belongs to.",
        ),
        status.HTTP_403_FORBIDDEN: OpenApiResponse(
            response=DetailSerializer,
            description=(
                "No usable session cookie. 403 rather than 401 because `SessionAuthentication` "
                "publishes no `WWW-Authenticate` header, and DRF rewrites the status when it "
                "cannot: there is no header to send, so there is nothing for a client to retry "
                "with. Treat it as \"not signed in\"."
            ),
        ),
    },
)
class CurrentUserView(APIView):
    """`GET /users/me` — the account behind the session cookie.

    The first endpoint in this project to keep the defaults rather than opt out of them:
    `SessionAuthentication` and `IsAuthenticated`, which is what everything reachable after login
    gets. CSRF comes with the authenticator and costs this endpoint nothing — Django's middleware
    exempts the safe methods, so a GET needs no token — but a write added here later would need one,
    and the frontend has the CSRF cookie by then: `login()` rotates it on the way in.
    """

    permission_classes = (IsAuthenticated,)

    def get(self, request, *args, **kwargs):
        return Response(SessionUserSerializer({"user": request.user}).data)
