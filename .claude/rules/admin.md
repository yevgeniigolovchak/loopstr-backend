---
paths:
  - "**/admin.py"
  - "**/admin/**/*.py"
---

# Django admin

- **Every FK in `list_display` needs `list_select_related`.** Otherwise each rendered row issues its own
  query per relation — the admin's most common performance failure, invisible until the table has real data.
- **Large-table FKs use `autocomplete_fields` or `raw_id_fields`.** The default widget renders every
  candidate row as an `<option>`.
- **Build HTML with `format_html`, never `mark_safe` on user data** — that is stored XSS.
- **Fields written by a background task are read-only.** Otherwise editing an unrelated field saves the
  whole form and overwrites a status the worker just set.
- **Disable add/change permissions** where rows are entirely system-owned.
- **Actions operate on the queryset** and report their outcome with `message_user`; confirm destructive
  ones. Remember `update()` skips `save()`, signals and `auto_now`.
- **`queryset.delete()` does not call the model's `delete()`** — cleanup that lives there is bypassed by
  bulk admin deletes.
- **Bound inlines** with `extra = 0` and `max_num`; link to a filtered list instead when a parent can have
  thousands of children.
- Never render secrets, tokens or hashed passwords on an admin page.

Details: [django-admin](../skills/django-admin/SKILL.md)
