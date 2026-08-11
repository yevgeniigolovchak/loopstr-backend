# loopstr

Backend PoC: Django 5.2 + Django REST Framework on PostgreSQL 17, running in Docker.

The repository carries a custom `User` model, an admin registration, a health-check endpoint and the
session-cookie login from ACC-01. Registration (ACC-02) is the next story and is not implemented yet.

## Stack

| | |
|---|---|
| Language | Python 3.14 |
| Framework | Django 5.2.13, Django REST Framework 3.17.1 |
| Database | PostgreSQL 17.9 |
| Settings | django-environ, one `config/settings.py` driven by environment variables |
| API docs | drf-spectacular — OpenAPI 3, Swagger UI served from the image |
| Tests | pytest, pytest-django, factory_boy |

## Getting started

```bash
cp envs.example/app.env docker/app/.env
cp envs.example/db.env docker/db/.env
# fill in DJANGO_SECRET_KEY and POSTGRES_PASSWORD — both files are gitignored

docker compose -f local.yml build
docker compose -f local.yml up -d
```

The application is served at http://localhost:8000, the admin at http://localhost:8000/admin/.

```bash
curl -i localhost:8000/health-check/          # 200 {"status": "ok"}
docker compose -f local.yml run --rm app python manage.py createsuperuser
```

## Endpoints

| Path | What it is | Authentication |
|---|---|---|
| `/admin/` | Django admin | staff session |
| `/docs/` | Swagger UI, rendered from the schema below | none |
| `/schema/` | the raw OpenAPI 3 document | none |
| `/health-check/` | liveness probe | none |
| `POST /api/v1/auth/login` | signs a Member in and sets the session cookie | none |
| `POST /api/v1/auth/forgot-password` | password-reset entry point | none |

The `/auth/*` endpoints follow [docs/auth-api.md](docs/auth-api.md), the contract the frontend already
ships against, rather than this project's usual DRF conventions: their errors are
`{"code", "message"}` and their statuses (401, 423, 204) are chosen in the view. They also declare no
authenticator, which is what lets the frontend post to them without a CSRF token — everything reachable
after login keeps `SessionAuthentication`, and therefore keeps CSRF.

Five consecutive failed logins lock an account for fifteen minutes; both numbers are environment
variables, and both must be 1 or greater — the process refuses to start otherwise. "Remember me" is the
difference between a 30-day cookie and one that dies with the browser.

Email addresses are stored lowercase — normalised on every save — so one address is one account whatever
case it is typed in.

`/docs/` and `/schema/` are registered only while `DJANGO_API_DOCS_ENABLED` is on — it defaults to on,
because the frontend team reads these pages in this PoC, and a deployment that turns it off gets a 404
rather than a page to protect. The Swagger UI assets ship inside the image, so the page needs no
internet access. Both sit outside `/api/v1/`, so the documentation is not versioned along with the API
it describes.

`APPEND_SLASH = False`: every path above has to be requested exactly as written, trailing slash included.

The frontend origins in `DJANGO_CORS_ALLOWED_ORIGINS` must share a registrable domain with the API's own
host: the session cookie is `SameSite=Lax`, which a browser withholds cross-site, so a mismatch produces
a login that answers 200 and leaves every later request anonymous — with no error on either side.

## Tests

```bash
docker compose -f local.yml run --rm app pytest
docker compose -f local.yml run --rm app pytest --create-db      # after a migration
docker compose -f local.yml run --rm app pytest --cov --cov-report term-missing
```

There is no formatter or linter wired up — this is a PoC, and style is kept by hand.

## Layout

```text
config/                 settings, root URLconf, WSGI entry point
loopstr/
├── apps/
│   ├── common/         shared primitives — health check, OpenAPI schema pieces
│   └── users/          custom User model, manager, roles, admin
├── conftest.py         shared pytest fixtures (api_client, user)
├── static/
└── templates/
docker/                 Dockerfile and the per-service env files (gitignored)
envs.example/           committed placeholders for those env files
requirements/           base, local, testing, coverage
local.yml               the only compose file for local development
```

Apps are imported by bare module name (`from users.models import User`) — `config/settings.py` puts
`loopstr/apps` on `sys.path`. The API mounts under `/api/v1/` in the `api` namespace, each app with its own
sub-namespace, so a reverse reads `api:users:auth:login`.

Conventions for working in this repository live in [CLAUDE.md](CLAUDE.md), `.claude/rules/` and
`.claude/skills/`.
