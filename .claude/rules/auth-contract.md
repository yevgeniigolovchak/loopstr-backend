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

**"Confirm password" is the client's, and stays there.** ACC-02 #1 puts the field on the Registration page
and #4 makes the mismatch an inline error — both are UI. The contract's body carries three fields, the
frontend owns the check, and this was confirmed with the frontend developer rather than inferred. The API
declares no `confirmPassword`, so one sent anyway is ignored rather than refused. Adding a server-side
comparison is a contract change plus a coordinated frontend release, not a hardening tweak.

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

**Password validators are exactly the criterion — no more.** ACC-02 #3 states "≥8 chars, a letter and a
number", so `AUTH_PASSWORD_VALIDATORS` is two: `MinimumLengthValidator` with an explicit `min_length: 8`
and `common.validators.LetterAndNumberValidator` for the part Django has no rule for. Strength beyond the
criterion is **scope, and scope comes from the story** — and the contract recognises no code for a rejected
password, so every added rule fires after the client has already said yes and renders as an unexplained
`UNKNOWN_ERROR`. `CommonPasswordValidator` and `UserAttributeSimilarityValidator` are therefore both out:
`password123` is accepted, and so is a password equal to the account's own address. Do not re-add either as
a security fix — it is a question for the story owner. `NumericPasswordValidator` is out for an unrelated
reason: it can never fire once a letter is required.

**Re-adding `UserAttributeSimilarityValidator` is never a one-line change.** It early-returns on
`if not user`, and `RegisterSerializer.validate_password` passes none — configured on its own it would be
listed in settings and silently never run. It would also need an unsaved `User` built from `initial_data`
(the raw payload, not `validated_data`) so a bad password is still reported when the address is malformed.

**The `validate_password` import is aliased** (`as run_password_validators`): the serializer hook has the
same name, and `self.validate_password(value)` is one plausible cleanup away from unbounded recursion.
A failure answers 400 `UNKNOWN_ERROR` with the joined messages in `message`; closing that gap properly
needs a new code (`WEAK_PASSWORD`) in a later revision of `docs/auth-api.md`.

**Registration opens the session without `authenticate()`.** Nothing set `user.backend`, so `login()` is
given one explicitly — `settings.AUTHENTICATION_BACKENDS[0]`. Django would infer it silently while exactly
one backend is configured, and start raising `ValueError` the day a second is added. The registration
cookie is a browser-session cookie: ACC-02 has no "remember me", so `set_expiry(0)` is required or Django
ships a thirty-day session instead. The taken-address check is a moment out of date the instant it returns,
so the `IntegrityError` from the unique index is caught and answered with the same 409 — but only after
re-running the lookup confirms the address really is taken. Any other constraint violation is re-raised:
answering it as `EMAIL_TAKEN` would report an address the caller does not hold and bury the real fault.

**Every `/auth/*` response is declared with `@extend_schema`.** drf-spectacular reads serializers, and
the statuses this contract names are chosen in the view rather than raised by one — no serializer implies
401, 409, 423/429 or 204, so an endpoint left to the generator publishes a 200 the frontend never sees.
Each endpoint therefore lists every status from its table, pointing the error ones at the shared `Error`
component (`common.schema`) instead of restating the envelope per view.

The frontend's `NEXT_PUBLIC_API_BASE_URL` must include `/api/v1` — the reverse stays
`api:users:auth:login`. Credentialed CORS (`Access-Control-Allow-Credentials`) is a dependency this story
adds; the project has none today.
