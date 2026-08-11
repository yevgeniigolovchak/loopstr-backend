---
paths:
  - "**/models.py"
  - "**/models/**/*.py"
  - "**/managers.py"
---

# Models

- **`model_utils.Choices`, never Django `TextChoices`.** Reference members by attribute
  (`Invoice.STATUS.paid`), never by raw string — a typo in an attribute raises, a typo in a string filters
  to nothing and looks like missing data.
- **Fixed body order:** fields → manager attributes → `Meta` → `__str__` → `save()` → custom methods.
- **Inherit timestamps and status** from the shared base models rather than re-declaring them.
- **Choose `on_delete` deliberately** — `PROTECT` for lookup tables, `CASCADE` only when the child cannot
  outlive the parent.
- **Query helpers live on a `QuerySet`** exposed as the default manager, in `models.py` **or**
  `managers.py` — one location per repository, never both.
- **Never put permission checks in a manager.** Scoping helpers are fine; deciding who may see what is the
  view's job.
- Wrap user-facing strings in `gettext_lazy`; store and compute in UTC.
- When `models.py` becomes `models/`, re-export every model in `__init__.py` — a model that is never
  imported there gets no table and no migration, silently.

Details: [django-app-layout](../skills/django-app-layout/SKILL.md)
