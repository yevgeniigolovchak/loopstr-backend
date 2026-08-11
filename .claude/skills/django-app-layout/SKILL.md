---
name: django-app-layout
description: Defines project and app structure — directory layout and ownership, app registration, splitting a module into a package, model body order, Choices, managers and ORM performance defaults. Use when creating a Django app, adding or changing a model or manager, or deciding where new code belongs.
paths:
  - "**/models.py"
  - "**/models/**/*.py"
  - "**/managers.py"
  - "**/apps.py"
  - "**/signals.py"
  - "**/services.py"
---

# Django App Layout

Where things live and in what order they are written. Structure is a decision the reader should never have
to reverse-engineer: two apps in the same repository must be navigable the same way.

## Quick Reference

| If you're about to... | Watch out for... | § |
|---|---|---|
| Register a new app | `AppConfig.name` is the **bare** module name, not the dotted path | 2 |
| Split a growing `models.py` | Package + explicit re-exports, or Django won't see the models | 3 |
| Add a field | Model body order is fixed: fields → managers → `Meta` → `__str__` → `save()` → methods | 4 |
| Define choices | `model_utils.Choices`, never Django `TextChoices` | 5 |
| Add a queryset helper | Managers live in `models.py` **or** `managers.py` — never both | 6 |
| Write a `for` loop over a queryset | That is an N+1 until proven otherwise | 8 |
| Reach for a signal | Signals are for cross-app side effects and cleanup, not business logic | 9 |
| Change a model | Generate the migration; never hand-edit one that is already applied | 10 |

---

## 1. Project Structure

```text
project_root/
├── config/                     # settings.py (django-environ), root urls.py, wsgi.py
├── <project_name>/
│   ├── apps/                   # all first-party apps
│   │   ├── common/             # RBAC primitives, shared exceptions, storages, utils
│   │   ├── users/              # custom User model, roles, service codes
│   │   ├── files/              # uploads, thumbnails, storage backends
│   │   ├── taskapp/            # Celery entry point
│   │   └── <domain_app>/
│   └── conftest.py             # global pytest fixtures
├── docker/                     # Dockerfiles + per-service env files
├── envs.example/               # committed placeholders for the above
├── requirements/               # base.txt, local.txt, production.txt, testing.txt
├── local.yml                   # local development — the only compose file for dev
└── CLAUDE.md
```

Ownership rules:

- **`config/`** — configuration only. `settings.py` is the single source of truth; nothing domain-specific.
- **`common/`** — shared primitives with no domain knowledge: permissions, exceptions, storages, filters,
  pagination, logging. If it imports a domain model, it does not belong here.
- **`taskapp/`** — Celery app definition. Tasks themselves live in each app's `tasks.py` and autodiscover.
- **Domain apps** — one bounded concern each. When an app needs a model from another app, import it; when
  two apps need to import each other's models, the boundary is wrong.

---

## 2. Creating an App

Run inside the container, then move the generated package into the apps directory:

```bash
docker-compose -f local.yml exec app python manage.py startapp <app_name>
```

`apps.py` — the config name is the **bare** module name:

✅ **Correct:**
```python
from django.apps import AppConfig


class ComplaintsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "complaints"
    verbose_name = "Complaints"
```

❌ **Incorrect:**
```python
class ComplaintsConfig(AppConfig):
    name = "myproject.apps.complaints"   # will not resolve — the apps dir is on sys.path
```

Register it in `LOCAL_APPS`, pointing at the config class, not the module:

```python
LOCAL_APPS = (
    "users.apps.UsersAppConfig",
    "complaints.apps.ComplaintsConfig",
)
```

A finished app has: `apps.py`, `models.py`, `serializers.py`, `views.py`, `urls.py`, `admin.py`,
`filters.py` (when it has list endpoints), `tasks.py` (when it has async work), `migrations/`, and
`tests/` with `factories.py`. Create only what the app actually uses — an empty `tasks.py` is noise.

---

## 3. When a Module Becomes a Package

A flat `models.py` / `serializers.py` / `views.py` is the default. Split into a package once the file
covers genuinely separate concerns — not merely once it gets long.

```text
complaints/
├── models.py                       # stays flat while it is one concern
├── serializers/
│   ├── __init__.py
│   ├── base.py
│   ├── clinician.py
│   └── organisation.py
└── views/
    ├── __init__.py
    ├── clinician.py
    └── organisation.py
```

Split by **concern or audience** (per role, per resource), never by layer-inside-layer (`serializers/
create.py`, `serializers/update.py`). Name submodules for what they hold — `organisation.py`, not
`views_organisation.py`, since the package already supplies that context.

> ⚠️ When `models.py` becomes `models/`, re-export every model in `__init__.py`. Django discovers models
> through the app's `models` module; a class that is only defined in `models/complaint.py` and never
> imported into `__init__.py` gets no table and no migration, silently.

---

## 4. Model Body Order

Fixed order, so any model can be skimmed the same way:

1. Field definitions
2. Manager / queryset attributes
3. `class Meta`
4. `__str__` and other magic methods
5. `save()`, `get_absolute_url()`
6. Custom business methods

```python
class Complaint(StatusModel, TimeStampedModel):
    STATUS = Choices(
        ("pending", _("Pending")),
        ("resolved", _("Resolved")),
    )

    subject = models.CharField(max_length=255)
    complaint_type = models.ForeignKey(
        ComplaintType,
        on_delete=models.PROTECT,
        related_name="complaints",
    )
    occurrence_date = models.DateField(db_index=True)

    objects = ComplaintQuerySet.as_manager()

    class Meta:
        verbose_name = _("Complaint")
        verbose_name_plural = _("Complaints")
        ordering = ("-created",)

    def __str__(self):
        return self.subject

    def resolve(self, actor):
        """Move the complaint to resolved and stamp who did it."""
        self.status = self.STATUS.resolved
        self.resolved_by = actor
        self.save(update_fields=("status", "resolved_by", "modified"))
```

Inherit the timestamp and status behaviour rather than re-declaring it: `TimeStampedModel` gives
`created`/`modified`, `StatusModel` wires `STATUS` to a `status` field with `status_changed` tracking.

Field naming is `snake_case`, lowercase, descriptive, no abbreviations. Use `on_delete` deliberately —
`PROTECT` for lookup tables you must not silently lose rows from, `CASCADE` only when the child genuinely
cannot outlive the parent. Add `db_index=True` on non-PK columns that are filtered on frequently.

---

## 5. Choices

Use `model_utils.Choices` exclusively. Do not use Django's `TextChoices`/`IntegerChoices` — mixing the two
means two different access idioms for the same concept across the codebase.

✅ **Recommended:**
```python
from model_utils import Choices

class Invoice(TimeStampedModel):
    STATUS = Choices(
        ("draft", _("Draft")),
        ("sent", _("Sent")),
        ("paid", _("Paid")),
    )

    status = models.CharField(max_length=20, choices=STATUS, default=STATUS.draft)
```

Reference members by attribute — `Invoice.STATUS.paid` — never by the raw string `"paid"`. A typo in an
attribute raises immediately; a typo in a string filters to an empty queryset and looks like missing data.

---

## 6. Managers and QuerySets

Query logic belongs on a `QuerySet`, exposed as the default manager, so it chains and reuses.

✅ **Recommended:**
```python
class ComplaintQuerySet(models.QuerySet):
    def open(self):
        return self.exclude(status=Complaint.STATUS.resolved)

    def for_organisation(self, organisation):
        return self.filter(organisation=organisation)


class Complaint(TimeStampedModel):
    objects = ComplaintQuerySet.as_manager()
```

Then `Complaint.objects.open().for_organisation(org)` reads as the sentence it is.

> ⚠️ Managers and querysets live in `models.py` **or** in a dedicated `managers.py` — pick one per
> repository and stay with it. Split across both, nobody knows where to look for an existing helper and
> the same filter gets written twice.

Never put permission checks inside a manager. `for_organisation(org)` is a scoping helper; deciding *which*
organisation the requester may see is the view's job.

---

## 7. Style Basics

- **Line length** follows the repository's formatter config; no backslash continuations — wrap with
  `()`/`[]`/`{}`.
- **Trailing commas** are mandatory when the closing bracket sits on its own line, and on single-element
  tuples: `("-created",)`.
- **Strings** — f-strings or `.format()`. Never `+` concatenation, never `%`.
- **No mutable default arguments.** Use `None` plus in-function init.
- **Catch specific exceptions.** Never bare `except:` or `except Exception:`. Keep `try` bodies to the
  statement that can actually raise.
- **Comments explain *why*.** No section headers, no commented-out code, no `TODO` left behind at merge —
  resolve it or open a ticket.
- **Docstrings**: one-liners stay on one line; multi-line means summary, blank line, details.
- **Dead code goes.** Unused helpers and one-shot scripts do not get committed "just in case".

---

## 8. ORM Performance

Treat these as defaults, not optimisations to revisit later:

| Situation | Use |
|---|---|
| Forward FK / OneToOne accessed per row | `select_related("fk")` |
| Reverse FK or M2M accessed per row | `prefetch_related("children")` |
| Creating/updating/deleting many rows | `bulk_create` / `bulk_update` / `bulk_delete` |
| You only need a couple of columns | `values()` / `values_list()` |
| Frequently filtered non-PK column | `db_index=True` |
| Aggregation | `annotate()` / `aggregate()` — not a Python loop |

❌ **Anti-pattern:**
```python
for complaint in Complaint.objects.all():
    print(complaint.complaint_type.name)      # one query per row
```

✅ **Recommended:**
```python
for complaint in Complaint.objects.select_related("complaint_type"):
    print(complaint.complaint_type.name)
```

Wrap multi-write operations in `transaction.atomic()`, and defer side effects that must not run on a
rolled-back transaction with `transaction.on_commit(...)` — dispatching a Celery task inside an open
transaction can hand the worker a row that never gets committed.

---

## 9. Signals

Signals are for **cross-cutting side effects that must fire on every delete/save path**, including cascade
deletes and queryset operations that bypass model `delete()`:

- storage cleanup when a file-bearing row disappears
- dependent rows a DB cascade cannot reach because the FK points the other way
- backfilling structure when a feature flag flips on

They are not a place for business logic. A signal is invisible at the call site, hard to test in isolation,
and fires in bulk operations where the author never expected it. If the behaviour belongs to a specific
user action, put it in the model method or the service that performs that action.

Register receivers in the app's `signals.py` and import it from `AppConfig.ready()` — a receiver module
nobody imports never connects.

---

## 10. Migrations

```bash
docker-compose -f local.yml exec app python manage.py makemigrations <app_name>
docker-compose -f local.yml exec app python manage.py makemigrations --check --dry-run   # CI-safe check
```

- **One migration per change set**, committed together with the model change — never separately.
- **Never hand-edit a migration that has been applied anywhere but your own machine.** Add a new one.
- **Never import a model directly in a data migration** — use `apps.get_model("app", "Model")`.
- Schema-changing migrations require `--create-db` on the next test run if the test database is reused.

Anything beyond a plain field addition — a new required column, a backfill, a rename, a change against a
populated database — has its own rules; see [Database Migrations](../db-migrations/SKILL.md).

---

## 11. i18n and Time

Wrap every user-facing string in `gettext_lazy as _` — model `verbose_name`, choice labels, validation
messages. Internal identifiers and log messages stay untranslated.

Store and compute in UTC (`timezone.now()`, never `datetime.now()`); convert to local time only at the
presentation edge.

---

## 12. Checklist

- [ ] App registered in `LOCAL_APPS` via its config class; `AppConfig.name` is the bare module name.
- [ ] Only the modules the app actually uses were created.
- [ ] Model body follows the fixed order; `Meta` has `verbose_name` and a deliberate `ordering`.
- [ ] Choices via `model_utils.Choices`, referenced by attribute rather than raw string.
- [ ] Query helpers on a `QuerySet`, in the one location this repository uses.
- [ ] `on_delete` chosen deliberately; hot lookup columns indexed.
- [ ] No N+1 — relations traversed in a loop are pre-fetched.
- [ ] Multi-write paths wrapped in `transaction.atomic()`; task dispatch via `on_commit`.
- [ ] Signals used only for cross-cutting side effects, and `signals.py` imported from `ready()`.
- [ ] Migration generated, reversible where possible, committed with the model change.
- [ ] User-facing strings wrapped in `gettext_lazy`.

## Navigation
- [DRF Endpoints](../drf-endpoints/SKILL.md)
- [Django Testing](../django-testing/SKILL.md)
- [Celery Tasks](../celery-tasks/SKILL.md)
- [Django Admin](../django-admin/SKILL.md)
- [Git Workflow & MR](../git-workflow-mr/SKILL.md)
