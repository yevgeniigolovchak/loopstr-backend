---
name: django-admin
description: Covers Django admin conventions — list pages without N+1, related-field widgets for large tables, read-only system-owned fields, safe computed columns, queryset actions, bounded inlines and audit logging. Use when adding or changing a ModelAdmin, inline, admin action or admin filter.
paths:
  - "**/admin.py"
  - "**/admin/**/*.py"
  - "**/admin_sites.py"
  - "**/admin_filters.py"
---

# Django Admin

The admin is a privileged operational surface, not a scaffold. Staff run real workflows through it against
production data, so the same standards apply as to an API endpoint: bounded queries, deliberate write
access, and a record of who changed what.

## Quick Reference

| If you're about to... | Watch out for... | § |
|---|---|---|
| Put a FK in `list_display` | One extra query per row unless it is in `list_select_related` | 2 |
| Add a method column | Not sortable or searchable until you say what backs it | 2 |
| Add a FK to the change form | The default widget loads **every** row into a `<select>` | 3 |
| Render HTML in a column | `format_html`, never an f-string or `mark_safe` | 4 |
| Expose a machine-written field | Make it read-only, or staff will edit what a task owns | 5 |
| Write a bulk action | Operate on the queryset, and confirm anything destructive | 6 |
| Add an inline | It runs its own query per parent row and can render thousands of forms | 7 |
| Delete via the admin | `delete_queryset` bypasses the model's `delete()` | 6 |

---

## 1. Registration

```python
@admin.register(Complaint)
class ComplaintAdmin(admin.ModelAdmin):
    ...
```

Every model that staff genuinely operate on gets a deliberate `ModelAdmin`. Registering a model with no
configuration produces a page that lists `Complaint object (1)` and loads every row into every widget —
worse than not registering it.

Models nobody administers should not be registered at all. The admin is not documentation of the schema.

---

## 2. The List Page

```python
@admin.register(SelectedTest)
class SelectedTestAdmin(admin.ModelAdmin):
    list_display = ("id", "product", "test_type", "lab", "status", "created")
    list_select_related = ("product", "test_type", "lab")
    list_filter = ("status", "test_type", "created")
    search_fields = ("product__name", "lab__name")
    date_hierarchy = "created"
    ordering = ("-created",)
    list_per_page = 50
```

❌ **Anti-pattern:** a FK in `list_display` with no `list_select_related`.
**Why?** Every rendered row triggers its own query for each related object. A 100-row page with three FK
columns issues around 300 extra queries — the admin's most common performance failure, and it only shows
up once the table has real data.

For anything beyond forward FKs, override the queryset:

```python
def get_queryset(self, request):
    return super().get_queryset(request).prefetch_related("documents")
```

**Method columns** are not sortable or searchable by default — the ORM has no column to work with. Declare
what backs them:

```python
@admin.display(description=_("Author"), ordering="creator__email")
def author(self, obj):
    return obj.creator.email
```

> ⚠️ `search_fields` spanning relations (`product__name`) adds a join per term and runs `LIKE` against it.
> Keep the list short and pointed at indexed columns; a search box over six related text fields is a table
> scan waiting for a busy afternoon.

`list_filter` on a high-cardinality FK renders one option per row — filter on a status or a date instead,
or use a custom filter that returns a bounded set.

---

## 3. Related-Field Widgets

The default FK widget renders every candidate row as an `<option>`. That is fine for a lookup table with
twelve entries and fatal for one with a hundred thousand.

| Rows in the target table | Use |
|---|---|
| small, stable lookup | default select |
| large, and the target has `search_fields` | `autocomplete_fields` |
| large, or no search configured | `raw_id_fields` |

```python
autocomplete_fields = ("product", "lab")     # needs search_fields on ProductAdmin / LabAdmin
raw_id_fields = ("creator",)
```

`filter_horizontal` makes M2M fields usable — but the same cardinality caveat applies, since it also loads
the full candidate list.

---

## 4. Computed Columns

```python
@admin.display(description=_("Document"))
def document_link(self, obj):
    if not obj.file:
        return "—"
    return format_html(
        '<a href="{}" target="_blank">{}</a>',
        obj.file.url,
        obj.original_name or obj.file.name,
    )
```

❌ **Never** build admin HTML with an f-string plus `mark_safe`:
```python
return mark_safe(f'<a href="{obj.url}">{obj.name}</a>')      # stored XSS
```
**Why?** `obj.name` is user-supplied. `format_html` escapes its arguments while keeping the template
literal intact; `mark_safe` promises the whole string is already safe, which is exactly the thing you
cannot promise about user data.

Return a plain placeholder (`"—"`) for empty values rather than `None`, so columns stay aligned and the
absence is visibly deliberate.

---

## 5. Read-Only and Partially-Read-Only Admins

When rows are written entirely by the system — job records, imports, generated documents — the admin exists
to inspect them, not to edit them:

```python
readonly_fields = ("uuid", "status", "progress", "params", "error", "started_at", "finished_at")

def has_add_permission(self, request):
    return False

def has_change_permission(self, request, obj=None):
    return False
```

Keep `delete` available only if deleting is a real operational need — and remember that deleting a row
with an attached file must also clear storage (the model handles that; see the files skill).

> ⚠️ Any field a background task writes must be read-only. Otherwise a staff member editing an unrelated
> field saves the whole form and silently overwrites a status the worker set two seconds earlier.

For mixed cases, compute the read-only set:

```python
def get_readonly_fields(self, request, obj=None):
    if obj and obj.status != Invoice.STATUS.draft:
        return self.readonly_fields + ("amount", "currency")
    return self.readonly_fields
```

Group long forms with `fieldsets`, and `exclude` internal columns that would only invite editing.

---

## 6. Actions

Bulk actions operate on the queryset — one statement, not a loop of saves:

```python
@admin.action(description=_("Mark selected complaints resolved"))
def mark_resolved(modeladmin, request, queryset):
    updated = queryset.exclude(status=Complaint.STATUS.resolved).update(
        status=Complaint.STATUS.resolved,
        resolved_at=timezone.now(),
    )
    modeladmin.message_user(request, _("%(count)d resolved.") % {"count": updated})
```

- **Report the outcome** with `message_user` — a silent action is indistinguishable from one that matched
  nothing.
- **Confirm destructive actions** with an intermediate page; the checkbox column is easy to mis-click.
- **Actions that need per-object logic** (side effects, validation, signals) must iterate deliberately and
  say so — `update()` skips `save()`, signals and `auto_now`.

> ⚠️ `queryset.delete()` does not call each model's `delete()`. If a model cleans up storage or related
> state in its `delete()`, the admin's bulk delete bypasses it — that is why cleanup belongs in a
> `post_delete` receiver as well. Override `delete_queryset` when the bulk path needs to differ.

---

## 7. Inlines

Inlines are convenient and quietly expensive: each one runs its own query per parent, renders a form per
child, and validates them all on save.

```python
class SampleInline(admin.TabularInline):
    model = Sample
    extra = 0
    max_num = 20
    fields = ("order", "data")
    readonly_fields = ("order",)
    show_change_link = True
```

- **`extra = 0`** — blank forms are almost never what staff want, and each one is markup.
- **`max_num`** — bounds a page that would otherwise render every child row.
- **`show_change_link = True`** so an unbounded collection is browsed on its own page instead.
- Give the inline its own `get_queryset` with `select_related` if its columns traverse relations.

If a parent can have thousands of children, do not inline them at all — link to the filtered child list.

---

## 8. Audit Logging

Django records admin changes in `LogEntry`, but only field-level diffs on standard operations. Anything
consequential — a status flip, a role change, a bulk write, an import kicked off — should log actor, action
and object explicitly:

```python
logger.info("%s marked %s resolved", request.user, complaint.pk)
```

Log identifiers, never personal data or credentials. Where a shared base admin class exists for this in the
repository, use it rather than adding a second logging convention.

Sensitive operational surfaces (imports, exports, anything that mutates other users' data) deserve the same
allow/deny thinking as an API endpoint — `has_*_permission` methods are where that belongs.

---

## 9. Security

- **The admin is a privileged surface.** Access is `is_staff` plus whatever the project layers on top;
  treat that flag as a real grant, not a convenience.
- **Never surface secrets** — tokens, keys, hashed passwords, raw payloads containing credentials. Exclude
  the field or render a redacted representation.
- **Raw JSON columns are user input.** Render them read-only and escaped; never through `mark_safe`.
- **Files linked from the admin follow the project's serving rules** — a private document gets a
  permission-checked view, not a bare storage URL.

---

## 10. Checklist

- [ ] Every FK in `list_display` is covered by `list_select_related`; other traversals by `get_queryset`.
- [ ] Method columns declare `description` and `ordering` where they should be sortable.
- [ ] `list_filter` avoids high-cardinality relations; `search_fields` is short and indexed.
- [ ] Large-table FKs use `autocomplete_fields` or `raw_id_fields`.
- [ ] HTML columns built with `format_html`; no `mark_safe` on user data.
- [ ] Machine-written fields are read-only; add/change permissions disabled where rows are system-owned.
- [ ] Actions work on the queryset, report their outcome, and confirm destructive operations.
- [ ] Inlines bounded with `extra = 0` and `max_num`; large collections linked instead.
- [ ] Consequential operations log actor, action and object id — with no PII.
- [ ] No secrets rendered anywhere on the page.

## Navigation
- [DRF Endpoints](../drf-endpoints/SKILL.md)
- [Django App Layout](../django-app-layout/SKILL.md)
- [Files & Uploads](../files-uploads/SKILL.md)
- [Celery Tasks](../celery-tasks/SKILL.md)
