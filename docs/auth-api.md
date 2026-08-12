# loopstr Auth API — Backend Contract

This is the contract the **frontend already calls** through its typed `AuthGateway`
(`src/features/auth/gateway/http-auth-gateway.ts`). The backend team implements these
endpoints; the frontend needs no changes when they come online.

- **Base URL**: configured on the frontend via `NEXT_PUBLIC_API_BASE_URL`
  (e.g. `https://api.loopstr.app`). All paths below are relative to it.
- **Transport**: JSON over HTTPS. Request/response bodies are `application/json`.
- **Scope**: this covers PoC **ACC-01 Login** (and its Forgot-password entry point) and
  **ACC-02 Registration**, plus the `GET /users/me` read the signed-in pages need. That last one
  belongs to no ACC story: it was agreed between the frontend and the backend and written down here
  afterwards, which is the order any addition to this document follows. There is **no two-factor /
  OTP step** — valid credentials sign the Member in directly, and a successful registration logs the
  new Member in the same way. Any further password-reset steps are separate, later contracts.

---

## Conventions

### Sessions

- On successful login the backend establishes the session by setting an **`HttpOnly`, `Secure`,
  `SameSite=Lax`** session cookie. Do not return session tokens in the response body.
- The frontend sends `credentials: "include"` on every request; it never reads, parses, or mints
  a token.
- **Remember me**: when `rememberMe` is `true`, the session cookie should be persistent
  (~30 days); otherwise it is a browser-session cookie (ACC-01 #7).
- CORS must allow the frontend origin with `Access-Control-Allow-Credentials: true`.

### The account object

Three responses carry the signed-in account — login, registration and `GET /users/me` — and all
three use the same body:

```json
{ "user": { "id": 42, "email": "user@example.com", "fullName": "Maya Lindqvist", "role": "member" } }
```

| Field      | Type    | Notes                                                                        |
| ---------- | ------- | ---------------------------------------------------------------------------- |
| `id`       | integer | The account's identifier.                                                    |
| `email`    | string  | Returned lowercased, whatever case it was submitted in.                      |
| `fullName` | string  | May be `""` for an account created outside registration (a superuser, say).  |
| `role`     | string  | `"member"` is the only value the PoC issues.                                 |

Nothing else about the account is published — no password hash, no staff flags, no lockout state —
and **none of it is a credential**: the session cookie is what authenticates the next request. The
`user` wrapper is what lets a later revision add a second key without changing the shape a client
already parses.

### Error envelope

Every non-2xx response uses this body:

```json
{ "code": "INVALID_CREDENTIALS", "message": "Human-readable, optional. For logs, not shown verbatim." }
```

- `code` is required and MUST be one of the [error codes](#error-codes).
- The frontend maps `code` → user-facing copy itself; `message` is for logs/debugging only.
- If `code` is missing or unrecognized, the frontend falls back to an HTTP-status mapping.

### Status → code fallback

| HTTP status | Fallback code         |
| ----------: | --------------------- |
|         401 | `INVALID_CREDENTIALS` |
|         409 | `EMAIL_TAKEN`         |
|     423/429 | `ACCOUNT_LOCKED`      |
|       other | `UNKNOWN_ERROR`       |

### Security

- Never log passwords or full auth payloads.
- Login uses one generic `INVALID_CREDENTIALS` for both unknown-email and wrong-password, so the
  response never reveals whether an email exists (ACC-01 #4).
- **Lockout** (ACC-01 #6): after 5 consecutive failed attempts, lock the account for 15 minutes and
  respond with `ACCOUNT_LOCKED` (423 or 429). The 5-attempt / 15-minute policy is server-enforced;
  the frontend only renders the resulting message.
- Forgot-password responses must be neutral (see below) to avoid account enumeration.
- Rate-limit login per account and per IP.

---

## Endpoints

### POST `/auth/login`

Authenticate credentials. On success, establish the session and return `2xx`.

**Request**

```json
{ "email": "user@example.com", "password": "…", "rememberMe": true }
```

| Field        | Type    | Req | Notes                                                              |
| ------------ | ------- | :-: | ----------------------------------------------------------------- |
| `email`      | string  |  ✔  | Already trimmed and lowercased by the frontend.                   |
| `password`   | string  |  ✔  | Sent as-is over TLS. Never logged.                                |
| `rememberMe` | boolean |  ✔  | If true, the session cookie is persistent (~30 days).            |

**Response `200`** — sets the session cookie and returns the
[account object](#the-account-object). The frontend may treat any 2xx as success and ignore the
body; when it does read it, this saves the extra `GET /users/me` right after a login.

**Errors**

| Code                  |   HTTP  | When                                          |
| --------------------- | :-----: | --------------------------------------------- |
| `INVALID_CREDENTIALS` |   401   | Unknown email or wrong password (generic).    |
| `ACCOUNT_LOCKED`      | 423/429 | Locked after 5 failed attempts (15 min).      |

---

### POST `/auth/register`

Create a Member account (ACC-02). On success, establish the session (auto-login) and return `2xx`.

**Request**

```json
{ "fullName": "Maya Lindqvist", "email": "user@example.com", "password": "…" }
```

| Field      | Type   | Req | Notes                                                            |
| ---------- | ------ | :-: | --------------------------------------------------------------- |
| `fullName` | string |  ✔  | Already trimmed by the frontend.                                |
| `email`    | string |  ✔  | Already trimmed and lowercased by the frontend.                 |
| `password` | string |  ✔  | ≥8 chars with a letter and a number (validated client-side too). Sent as-is over TLS; never logged. |

**Response `201`** — sets the session cookie (a browser-session cookie; ACC-02 has no
"remember me") and returns the [account object](#the-account-object), the same shape login answers
with. The new Member has the **Member** role.

**Errors**

| Code          | HTTP | When                                                         |
| ------------- | :--: | ------------------------------------------------------------ |
| `EMAIL_TAKEN` | 409  | An account already exists for that email.                    |

> Unlike login and forgot-password, registration **deliberately reveals** whether an email is
> already registered (ACC-02): the user is told to log in instead. Rate-limit per IP.

---

### POST `/auth/forgot-password`

Request a password-reset link (ACC-01 #5 entry point). The rest of the reset flow is out of PoC
scope.

**Request**

```json
{ "email": "user@example.com" }
```

**Response `204`** — always succeed for a well-formed email, whether or not the account exists
(the frontend shows a neutral "if an account exists, we've sent a link" confirmation). Send the
reset email only when the account exists. Rate-limit per email and per IP.

---

### GET `/users/me`

Read the account the session cookie belongs to. The cookie is `HttpOnly`, so a page that reloads can
tell it *has* a session but nothing about whose it is; this is where the name and the role behind it
come from. No request body, no query parameters — the cookie is the whole of the request.

**Response `200`** — the [account object](#the-account-object).

**Errors**

| HTTP | When                                                                      |
| :--: | ------------------------------------------------------------------------- |
| 403  | No session cookie, an expired one, or an account that has been deactivated. |

> **This one is not an `/auth/*` endpoint**, and two things follow. Its failure body is the API's
> ordinary `{ "detail": … }`, **not** the `{ "code", "message" }` envelope — there is no `code` to
> map, and the frontend's status fallback reads 403 as `UNKNOWN_ERROR`. And it answers **403 rather
> than 401**: a session cookie is not a credential a client can be asked to re-send, so there is no
> `WWW-Authenticate` challenge to publish and the framework will not claim otherwise. Read it as
> "not signed in" and send the user to Login.

---

## Error codes

The frontend recognizes exactly these `code` values
(`src/features/auth/auth.types.ts` → `AUTH_ERROR_CODES`):

```
INVALID_CREDENTIALS
ACCOUNT_LOCKED
EMAIL_TAKEN
NETWORK_ERROR   (frontend-only: fetch failed / offline — never returned by the API)
UNKNOWN_ERROR   (fallback for unrecognized errors)
```

Any other `code` is treated as `UNKNOWN_ERROR`.

---

## Example: login

```
POST /auth/login   { "email": "user@example.com", "password": "…", "rememberMe": true }
200  Set-Cookie: session=…; HttpOnly; Secure; SameSite=Lax; Max-Age=2592000
     { "user": { "id": 42, "email": "user@example.com", "fullName": "Maya Lindqvist", "role": "member" } }
```

```
POST /auth/login   { "email": "user@example.com", "password": "wrong", "rememberMe": false }
401                { "code": "INVALID_CREDENTIALS" }
```

## Example: register

```
POST /auth/register   { "fullName": "Maya Lindqvist", "email": "user@example.com", "password": "…" }
201  Set-Cookie: session=…; HttpOnly; Secure; SameSite=Lax     (session cookie, no Max-Age)
     { "user": { "id": 42, "email": "user@example.com", "fullName": "Maya Lindqvist", "role": "member" } }
```

```
POST /auth/register   { "fullName": "Maya Lindqvist", "email": "taken@example.com", "password": "…" }
409                   { "code": "EMAIL_TAKEN" }
```

## Example: the signed-in account

```
GET /users/me      Cookie: session=…
200                { "user": { "id": 42, "email": "user@example.com", "fullName": "Maya Lindqvist", "role": "member" } }
```

```
GET /users/me      (no cookie)
403                { "detail": "Authentication credentials were not provided." }
```
