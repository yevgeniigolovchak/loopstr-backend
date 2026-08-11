---
paths:
  - "**/tests/**/*.py"
  - "**/test_*.py"
  - "**/conftest.py"
  - "**/factories.py"
---

# Tests

- **Name test classes `Test*` or `*TestCase`.** Anything else is collected as nothing at all — no error,
  no tests, a green run that proves nothing.
- **`pytestmark = pytest.mark.django_db`** at module level for anything touching the database.
- **Build data with `factory_boy`**, never static fixture files. `Sequence` for unique values,
  `SubFactory` for FKs, and pass only the fields the assertion depends on.
- **Reverse URLs by full namespace, inside the test body** — a module-level `reverse()` turns a URL mistake
  into a collection error for the whole file.
- **Cover the deny branch, not only the allow branch.** Anonymous → 401, wrong role → 403, another owner's
  object → 403/404.
- **Field-level permission drops return 200** — only a `refresh_from_db()` assertion catches them.
- **Assert database state and error shape**, not just the status code.
- Reuse the root `conftest.py` fixtures; never hit a real external service.
- Run `--create-db` after any migration, or you are testing against a stale schema.

Details: [django-testing](../skills/django-testing/SKILL.md)
