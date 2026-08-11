---
paths:
  - "**/apps/users/**"
  - "config/urls.py"
---

# Auth contract

`/auth/*` is owned by [docs/auth-api.md](../../docs/auth-api.md) — the frontend already ships code against
it, so where that file and our conventions disagree, **the file wins**. It wins *only there*: every other
endpoint keeps the DRF shapes described in [api-contract](api-contract.md). Read the document before
changing anything under `users/`; the decisions below are what it costs us, not a summary of it.

**Errors are `{"code": ..., "message": ...}`, not DRF's `{"field": ["msg"]}`.** Only `code` is consumed;
`message` is for logs. Build it in the auth views' own exception class — never by swapping
`EXCEPTION_HANDLER` globally, which would silently reshape every other endpoint's errors.

**Statuses are chosen, not raised.** 401, 409, 423/429 and 204 cannot come from
`serializers.ValidationError` — that is always 400. Validate with a serializer, then return the status the
contract names.

**camelCase stops at the serializer boundary.** `fullName` / `rememberMe` map to `full_name` /
`remember_me` with an explicit `source=` on each field. No project-wide camelCase renderer: it would
rewrite every future endpoint's payload to satisfy two views.

**Sessions, not tokens.** `django.contrib.auth.login()` sets the `HttpOnly`, `SameSite=Lax` cookie; nothing
auth-related goes in the response body. `SESSION_COOKIE_SECURE` is env-driven — hardcoding `True` breaks
local HTTP, hardcoding `False` ships a cookie readable off the wire. `rememberMe` is
`request.session.set_expiry(30 days | 0)`, not a field we store.

**Login and register carry no CSRF token** — the frontend sends none. They declare
`authentication_classes = ()`, so DRF's `SessionAuthentication.enforce_csrf` never runs on them, and the
rest of the API keeps CSRF enforcement untouched. Anything reachable *after* login keeps
`SessionAuthentication` and therefore keeps CSRF.

**A taken email is revealed on registration and hidden everywhere else.** 409 `EMAIL_TAKEN` is a deliberate
enumeration trade-off from ACC-02; login and forgot-password stay generic (`INVALID_CREDENTIALS`, always
204). Do not "fix" the inconsistency — it is the requirement.

**Lockout is server state, not a throttle.** Five consecutive failures lock the account for 15 minutes; a
DRF throttle counts requests per client and cannot express "this account". With no Redis in this project,
the counter lives in the database. Rate limits (per account, per IP) are a separate, additional layer.

| Trap | What actually happens |
|---|---|
| `raise AuthenticationFailed` for bad credentials | DRF rewrites 401 → **403** when the view has no authenticator. Return the 401 response explicitly. |
| Route registered as `auth/login/` | `APPEND_SLASH = False`, so the contract's `/auth/login` **404s**. Register auth paths without the trailing slash. |
| Password validators left at Django's defaults | The contract promises "≥8 chars, a letter and a number"; our validators also reject common and user-similar passwords, with no contract code to express that. Decide the mapping before implementing. |

**Every `/auth/*` response is declared with `@extend_schema`.** drf-spectacular reads serializers, and
the statuses this contract names are chosen in the view rather than raised by one — no serializer implies
401, 409, 423/429 or 204, so an endpoint left to the generator publishes a 200 the frontend never sees.
Each endpoint therefore lists every status from its table, pointing the error ones at the shared `Error`
component (`common.schema`) instead of restating the envelope per view.

The frontend's `NEXT_PUBLIC_API_BASE_URL` must include `/api/v1` — the reverse stays
`api:users:auth:login`. Credentialed CORS (`Access-Control-Allow-Credentials`) is a dependency this story
adds; the project has none today.
