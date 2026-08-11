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
the counter lives in the database. Rate limits (per account, per IP) are a separate, additional layer that
the contract asks for and **this PoC does not implement** — it is out of the ACC-01 story's scope. Do not
add one without that being asked for.

| Trap | What actually happens |
|---|---|
| `raise AuthenticationFailed` for bad credentials | DRF rewrites 401 → **403** when the view has no authenticator. Raise an `APIException` subclass carrying the status instead — that is what `users/exceptions.py` is. |
| Route registered as `auth/login/` | `APPEND_SLASH = False`, so the contract's `/auth/login` **404s**. Register auth paths without the trailing slash. |
| `login(request, user)` with DRF's request | `rotate_token()` flags the object it is handed, and `CsrfViewMiddleware` only reads the original. The CSRF cookie is never reset. Pass `request._request`. |
| `authenticate(username=<the submitted email>)` | The lookup normalises the address, but `ModelBackend` resolves the natural key **exactly** against whatever you hand it. A differently-cased email fails with the right password and charges the account an attempt. Pass `user.email` from the row. |
| A different `message` per failure reason | `message` ships in the response body. Two texts behind one `INVALID_CREDENTIALS` re-open the enumeration hole the shared code closes. Keep the string identical; put the distinction in the log line. |

**Password validators: decided, lands with ACC-02.** Login never validates a password, so ACC-01 leaves
`AUTH_PASSWORD_VALIDATORS` alone. The contract promises "≥8 chars, a letter and a number" and the client
recognises no code for a rejected password, so any rule stricter than the client's fires only after the
client has already said yes, and renders as an unexplained `UNKNOWN_ERROR`. The mapping: keep
`MinimumLengthValidator` with an explicit `min_length: 8`, add a `LetterAndNumberValidator` in
`common/validators.py` for the part Django has no rule for, drop `NumericPasswordValidator` (it can never
fire once a letter is required) and `UserAttributeSimilarityValidator` (the likeliest source of a mystery
rejection), and keep `CommonPasswordValidator` — a bad message beats a guessable password. A validator
failure answers 400 `UNKNOWN_ERROR` with the joined messages in `message`. Closing that properly needs a
new code (`WEAK_PASSWORD`) in a later revision of `docs/auth-api.md`.

**Every `/auth/*` response is declared with `@extend_schema`.** drf-spectacular reads serializers, and
the statuses this contract names are chosen in the view rather than raised by one — no serializer implies
401, 409, 423/429 or 204, so an endpoint left to the generator publishes a 200 the frontend never sees.
Each endpoint therefore lists every status from its table, pointing the error ones at the shared `Error`
component (`common.schema`) instead of restating the envelope per view.

The frontend's `NEXT_PUBLIC_API_BASE_URL` must include `/api/v1` — the reverse stays
`api:users:auth:login`. Credentialed CORS (`Access-Control-Allow-Credentials`) is a dependency this story
adds; the project has none today.
