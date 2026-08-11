---
name: django-testing
description: Covers test conventions — pytest layout and discovery, factory_boy data, shared conftest fixtures, API tests with namespaced reverses, allow-and-deny coverage of permissions, writing the failing test before the implementation, and the coverage gate. Use when writing, fixing or running tests, adding factories and fixtures, or deciding what to test before implementing a requirement.
paths:
  - "**/tests/**/*.py"
  - "**/test_*.py"
  - "**/conftest.py"
  - "**/factories.py"
  - "**/pytest.ini"
---

# Django Testing

pytest with `pytest-django` and `factory_boy`. Tests live inside the app they cover, build their data
through factories, and hit the API the way a client does — by reversed URL, through `APIClient`.

## Quick Reference

| If you're about to... | Watch out for... | § |
|---|---|---|
| Write any test touching the DB | `pytestmark = pytest.mark.django_db` at module level | 2 |
| Name a test class | Discovery matches `Test*` **or** `*TestCase` — anything else is silently skipped | 1 |
| Create test data | factory_boy, never JSON/YAML fixture files | 4 |
| Build a URL | `reverse()` with the full namespace, never a hardcoded path | 5 |
| Test a role-gated endpoint | Assert the deny branch too — allow-only tests prove nothing | 6 |
| Assert a write succeeded | Check the database, not just the status code | 7 |
| Implement a requirement you can already state | Write the test first, and watch it fail | 10 |
| See a test fail | The code is wrong until proven otherwise — never edit the assertion to match | 10 |
| Change a model | Next run needs `--create-db`, or you test against a stale schema | 11 |
| Open an MR | Changed code must clear the coverage gate | 12 |

---

## 1. Layout and Discovery

```text
<app>/
├── tests/
│   ├── __init__.py
│   ├── conftest.py        # fixtures used across this app only
│   ├── factories.py       # factory_boy definitions for this app's models
│   ├── test_models.py
│   ├── test_serializers.py
│   ├── test_views.py
│   └── test_signals.py
```

One module per layer; split further by concern once a module covers unrelated things
(`tests/handlers/test_<name>.py`). The suite root is the apps directory, configured in `pytest.ini`:

```ini
[pytest]
python_classes =
    *TestCase
    Test*
testpaths =
    <project_name>/apps
addopts =
    --ds=config.settings
    --maxfail=2
    --durations=5
    -rfsExX
    --reuse-db
```

> ⚠️ `python_classes` accepts `Test*` and `*TestCase` only. A class named `ComplaintTests` or
> `TestingComplaints` is collected as nothing at all — no error, no tests, a green run that proves nothing.

Grouping tests in classes is optional; plain module-level functions are equally fine. Use a class when
several tests share setup worth naming.

---

## 2. Database Access

`pytest-django` blocks DB access unless the test asks for it. Declare it once per module:

```python
import pytest

pytestmark = pytest.mark.django_db
```

Add `transaction=True` only when the test needs real transaction behaviour (`on_commit` hooks, `select_for_update`)
— it is markedly slower because the database is truncated rather than rolled back.

---

## 3. Fixtures

The root `conftest.py` provides the shared ones; do not re-create them per app:

| Fixture | Gives you |
|---|---|
| `user` | a verified, usable user |
| `api_client` | an unauthenticated DRF `APIClient` |
| `request_factory` | Django `RequestFactory` for unit-testing view internals |
| `media_storage` | autouse — redirects `MEDIA_ROOT` to a tmpdir so uploads never touch the repo |

App-specific fixtures go in that app's `tests/conftest.py`. When several tests in a module repeat the same
authentication dance, make it a fixture rather than a helper called in every test:

❌ **Anti-pattern:**
```python
def test_list(self, api_client):
    user = UserFactory(role=User.ROLES.SALES)
    api_client.force_authenticate(user)
    ...

def test_retrieve(self, api_client):
    user = UserFactory(role=User.ROLES.SALES)     # same three lines, again
    api_client.force_authenticate(user)
    ...
```

✅ **Recommended (`tests/conftest.py`):**
```python
@pytest.fixture
def sales_client(api_client):
    api_client.force_authenticate(UserFactory(role=User.ROLES.SALES))
    return api_client
```

---

## 4. Factories, Not Fixture Files

❌ **Anti-pattern:** static `fixtures/data.json` loaded with `loaddata`.
**Why?** Add a required field and every fixture file needs manual editing. The data is also invisible from
the test that depends on it, so a reader cannot tell which values matter.

✅ **Recommended (`<app>/tests/factories.py`):**
```python
from factory import Faker, Sequence, SubFactory
from factory.django import DjangoModelFactory

from complaints.models import Complaint, ComplaintType


class ComplaintTypeFactory(DjangoModelFactory):
    name = Sequence(lambda n: f"Complaint type {n}")

    class Meta:
        model = ComplaintType


class ComplaintFactory(DjangoModelFactory):
    subject = Faker("sentence")
    complaint_type = SubFactory(ComplaintTypeFactory)
    status = Complaint.STATUS.pending

    class Meta:
        model = Complaint
```

- **`Sequence` for anything unique** — `Faker` can and will collide within a run.
- **`SubFactory` for FKs**, so a test never has to build a chain of unrelated parents by hand.
- **`django_get_or_create = ("email",)`** on lookup-like models to avoid duplicate rows across a test.
- **`create_batch(n)`** for list-endpoint tests.
- Pass only the fields the assertion depends on: `ComplaintFactory(status=Complaint.STATUS.resolved)`.
  Everything a test spells out reads as significant, so spelling out noise is misleading.

---

## 5. API Tests

Hit the endpoint through `APIClient`, with the URL reversed by its full namespace and status codes taken
from `rest_framework.status`.

```python
import pytest
from django.urls import reverse
from rest_framework import status

from complaints.models import Complaint
from complaints.tests.factories import ComplaintFactory

pytestmark = pytest.mark.django_db


class TestComplaintList:
    def test_returns_only_own_organisation(self, sales_client, user):
        ComplaintFactory.create_batch(2, organisation=user.organisation)
        ComplaintFactory()                                    # another organisation

        response = sales_client.get(reverse("api:complaints:complaints-list"))

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 2
```

- **Reverse inside the test**, not in the class body — a module-level `reverse()` runs at import time and
  turns a URL mistake into a collection error for the whole file.
- **Assert the paginated shape you actually configured** (`response.data["results"]`). A test that accepts
  either a list or a paginated dict is asserting nothing about the contract.
- **Never hardcode `/api/v1/...`** — a renamed route must break the reverse, not silently 404 a test.

---

## 6. Allow *and* Deny

For anything role-gated, ownership-scoped, or state-guarded, the deny branch is the test that matters —
a passing allow-test says nothing about whether the door is locked for anyone else.

```python
@pytest.mark.parametrize(
    "role,expected",
    [
        (User.ROLES.ADMIN, status.HTTP_204_NO_CONTENT),
        (User.ROLES.SALES, status.HTTP_403_FORBIDDEN),
    ],
)
def test_delete_is_admin_only(api_client, role, expected):
    complaint = ComplaintFactory()
    api_client.force_authenticate(UserFactory(role=role))

    response = api_client.delete(
        reverse("api:complaints:complaints-detail", args=(complaint.pk,)),
    )

    assert response.status_code == expected
```

Cover at minimum: anonymous → 401, wrong role → 403, another owner's object → 403/404, and a write blocked
by object state → 400. Field-level permissions need their own test — a dropped write returns **200**, so
only a database assertion catches it:

```python
def test_price_is_ignored_for_roles_without_permission(sales_client, product):
    sales_client.patch(url, {"price": 999})

    product.refresh_from_db()
    assert product.price != 999
```

---

## 7. Assert Outcomes, Not Just Status Codes

A 201 proves the view returned; it does not prove the row is right.

❌ **Anti-pattern:**
```python
assert response.status_code == status.HTTP_201_CREATED
```

✅ **Recommended:**
```python
assert response.status_code == status.HTTP_201_CREATED

complaint = Complaint.objects.get(pk=response.data["id"])
assert complaint.subject == payload["subject"]
assert complaint.organisation == user.organisation      # server-owned, not client-supplied
```

For validation tests, assert the error *shape* as the frontend consumes it:
```python
assert response.status_code == status.HTTP_400_BAD_REQUEST
assert response.data["occurrence_date"] == ["Cannot be in the future."]
```

---

## 8. Celery, Time and External Services

- **Celery runs eagerly under pytest** — a dispatched task executes inline, so assert its effects directly.
  Where a test must confirm dispatch rather than outcome, patch the task's `delay`/`apply_async`.
- **`transaction.on_commit` callbacks do not fire** in the default non-transactional test. Use
  `django_capture_on_commit_callbacks`, or `pytest.mark.django_db(transaction=True)` when the commit itself
  is what you are testing.
- **Never call a real external service.** File storage is already redirected to a tmpdir by the autouse
  fixture; HTTP integrations get patched at their client boundary.
- **Freeze time rather than computing offsets** when asserting on dates, so a test cannot pass in one month
  and fail in the next.

---

## 9. What Deserves a Test

Priority order, not a wishlist:

| Always | Usually | Rarely worth it |
|---|---|---|
| Permission allow **and** deny branches | Serializer validation rules | Straight `ModelSerializer` field mapping |
| State-machine transitions and their guards | Filter/search/ordering params | Django's own ORM behaviour |
| Calculations and derived values | Signal side effects | `__str__` |
| Anything with a bug ticket attached | Task effects | Admin registration |

A regression fix ships with the test that would have caught it — that is what makes the fix permanent.

---

## 10. Writing the Test First

Where a requirement is precise enough to state as an assertion, write the test before the implementation.
Not as a discipline exercise: a test written afterwards is written *from the code*, so it describes what
the code happens to do rather than what was asked for — and it passes just as confidently when the
behaviour is wrong.

**Run it and watch it fail.** A test that has never failed proves nothing; it may be asserting on a
fixture, or exercising a branch that never runs. The failure message is also the first check that it fails
for the intended reason — an `ImportError` where you expected an assertion error means the test is not yet
testing anything.

```python
def test_deviation_above_threshold_is_rejected(sample_set, user):
    with pytest.raises(ValidationError) as exc:
        handler.calculate(sample_set, user)

    assert "standard deviation" in str(exc.value)
```

> ⚠️ **The implementation adapts to the test, not the reverse.** When a test fails, the default assumption
> is that the code is wrong. Editing the assertion to match the output is how a suite quietly stops being
> evidence. If the expectation genuinely was wrong, change it deliberately and say so in the MR description
> — that is a change to the requirement, not a fix.

Worth writing first:

- calculations, parsers and derived values, where the expected output is known before any code exists;
- validation rules and permission matrices — they fall out naturally as a parametrised table;
- **every bug fix**, starting from the failing case in the report;
- anything implemented unattended, where the test is the only thing verifying the result independently of
  whatever produced it.

Not worth it when the shape of the answer is still unknown — write the code, then the test, before the MR.

**Make the gate automatic rather than remembered.** Wire the suite into a hook that runs at the end of a
turn, or into a watch command. "Done" should mean the suite ran, never that the change looked finished.

---

## 11. Running the Suite

```bash
docker-compose -f local.yml run --rm app pytest
docker-compose -f local.yml run --rm app pytest <project>/apps/complaints
docker-compose -f local.yml run --rm app pytest <path>::TestClass::test_name
docker-compose -f local.yml run --rm app pytest -n auto            # parallel
docker-compose -f local.yml run --rm app pytest --cov --cov-report term-missing
```

| Flag | When |
|---|---|
| `--reuse-db` (default) | normal runs — keeps the test database between runs |
| `--create-db` | **after any migration** — otherwise you test against a stale schema |
| `--maxfail=0` | the config aborts after 2 failures; pass this for the full failure list |
| `-n auto` | large suites; beware tests that share module-level state |
| `-x --pdb` | drilling into a single failure |

---

## 12. Coverage Gate

- **New or changed code: 80% line coverage minimum**, enforced in CI — not a target agreed and forgotten.
- **Overall repository coverage must not regress** below its current baseline; that is a pipeline check.
- **Critical paths — auth, payments, RBAC enforcement — need explicit allow *and* deny cases**, regardless
  of what the line-coverage number says. Coverage counts executed lines; it cannot tell whether a branch
  was asserted or merely walked through.

CI runs the same commands as local hooks. A test that passes locally and fails in CI means environment
drift — pinned versions out of sync — not a flaky pipeline.

---

## 13. Checklist

- [ ] Test class named `Test*` or `*TestCase`; module under the app's `tests/` package.
- [ ] `pytestmark = pytest.mark.django_db` present.
- [ ] Data built with factories; no static fixture files, no hand-built model chains.
- [ ] URLs reversed by full namespace, inside the test body.
- [ ] Both allow and deny branches covered for every permission or state guard.
- [ ] Assertions check database state and error shape, not only status codes.
- [ ] Dropped-write tests exist for field-level permissions (they return 200).
- [ ] No real external calls; time frozen where dates are asserted.
- [ ] For a stateable requirement or a bug fix, the test was written first and seen to fail.
- [ ] No assertion was relaxed to make a failing test pass.
- [ ] `--create-db` used after a migration.
- [ ] Changed code clears the coverage gate.

## Navigation
- [DRF Endpoints](../drf-endpoints/SKILL.md)
- [Django App Layout](../django-app-layout/SKILL.md)
- [Celery Tasks](../celery-tasks/SKILL.md)
- [Files & Uploads](../files-uploads/SKILL.md)
- [Git Workflow & MR](../git-workflow-mr/SKILL.md)
