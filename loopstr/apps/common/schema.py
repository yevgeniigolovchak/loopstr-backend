"""OpenAPI pieces the generator cannot derive from a view.

drf-spectacular builds the document from the views it can see, and what it cannot read off them
comes from docs/auth-api.md and is appended here, so an endpoint references one definition instead
of inventing its own. Two kinds of thing land in that gap. The failure bodies are one: both the
auth envelope and DRF's own `{"detail": ...}` are built from an exception rather than through a
serializer, so nothing in a view declares either. The session cookie is the other, and only partly
— `GET /users/me` keeps `SessionAuthentication`, so the generator's own `SessionScheme` registers
`cookieAuth` by itself; what it cannot know is what that cookie is and which endpoints set it.
"""

from django.conf import settings

from drf_spectacular.utils import extend_schema_serializer
from rest_framework import serializers

# docs/auth-api.md → "Error codes". NETWORK_ERROR is in that list but is frontend-only — the client
# raises it when fetch fails — so it is deliberately absent from what the API declares it returns.
AUTH_ERROR_CODES = (
    "INVALID_CREDENTIALS",
    "ACCOUNT_LOCKED",
    "EMAIL_TAKEN",
    "UNKNOWN_ERROR",
)

COOKIE_SECURITY_SCHEME_NAME = "cookieAuth"
ERROR_COMPONENT_NAME = "Error"
DETAIL_COMPONENT_NAME = "Detail"


@extend_schema_serializer(component_name=ERROR_COMPONENT_NAME)
class ErrorSerializer(serializers.Serializer):
    """The handle a view uses to point `@extend_schema` at the shared error component.

    Nothing serialises through it — the auth views build their body from an exception. It exists so
    an error response renders as `$ref: '#/components/schemas/Error'` instead of a copy of the
    envelope inlined per view. `add_contract_components()` runs afterwards and replaces the
    generated definition with the authoritative one, so the enum of codes stays in one place.
    """

    code = serializers.CharField()
    message = serializers.CharField(required=False)


@extend_schema_serializer(component_name=DETAIL_COMPONENT_NAME)
class DetailSerializer(serializers.Serializer):
    """The handle a view uses to declare DRF's own failure body, `{"detail": ...}`.

    Everything outside `/auth/*` fails in this shape, and DRF renders it from an exception, so the
    generator reads nothing from the view and publishes a response with no body at all. It exists
    for the same reason `ErrorSerializer` does — one component the failures point at — and is the
    other half of the split the auth contract draws: the envelope above belongs to `/auth/*`, this
    one to every endpoint that reads a session rather than opening it.
    """

    detail = serializers.CharField()


def add_contract_components(result, generator, request, public):
    """Add the session cookie's description and the error envelope to the generated document.

    Registered as a drf-spectacular postprocessing hook; the signature is the package's.
    """
    components = result.setdefault("components", {})

    # `GET /users/me` authenticates with the cookie, so drf-spectacular's own `SessionScheme` emits
    # this entry — type, and the name read from SESSION_COOKIE_NAME — before the hook runs. What is
    # added here is the description only: overwriting the rest would publish a hardcoded copy the
    # day the generator's version stops matching. The literal below is the fallback for a document
    # generated with no endpoint that authenticates at all; OpenAPI 3 spells a cookie as an apiKey
    # read from `in: cookie`.
    cookie_scheme = components.setdefault("securitySchemes", {}).setdefault(
        COOKIE_SECURITY_SCHEME_NAME,
        {"type": "apiKey", "in": "cookie", "name": settings.SESSION_COOKIE_NAME},
    )
    cookie_scheme["description"] = (
        "Session cookie established by the `/auth/*` endpoints. It is `HttpOnly` and "
        "`SameSite=Lax`: the browser attaches it on its own and no client code can read it, so "
        "there is no token to send in a header."
    )

    components.setdefault("schemas", {})[ERROR_COMPONENT_NAME] = {
        "type": "object",
        "title": ERROR_COMPONENT_NAME,
        "description": (
            "The body of every non-2xx `/auth/*` response. The frontend maps `code` to its own copy "
            "and never renders `message`."
        ),
        "properties": {
            "code": {
                "type": "string",
                "enum": list(AUTH_ERROR_CODES),
                "description": "Anything outside this list is treated as `UNKNOWN_ERROR` by the client.",
            },
            "message": {
                "type": "string",
                "description": "Human-readable, optional, for logs and debugging only.",
            },
        },
        "required": ["code"],
    }

    return result
