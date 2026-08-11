---
name: db-migrations
description: Covers schema and data migrations — the add-nullable-backfill-tighten pattern for required columns, idempotent RunPython with apps.get_model, mandatory reverses, additive changes on populated databases, multi-release renames and lock-aware indexing. Use when generating, writing, reviewing or debugging a migration.
paths:
  - "**/migrations/*.py"
---

# Database Migrations

A migration is the only code that runs against a database you cannot inspect first. It executes on a
developer's throwaway database, on a staging copy, and on production with real rows — and it gets exactly
one attempt at each.

## Quick Reference

| If you're about to... | Watch out for... | § |
|---|---|---|
| Add a required column | A single `NOT NULL` migration fails on every existing row | 2 |
| Write a data migration | `apps.get_model()`, never a direct model import | 3 |
| Write `RunPython` | It may run against a database already partly in the target state | 3 |
| Skip the reverse function | An irreversible migration blocks every rollback after it | 4 |
| Add data to a populated database | Rebuild commands and fixtures are for fresh databases only | 5 |
| Rename or drop a column | One migration means broken pods during the rollout | 6 |
| Edit a migration already merged | It has run elsewhere — its state and the file no longer agree | 7 |
| Rebase onto a new migration | Two branches both created `0011_` — you need a merge migration | 8 |
| Index a large table | The default `AddIndex` locks writes for the duration | 9 |

---

## 1. Generating

```bash
docker-compose -f local.yml exec app python manage.py makemigrations <app_name>
docker-compose -f local.yml exec app python manage.py makemigrations --check --dry-run
```

The second form is the CI-safe check: it fails when models and migrations have drifted, without writing a
file. Run it before opening the MR.

- **Name the migration for what it does** when the generated name is opaque:
  `0012_add_display_id_to_project`, not `0012_auto_20260730_1214`.
- **Commit the migration with the model change**, in the same commit. A model change without its migration
  is a broken branch for everyone who pulls it.
- **One concern per migration.** Two unrelated changes in one file cannot be reverted independently.
- **Review the generated file before committing.** Autogeneration guesses — especially about renames, which
  it usually reads as a drop plus an add.

---

## 2. Adding a Required Column

❌ **Anti-pattern:**
```python
migrations.AddField(
    model_name="project",
    name="display_id",
    field=models.CharField(max_length=20, unique=True),   # NOT NULL, no default
)
```
**Why?** Every existing row needs a value at the moment the column appears. On an empty database this
passes; on any populated one it fails outright, or silently writes one shared default into a unique column.

✅ **Recommended — three operations, in order:**
```python
def backfill_display_id(apps, schema_editor):
    Project = apps.get_model("projects", "Project")
    by_year_count = {}
    for project in Project.objects.order_by("created", "id").iterator():
        year = project.created.year
        seq = by_year_count.get(year, 0) + 1
        by_year_count[year] = seq
        project.display_id = f"{year}-{seq:03d}"
        project.save(update_fields=["display_id"])


class Migration(migrations.Migration):
    dependencies = [("projects", "0001_initial")]

    operations = [
        migrations.AddField(                       # 1. nullable
            model_name="project",
            name="display_id",
            field=models.CharField(max_length=20, unique=True, null=True),
        ),
        migrations.RunPython(                      # 2. backfill
            backfill_display_id,
            reverse_code=migrations.RunPython.noop,
        ),
        migrations.AlterField(                     # 3. tighten
            model_name="project",
            name="display_id",
            field=models.CharField(max_length=20, unique=True),
        ),
    ]
```

> ⚠️ Three operations in one file is right for ordinary tables. On a large or write-heavy table, split them
> across **three releases** instead — add nullable, deploy; backfill, deploy; tighten, deploy. A single file
> holds a lock for the whole backfill, and the intermediate states are exactly what lets old and new code
> run side by side during a rollout.

Where a sensible default exists, `default=` plus `null=False` is simpler — but note the default is baked
into existing rows once and does not follow later changes to it.

---

## 3. Data Migrations

### Always `apps.get_model()`

❌ **Anti-pattern:**
```python
from projects.models import Project        # today's model
```
**Why?** The migration runs against the schema *as it was at this point in history*. A direct import gives
you the current model — with fields that may not exist yet, and with managers, signals and `save()` logic
the historical schema cannot support. Six months later that import turns a green migration into a failing
deploy.

✅ **Recommended:**
```python
def forwards(apps, schema_editor):
    Project = apps.get_model("projects", "Project")
```

Historical models have **no custom methods, no signals, no custom managers** — only fields and a plain
manager. Anything the migration needs must be written out inside it.

### Idempotency

Write every data migration as if it may run against a database that is already partly in the target state —
a re-run after a partial failure, or an environment where an operator applied the change by hand.

```python
def add_groups(apps, schema_editor):
    CategoryNode = apps.get_model("projects", "CategoryNode")
    for parent_slug, group_name in NEW_GROUPS:
        if CategoryNode.objects.filter(slug=f"{parent_slug}/{slugify(group_name)}").exists():
            continue                                  # already present — nothing to do
        ...
```

Guard on existence, or use `get_or_create` / `update_or_create` rather than blind `create`.

### Size

`.iterator()` for large reads so the queryset is not loaded whole. For large writes, batch:

```python
Project.objects.bulk_update(batch, ["display_id"], batch_size=1000)
```

A migration that rewrites millions of rows in one statement holds a lock for its entire runtime — chunk it,
or move the backfill into a management command the deploy triggers separately.

---

## 4. Reversibility

Every `RunPython` takes a second argument. There is no valid reason to omit it:

```python
migrations.RunPython(add_layers, remove_layers)              # genuinely reversible
migrations.RunPython(backfill, migrations.RunPython.noop)    # backfill: nothing to undo
```

Without one, the migration is irreversible — and so is **every migration after it**, because you cannot
roll back past it. That turns a bad deploy into a restore-from-backup.

`RunPython.noop` is the honest answer when reversing is meaningless (a backfill into a column that the
reverse of the schema operation drops anyway). It is not a placeholder for "I didn't think about it".

---

## 5. Additive Changes on Populated Databases

Seed data usually arrives two ways: a management command that builds a structure, or fixtures loaded with
`loaddata`. Both assume a fresh database.

To add to a database that already has data and references to it, write an **additive `RunPython`**:

- **Never rebuild.** A rebuild command drops and recreates rows, so every FK pointing at them breaks or
  silently re-targets. Insert what is new and leave the rest untouched.
- **Never renumber identifiers other rows depend on.** If insertion shifts an ordering scheme, shift it
  in place — primary keys must not change, because everything referencing them survives only if they don't.
- **Skip what already exists**, so the migration is safe on databases at different stages.
- **Say in the docstring what it does and does not touch.** A data migration is read by whoever debugs the
  data later, and its blast radius is not visible from the code.

> ⚠️ Raw `loaddata` does not fire the signals a normal save would. Seeding through fixtures on a live
> database can therefore skip backfills or derived structures that a signal would otherwise create — check
> what the app's `post_save` receivers do before assuming a fixture is equivalent.

---

## 6. Renames and Removals

The dangerous part is not the SQL — it is that old and new code run at the same time during a rollout.

**Renaming a column safely:**
1. Add the new column; deploy.
2. Write to both, read from the new one; backfill; deploy.
3. Stop writing the old one; deploy.
4. Drop the old column; deploy.

`migrations.RenameField` is fine for a column no released code reads yet — inside one feature branch, before
it ships. Never on a column another running version is still querying.

**Removing a column:** stop referencing it in code and deploy that first. A column dropped while the
previous release still selects it takes production down until the rollout finishes.

> ⚠️ Autogeneration reads a rename as *drop + add*. Accepting that silently deletes the data. When
> `makemigrations` asks whether a field was renamed, answering wrong is a data-loss bug, not a style issue.

---

## 7. Never Edit an Applied Migration

Once a migration has run anywhere but your own machine, it is history. Its effects are recorded in
`django_migrations`; changing the file does not change what happened, it only makes the file lie.

Fix forward with a new migration. The only exception is a migration created in your own unmerged branch and
never applied elsewhere — there, delete it, fix the model, regenerate.

Resetting local state when a branch's migrations conflict with your database:
```bash
docker-compose -f local.yml exec app python manage.py migrate <app> <previous_number>
```

---

## 8. Conflicts Between Branches

Two branches both branching from `0010_` produce two `0011_` files. Django detects this and refuses to
migrate.

```bash
docker-compose -f local.yml exec app python manage.py makemigrations --merge
```

The merge migration simply declares both as dependencies. Review what the two actually did before
accepting: parallel changes to the *same* table may need real reconciliation, not just a dependency node.

Rebasing your branch onto the updated target branch first is usually cleaner — then renumber your migration
and adjust its `dependencies` to point at the new head.

---

## 9. Performance and Locking

| Operation | Cost on a large table |
|---|---|
| `AddField` nullable, no default | cheap — metadata only |
| `AddField` with a default | rewrites the table on older engines |
| `AlterField` to `NOT NULL` | full scan to validate |
| `AddIndex` | blocks writes until the index is built |
| `RunPython` looping with `save()` | one round trip per row |

For a hot table, build indexes without blocking writes (`AddIndexConcurrently` on PostgreSQL, in a
migration marked `atomic = False`), and keep backfills out of the migration itself.

Declare `atomic = False` only when an operation genuinely requires it — you lose the automatic rollback, so
the migration must then be safe to re-run from a partial state (§3).

---

## 10. Testing

```bash
docker-compose -f local.yml run --rm app pytest --create-db
```

Schema changes require `--create-db`; with a reused test database you are testing against the old schema
and will not find out until CI.

- **`makemigrations --check --dry-run` belongs in CI** — it catches a model change whose migration was
  never generated.
- **Test data migrations that carry real logic**: build the "before" rows with factories, call the forward
  function with `apps` from `django.apps`, assert the result. Migrations with branching, parsing or
  ordering logic are code, and untested code in a migration fails in the one place you cannot debug it.
- **Run the migration twice in the test** when idempotency matters — that is the property you are claiming.

---

## 11. Checklist

- [ ] Migration generated, reviewed, and committed with the model change.
- [ ] New required column follows add-nullable → backfill → tighten.
- [ ] Data migrations use `apps.get_model()`; no direct model imports, no reliance on signals or managers.
- [ ] `RunPython` is idempotent and has a reverse (or an explicit `noop`).
- [ ] Additive on populated databases — nothing rebuilt, no identifiers renumbered.
- [ ] Renames and drops sequenced across releases, not squeezed into one deploy.
- [ ] No edits to a migration that has run outside your machine.
- [ ] Branch conflicts resolved by rebase or an explicit merge migration.
- [ ] Large-table operations checked for locking; backfills batched.
- [ ] Tests run with `--create-db`; `--check --dry-run` passes in CI.

## Navigation
- [Django App Layout](../django-app-layout/SKILL.md)
- [DRF Endpoints](../drf-endpoints/SKILL.md)
- [Django Testing](../django-testing/SKILL.md)
- [Git Workflow & MR](../git-workflow-mr/SKILL.md)
