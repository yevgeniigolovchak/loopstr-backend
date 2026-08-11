---
paths:
  - "**/migrations/*.py"
---

# Migrations

- **Never import a model directly.** Use `apps.get_model("app", "Model")` — the migration runs against the
  historical schema, and historical models have no custom managers, methods or signals.
- **Every `RunPython` takes a reverse** — a real one, or an explicit `migrations.RunPython.noop`. Without
  it, this migration *and every one after it* becomes irreversible.
- **Write data migrations to be idempotent.** They may run against a database already partly in the target
  state; guard on existence or use `get_or_create`.
- **A new required column is three operations:** add nullable → backfill → tighten. A single `NOT NULL`
  passes on an empty database and fails on every populated one.
- **Never edit a migration that has run anywhere but your own machine.** Fix forward with a new one.
- **Additive on populated databases** — never rebuild seed data, never renumber identifiers other rows
  reference.
- Answering "was this field renamed?" wrongly is a data-loss bug: autogeneration reads a rename as
  drop + add.

Details: [db-migrations](../skills/db-migrations/SKILL.md)
