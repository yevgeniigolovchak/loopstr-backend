# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Where the conventions live

- **`.claude/skills/`** — stack-wide conventions shared with our other backends: DRF endpoints, app layout,
  testing, Celery, files, admin, migrations, real-time, git/MR workflow, code review. Loaded when the task
  touches matching files.
- **`.claude/rules/`** — short always-on rules. The generic ones mirror the skills; project rules carry this
  repository's domain and are scoped to their app path.
- **`docs/auth-api.md`** — the frontend's published contract for `/auth/*`, and the source of truth for it:
  where it disagrees with a rule, it wins, because the client already ships against it. What that costs us
  is in [auth-contract](.claude/rules/auth-contract.md).
- **This file** — stack, commands, layout, and the cross-cutting facts that belong to no single app.

Don't duplicate a rule or a skill here. Domain detail belongs in the rule for its app.

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

There is **no Celery, Redis, allauth, dj-rest-auth, S3/Azure storage or Centrifugo** here. This is a
PoC skeleton; authentication is the next story and does not exist yet. It is **session-cookie based** —
`django.contrib.auth.login()` behind an `HttpOnly`, `SameSite=Lax` cookie, no token in the response body —
because that is what [docs/auth-api.md](docs/auth-api.md) specifies.

## Common commands

```bash
# Bring the stack up / down
docker compose -f local.yml up -d
docker compose -f local.yml down

# Tests — full suite, a single module, coverage
docker compose -f local.yml run --rm app pytest
docker compose -f local.yml run --rm app pytest loopstr/apps/users/tests/test_models.py
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
  roles and admin registration.
- `loopstr/conftest.py` — the shared `api_client` and `user` fixtures; app-specific fixtures go in that app's
  `tests/conftest.py`.

### URL namespacing

The API mounts under `/api/v1/` in the `api` namespace, and every app is included there with its own
sub-namespace, so a reverse reads `api:<app>:<sub>:<name>`:

```python
path("api/v1/", include((api_urls, "api"), namespace="api"))   # config/urls.py
reverse("api:users:auth:login")                                # the shape to expect
```

`api_urls` is empty until the auth story lands; adding an app is one `path("", include(("users.urls", "users")))`
line inside it.

Infrastructure endpoints sit **outside** that prefix: the health check is `common:health-check` at
`/health-check/`, unauthenticated, so a probe does not have to know the API version. The documentation
(`common:schema`, `common:docs`) is mounted the same way and behind `DJANGO_API_DOCS_ENABLED`.

## Non-obvious rules

- **`APPEND_SLASH = False`** — a request without the trailing slash 404s instead of redirecting. URLs must be
  hit exactly as declared.
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
