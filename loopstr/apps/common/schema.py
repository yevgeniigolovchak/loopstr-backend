"""OpenAPI pieces the generator cannot derive from a view.

drf-spectacular builds the document from the views it can see. Two things this API publishes are
invisible to it today: the session cookie, because no endpoint authenticates with one yet, and the
error envelope, which the auth views build by hand rather than through a serializer. Both come from
docs/auth-api.md, and both are appended here so the first `/auth/*` endpoint to land can reference
them instead of inventing its own.
"""

from django.conf import settings

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


def add_contract_components(result, generator, request, public):
    """Add the session cookie scheme and the error envelope to the generated document.

    Registered as a drf-spectacular postprocessing hook; the signature is the package's.
    """
    components = result.setdefault("components", {})

    # OpenAPI 3 spells a cookie as an apiKey read from `in: cookie`. The name is read at generation
    # time so it follows SESSION_COOKIE_NAME instead of restating it.
    components.setdefault("securitySchemes", {})[COOKIE_SECURITY_SCHEME_NAME] = {
        "type": "apiKey",
        "in": "cookie",
        "name": settings.SESSION_COOKIE_NAME,
        "description": (
            "Session cookie established by the `/auth/*` endpoints. It is `HttpOnly` and "
            "`SameSite=Lax`: the browser attaches it on its own and no client code can read it, so "
            "there is no token to send in a header."
        ),
    }

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
