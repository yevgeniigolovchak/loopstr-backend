# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Where the conventions live

- **`.claude/skills/`** — stack-wide conventions shared with our other backends: DRF endpoints, app layout,
  testing, Celery, files, admin, migrations, real-time, git/MR workflow, code review. Loaded when the task
  touches matching files.
- **`.claude/rules/`** — short always-on rules. The generic ones mirror the skills; project rules carry this
  repository's domain and are scoped to their app path.
- **`docs/auth-api.md`** — the frontend's published contract for `/auth/*` and for `GET /users/me`, and the
  source of truth for both: where it disagrees with a rule, it wins, because the client ships against it.
  What that costs us is in [auth-contract](.claude/rules/auth-contract.md), which also records how the
  `/users/me` section got there — it is the one part this side wrote, and agreement came before the edit.
- **`docs/PoC Scope Login, Authorization & Homepage.pdf`** — the acceptance criteria the work is measured
  against, and the authority on scope. Read it with `pdftotext -layout "<path>" -`, which needs poppler on
  the host (`brew install poppler`); it is not in the image, so this is one of the few things that does not
  run through Compose. Without it, ask for the page rather than inferring what a criterion says — the file
  uses subset fonts whose `ToUnicode` maps cover only ligatures, so a reader that falls back to the
  embedded text layer gets nothing usable. It carries three stories: ACC-01 Login, ACC-02 Registration and
  HOME-01 Homepage, of which the first two are implemented.
- **This file** — stack, commands, layout, and the cross-cutting facts that belong to no single app.

Don't duplicate a rule or a skill here. Domain detail belongs in the rule for its app.

**Scope comes from the story; the contract supplies shapes.** The acceptance criteria decide what gets built.
`docs/auth-api.md` is authoritative for what a payload and an error body *look like* — fields, codes,
statuses, cookie flags — and not for the infrastructure it also asks for. Its rate-limit lines are
deliberately unimplemented; so is everything past the forgot-password entry point, which answers 204 and
sends nothing, because no reset-confirm endpoint exists in the contract for a link to land on. Building
either is a decision to be asked for, not inferred from the contract.

<!-- The Celery skill and the async-tasks rule ship with the skill set but do not apply here: this project
     has no broker and no worker. Do not introduce Celery without a decision to add one. -->

## Stack

Python 3.14, Django 5.2.13, Django REST Framework 3.17.1, PostgreSQL 17.9. Settings come from environment
variables through `django-environ`; `model_utils` supplies `Choices` and `TimeStampedModel`; tests run on
pytest + pytest-django with factory_boy.

Local development runs in Docker via **`local.yml`** — the only compose file in the repository. Two services:
`db` (with a `pg_isready` healthcheck) and `app`, which waits for `db` to be healthy before starting.

API documentation is **drf-spectacular** (with `drf-spectacular-sidecar` for the Swagger UI assets), not the
drf-yasg our other backends use: drf-yasg emits OpenAPI 2.0, which has no cookie security scheme, and this
project authenticates with a session cookie. Where the [drf-endpoints](.claude/skills/drf-endpoints/SKILL.md)
skill says drf-yasg, it means drf-spectacular here — `@swagger_auto_schema` is `@extend_schema`.

There is **no Celery, Redis, allauth, dj-rest-auth, S3/Azure storage or Centrifugo** here. Authentication is
**session-cookie based** — `django.contrib.auth.login()` behind an `HttpOnly`, `SameSite=Lax` cookie, no
token in the response body — because that is what [docs/auth-api.md](docs/auth-api.md) specifies. Login and
the forgot-password entry point (ACC-01) and registration (ACC-02) have landed, along with `GET /users/me`,
which reads the account behind the session — that one is in no ACC story, it is what the signed-in pages
need, and it was settled with the frontend developer first and written into the contract afterwards. Those
four are the whole of the API. A success on login and registration answers with that same account object —
the cookie stays the only credential. Registration signs the new account in the same way and gets a
browser-session cookie: it has no "remember me", so the expiry is set explicitly rather than left at
`SESSION_COOKIE_AGE`.

Credentialed CORS runs through **django-cors-headers**: the frontend is a separate origin and sends
`credentials: "include"`, so `CORS_ALLOW_CREDENTIALS` is on and `CORS_ALLOWED_ORIGINS` is an explicit list —
that header is incompatible with a wildcard. Those origins must also be **same-site with the API host**, or
the `SameSite=Lax` session cookie never comes back — a login that answers 200 and leaves the next request
anonymous, with no error anywhere. That is a deploy-coordination item, not something the code checks.

## Common commands

```bash
# Bring the stack up / down
docker compose -f local.yml up -d
docker compose -f local.yml down

# Tests — full suite, a single module, one class or one test, by keyword, coverage
docker compose -f local.yml run --rm app pytest
docker compose -f local.yml run --rm app pytest loopstr/apps/users/tests/test_models.py
docker compose -f local.yml run --rm app pytest loopstr/apps/users/tests/test_views.py::TestLoginViewLockout
docker compose -f local.yml run --rm app pytest -k "lockout and not schema"
docker compose -f local.yml run --rm app pytest --cov --cov-report term-missing

# After any migration, the reused test database is stale
docker compose -f local.yml run --rm app pytest --create-db

# Migrations and management commands
docker compose -f local.yml run --rm app python manage.py makemigrations <app>
docker compose -f local.yml run --rm app python manage.py makemigrations --check --dry-run
docker compose -f local.yml run --rm app python manage.py createsuperuser
```

First run needs the env files: `cp envs.example/app.env docker/app/.env` and
`cp envs.example/db.env docker/db/.env`, then fill in the placeholders. Both files are gitignored.

## Architecture

### Import paths

`config/settings.py` appends `loopstr/apps` to `sys.path`, so local apps are imported by **bare module name**:

```python
from users.models import User          # ✅
from loopstr.apps.users.models import User   # ❌ does not resolve
```

The same applies to `AppConfig.name` (`"users"`, not `"loopstr.apps.users"`) and to `LOCAL_APPS` entries
(`"users.apps.UsersAppConfig"`). The append is relative, so management commands and pytest run from the
repository root — which is `/app` inside the container, and what `WORKDIR` guarantees.

### Project layout

- `config/` — settings, root URLconf, WSGI entry point. Nothing domain-specific.
- `loopstr/apps/common/` — shared primitives with no domain knowledge: the health-check endpoint, the docs
  routes, and `schema.py`, which appends what the generator cannot see from a view.
- `loopstr/apps/users/` — the custom `User` model (email as `USERNAME_FIELD`, no username), its manager,
  roles and admin registration, plus the `/auth/*` endpoints and `GET /users/me`: `serializers.py`,
  `services.py` (credentials, lockout, session), `views.py`, `urls.py` and `exceptions.py`, which carries
  the contract's error envelope — and applies to `/auth/*` only.
- `loopstr/conftest.py` — the shared `api_client` and `user` fixtures; app-specific fixtures go in that app's
  `tests/conftest.py`.

### URL namespacing

The API mounts under `/api/v1/` in the `api` namespace, and every app is included there with its own
sub-namespace, so a reverse reads `api:<app>:<sub>:<name>`:

```python
path("api/v1/", include((api_urls, "api"), namespace="api"))   # config/urls.py
reverse("api:users:auth:login")                                # the shape to expect
```

`api_urls` holds one `path("", include(("users.urls", "users")))` line today; adding an app is another one.
A route that belongs to no sub-namespace reverses one level shorter — `api:users:current-user` for
`/api/v1/users/me`, which sits outside `/auth/` because it reads a session rather than opening one. Every
route in this app is registered **without a trailing slash** — `APPEND_SLASH = False`, so `auth/login/`
would 404 the contract's `/auth/login` instead of redirecting to it.

Infrastructure endpoints sit **outside** that prefix: the health check is `common:health-check` at
`/health-check/`, unauthenticated, so a probe does not have to know the API version. The documentation
(`common:schema`, `common:docs`) is mounted the same way and behind `DJANGO_API_DOCS_ENABLED`.

## Non-obvious rules

- **`APPEND_SLASH = False`** — a request without the trailing slash 404s instead of redirecting. URLs must be
  hit exactly as declared.
- **Email is stored lowercase.** `UserManager.normalize_email` lowercases the whole address — Django's own
  version does the domain only — and `User.save()` applies it to every write, whatever wrote it. That is
  what makes the column's `unique=True` mean "one address, one account". Look up a user by exact match on
  the normalised address, not `iexact`: the stored value is already normalised, and `iexact` cannot use the
  index.
- **DRF defaults to `IsAuthenticated`.** Anything public says so explicitly, as `HealthCheckView` does with
  `permission_classes = (AllowAny,)` and empty `authentication_classes`.
- **Nothing reads a `.env` file.** Compose injects the variables, so a new variable needs the container
  restarted — and adding `read_env()` would create a second source of truth that disagrees with deploy.
- **`User` has no `username` field**, and `REQUIRED_FIELDS` is empty: `createsuperuser` asks for the email and
  the password only. Code that assumes `AbstractUser` (`first_name`, `last_name`, `username`) will not work.
- **`created`/`modified` come from `TimeStampedModel`**, not from a `date_joined` field. Ordering is `-created`.
- **No formatter, no linter, no pre-commit** — deliberately, for a PoC. Where a rule delegates style to a
  hook (`imports.md` hands import ordering to isort), do it by hand instead: the four import groups are
  stdlib → Django → third-party → local, and lines wrap at 120 characters.

## Test conventions

Only what differs from the [django-testing](.claude/skills/django-testing/SKILL.md) skill:

- `USER_PASSWORD` in `users/tests/factories.py` is the password every factory-built user gets; use it rather
  than setting one per test.
- `UserFactory` uses `django_get_or_create = ("email",)` — passing an existing email returns that user instead
  of raising, so uniqueness tests build the second user through `User.objects.create_user`.
- `pytest.ini` sets `--maxfail=2`; pass `--maxfail=0` when you want the full failure list.
