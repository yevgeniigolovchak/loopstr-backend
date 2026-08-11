---
name: settings-secrets
description: Covers Django settings and environment variables with django-environ — where values come from in a containerised setup, the central Env schema and its casting, which variables may carry a default and which must fail closed, the prefixed naming convention, and keeping the committed placeholder files in step. Use when adding or changing a setting, introducing an environment variable, editing the placeholder env files, or debugging a "works locally, breaks in staging" configuration problem.
paths:
  - "**/settings.py"
  - "**/envs.example/**"
---

# Settings & Secrets

One `settings.py`, driven entirely by environment variables through `django-environ`. There is no
`base.py` / `local.py` / `production.py` split — the file is identical in every environment, and only the
values around it change. A setting that differs between environments is a variable, never a branch on
`DEBUG` or a hostname check.

## Quick Reference

| If you're about to... | Watch out for... | § |
|---|---|---|
| Look for where `.env` is loaded | Nothing loads it — the container gets the variables from Compose | 1 |
| Read a new variable | Cast it; a string `"False"` is truthy | 2 |
| Decide whether to add a default | The default goes in the `Env(...)` schema, not at the call site | 3 |
| Add a credential | A default turns a missing credential into a silent runtime failure | 4 |
| Name the variable | Prefixed by consumer — the variable name is not the setting name | 5 |
| Add any variable | The matching placeholder file needs it in the same commit | 6 |
| Commit | Real env files are gitignored — check `git status` before a broad `git add` | 7 |
| Merge | A new required variable is a deploy-coordination item, not just a diff | 9 |

---

## 1. Where Values Come From

Nothing in `settings.py` reads a file. The Compose service declares which env files to inject, and the
process environment is what `django-environ` reads:

```yaml
app:
  env_file:
    - docker/app/.env
    - docker/db/.env
```

Two consequences that catch people out:

- **A variable added to an env file needs the container restarted**, not just a code reload — the process
  environment is fixed at start.
- **`read_env()` is not used.** Adding a call to it, or a `.env` at the project root, creates a second
  source of truth that disagrees with Compose in exactly the environments you cannot debug easily.

Env files are split by service, so a variable belongs in the file for the service that consumes it —
database credentials in the database env file, application settings in the application one. Services that
need both list both.

---

## 2. Reading and Casting

Everything in the process environment is a string. The `env.*` methods cast it:

```python
DEBUG = env.bool("DJANGO_DEBUG")
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS")
SERVICE_CODE_EXPIRATION_HOURS = env.int("DJANGO_SERVICE_CODE_EXPIRATION_HOURS")
SECRET_KEY = env("DJANGO_SECRET_KEY")            # calling env directly is env.str
```

❌ **Anti-pattern:**
```python
DEBUG = os.environ.get("DJANGO_DEBUG", "False") == "True"
```
**Why?** It reimplements `env.bool()` and gets it wrong the first time someone writes `yes`, `false` or `0`
in an env file — all of which are normal there, and none of which equal `"True"`. The app silently stays in
debug mode.

✅ **Recommended:**
```python
DEBUG = env.bool("DJANGO_DEBUG")
```
`env.bool()` accepts `true/false`, `yes/no` and `1/0` case-insensitively. Use it for **every** on/off value,
not only `DEBUG`.

> ⚠️ **A truthy string is still a string.** `env.str("FEATURE_ON", default="False")` returns `"False"`, and
> `if "False":` is `True`. Reading an on/off value as a string is a bug that behaves correctly in every test
> where the flag is meant to be on.

---

## 3. The Central `Env(...)` Schema

Defaults are declared **once**, in the `environ.Env(...)` constructor at the top of `settings.py`, as
`NAME=(type, default)` pairs — not at each call site:

```python
env = environ.Env(
    DJANGO_DEBUG=(bool, False),
    DJANGO_ALLOWED_HOSTS=(list, []),
    POSTGRES_HOST=(str, "db"),
    POSTGRES_PORT=(int, 5432),
    DJANGO_SERVICE_CODE_EXPIRATION_HOURS=(int, 24),
)
```

The constructor doubles as the inventory of every variable the project understands. Adding a variable means
adding it here, in the same commit as the code that reads it.

> ⚠️ **A call site with no default may still be defaulted.** `env.bool("DJANGO_DEBUG")` looks required, but
> the constructor supplies `False`. To know whether a missing variable stops the application, you have to
> read the constructor — never conclude "no default at the call site, therefore required."

That cuts both ways: a variable **absent** from the constructor and read without a default raises
`ImproperlyConfigured` at import time, which is the correct behaviour for something the app genuinely
cannot run without.

---

## 4. Which Variables May Carry a Default

| Category | Treatment |
|---|---|
| Behaviour and tuning — timeouts, page sizes, expiry windows, feature flags | Default in the schema. Fine, and keeps env files short |
| Infrastructure coordinates — host, port, container names | Default in the schema to the Compose value |
| **Credentials, keys, tokens, connection strings** | See below — a default here is the dangerous case |

A credential defaulted to an empty string does not fail closed. It fails **later**, somewhere else, as a
permission or connectivity error:

```python
DJANGO_AZURE_ACCOUNT_KEY=(str, ""),        # unset → empty key → storage silently broken
```

Django itself refuses to start with an empty `SECRET_KEY`, so that one is covered by accident. Nothing
covers the rest.

Most credentials here are guarded by a feature flag — the storage keys matter only when the storage backend
is switched on. That is where they belong:

✅ **Validate the credential inside the branch that needs it:**
```python
USE_AZURE = env.bool("DJANGO_USE_AZURE")

if USE_AZURE:
    AZURE_ACCOUNT_KEY = env("DJANGO_AZURE_ACCOUNT_KEY")
    if not AZURE_ACCOUNT_KEY:
        raise ImproperlyConfigured("DJANGO_USE_AZURE is on but DJANGO_AZURE_ACCOUNT_KEY is empty.")
```

**Why?** The variable is genuinely optional when the flag is off, so removing its default would break local
development. Checking it where the flag turns on gives the loud, immediate failure that a missing credential
deserves — with a message naming both variables, which is what the person reading the logs actually needs.

---

## 5. Naming

Variables are prefixed by the consumer, and **the variable name is not the setting name**:

| Prefix | Consumer | Example |
|---|---|---|
| `DJANGO_` | Django settings, and project settings read in `settings.py` | `DJANGO_ALLOWED_HOSTS` → `ALLOWED_HOSTS` |
| `DRF_` | Django REST Framework configuration | `DRF_ENABLE_BROWSABLE_API_RENDERER` |
| `POSTGRES_` | database service — read by the database container too | `POSTGRES_PASSWORD` |

Keep the prefix even when the setting name would be unambiguous: the env file is a flat namespace shared
with the database image and anything else Compose starts, and the prefix is what keeps it navigable.

**A third-party package that defines its own variable name wins.** Use the name the package documents rather
than inventing an aliased one — the failure mode of an alias is the application reading one name while the
deployment tooling sets another, with nothing on either side reporting a mismatch.

---

## 6. Placeholder Files

The committed placeholder directory mirrors the real env files one-for-one — same filenames, same keys,
fake values:

```bash
# envs.example/app.env
DJANGO_SECRET_KEY=SET_DJANGO_SECRET_KEY_HERE
DJANGO_DEBUG=yes
DJANGO_USE_AZURE=no
DJANGO_AZURE_ACCOUNT_KEY=CHANGE ME!
```

- **Add the key to the placeholder file in the same commit** that adds it to `settings.py`. A variable that
  exists in code but not in the placeholder is the next teammate's `ImproperlyConfigured` after they pull
  and copy the examples.
- **Never a real value**, including ones that look internal — a value true in any real environment does not
  belong in a committed file.
- **Group under the same headed sections as the real file**, and put the key in the file for the service
  that consumes it.
- One line per variable. If it needs explaining, the explanation goes in `settings.py` or `CLAUDE.md`, not
  as a paragraph in the placeholder.

---

## 7. What Never Enters Source Control

- **Real env files are gitignored** — confirm this is actually true in a project you did not set up. A file
  of credentials committed once during setup is the most common way real secrets reach history.
- Run `git status` before a broad `git add` and check no env file is listed as untracked-and-about-to-be-added.
- This covers **every** environment's file, not just local: a production env file pulled onto a laptop for
  debugging must not be committed from there either.
- **Fixtures, migrations and tests must not carry real secrets.** A credential hardcoded into a fixture or a
  `RunPython` is committed like any other line.

---

## 8. If a Secret Leaks

Deleting the value from the current file does not undo the leak — it is in every clone and every fork.

1. **Rotate the credential first.** Issue a new value at the provider and update every environment's file
   before anything else.
2. **Then** clean history if it is required. That is cleanup, not the fix.
3. **Never log a secret**, including at DEBUG level, and including where it could surface in a traceback's
   local variables. Log that a value was read, never the value.
4. **Never put one in a response**, including an error page shown only to staff — it reaches screenshots,
   support tickets and monitoring tools.

---

## 9. Rolling Out a New Variable

Adding it to `settings.py` and the placeholder file does not put it in any real environment.

- **A new required variable is a deploy-coordination item.** Say so in the merge request: which environments
  need the value set, and before which step.
- **Prefer landing it optional first** — a safe default in the schema, tightened once every environment has
  the value. Same add-then-tighten shape as a required database column.
- **Confirm it arrived.** Failing at container start is correct behaviour, but it is still an outage until
  someone reads the log.

---

## 10. Checklist

- [ ] Variable declared in the `Env(...)` schema and read with the matching `env.*` cast.
- [ ] On/off values use `env.bool()` — no string compared to `"True"`.
- [ ] Default chosen deliberately: fine for behaviour and coordinates, checked explicitly for credentials.
- [ ] A flag-guarded credential is validated inside the branch that switches the flag on.
- [ ] Name carries the consumer prefix; third-party packages keep their documented name.
- [ ] Placeholder file updated in the same commit, in the right service's file, with a fake value.
- [ ] No real env file staged; no secret in a log line, response, fixture or migration.
- [ ] A leaked credential is rotated before any history rewriting.
- [ ] A new required variable is called out in the merge request as a deploy step.

## Navigation
- [Agent Configuration](../agent-configuration/SKILL.md) — deny rules that stop the agent reading env files
- [Database Migrations](../db-migrations/SKILL.md) — the same add-then-tighten shape for required columns
- [Django App Layout](../django-app-layout/SKILL.md)
