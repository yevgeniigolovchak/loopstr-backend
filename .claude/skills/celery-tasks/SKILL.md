---
name: celery-tasks
description: Covers Celery task conventions — registration and the unregistered-task trap, id-not-instance arguments, dispatch via on_commit, error callbacks that stop jobs hanging, targeted retries, idempotency and beat schedules. Use when adding, dispatching, scheduling, debugging or testing asynchronous work.
paths:
  - "**/tasks.py"
  - "**/tasks/**/*.py"
  - "**/taskapp/**/*.py"
---

# Celery Tasks

Async work runs in a separate worker process with its own copy of the code and no request context. Almost
every rule here exists because that process does not see what the web process just did.

## Quick Reference

| If you're about to... | Watch out for... | § |
|---|---|---|
| Add a new task module | The worker registered tasks at boot — restart it or every call fails | 3 |
| Pass an argument | Send ids, never model instances | 2 |
| Dispatch from inside a transaction | The worker can read the row before it is committed — use `on_commit` | 4 |
| Start a job that a user is watching | Link an error callback, or a crash leaves it stuck "in progress" forever | 5 |
| Add retries | `autoretry_for=(Exception,)` retries your own bugs, forever | 6 |
| Let a task run twice | Redelivery is normal — the task must tolerate it | 7 |
| Schedule periodic work | Beat state files are local artefacts, not repository content | 8 |
| Test a task | It runs inline under pytest — assert its effects, not its dispatch | 9 |

---

## 1. Where Tasks Live

Tasks live in each app's `tasks.py` and are found automatically — `app.autodiscover_tasks()` walks
`INSTALLED_APPS`. The Celery app itself is defined once:

```python
import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("<project_name>")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
```

The `CELERY_` namespace means every setting is read from Django settings: `CELERY_BROKER_URL`,
`CELERY_RESULT_BACKEND`, `CELERY_TASK_ALWAYS_EAGER`.

Worker and beat run as separate services. A task module that is neither in an installed app's `tasks.py`
nor imported from one is never registered, however correct it looks.

---

## 2. Writing a Task

A task is a thin entry point: load, delegate, record. The work belongs in a service or model method — the
same one a synchronous caller would use.

✅ **Recommended:**
```python
from celery.utils.log import get_task_logger

from taskapp.celery import app

logger = get_task_logger(__name__)


@app.task(name="generate_report", bind=True)
def generate_report(self, report_id: int):
    """Produce the document for a queued report."""
    report = Report.objects.filter(pk=report_id).first()
    if report is None:
        logger.error("Report %s not found", report_id)
        return
    ...
```

- **Explicit `name=`** decouples the queue name from the module path, so moving the module doesn't strand
  messages already sitting in the broker addressed to the old path.
- **`bind=True`** when the body needs `self` — the request id, or `self.retry()`.
- **`shared_task` instead of `app.task`** in apps meant to be reusable across projects; pick one per
  repository rather than mixing both in the same app.

### Arguments Are Ids, Never Objects

❌ **Anti-pattern:**
```python
generate_report.delay(report)
```
**Why?** The instance is serialised at dispatch, so the worker operates on a snapshot taken before the
task ran, silently overwriting anything changed in between — and any non-serialisable field fails outright.

✅ **Recommended:**
```python
generate_report.delay(report.pk)
```

Pass primitives: ids, strings, numbers. The task re-loads the row and sees current state.

> ⚠️ **Handle the row being gone.** Between dispatch and execution the object may have been deleted. A
> task that assumes `objects.get()` succeeds turns an ordinary deletion into a stack trace in the logs.

---

## 3. The Unregistered-Task Trap

The worker imports and registers tasks **when it boots**. A task added afterwards does not exist as far as
that process is concerned:

```text
Received unregistered task of type 'myapp.tasks.new_task'
```

The web application works fine — it only needs to publish a message — so this looks like a broker problem
and is not.

```bash
docker-compose -f local.yml restart celery
```

> ⚠️ The same applies on deploy: a release that adds a task module requires a worker restart, not just a
> web restart. Renaming or moving an existing task is worse — messages queued under the old name are still
> in the broker and will fail on arrival. Keep the old name registered until the queue has drained.

---

## 4. Dispatching

`delay(...)` for plain arguments; `apply_async(...)` when you need options (countdown, queue, callbacks).

### Never Dispatch Inside an Open Transaction

❌ **Anti-pattern:**
```python
with transaction.atomic():
    report = Report.objects.create(...)
    generate_report.delay(report.pk)      # worker may run before COMMIT
```
**Why?** The worker is a different connection. It can pick the message up before the transaction commits
and find no such row — and if the transaction later rolls back, the task has already run against data that
never existed.

✅ **Recommended:**
```python
with transaction.atomic():
    report = Report.objects.create(...)
    transaction.on_commit(lambda: generate_report.delay(report.pk))
```

---

## 5. A Job Must Never Be Left "In Progress"

When a task backs a row the user is watching — a job, an import, an export — a crash between "started" and
"finished" leaves that row permanently in its intermediate state. Handle both failure directions:

**Expected failures** — caught inside the task and recorded in the job's own words:
```python
try:
    content, filename = builder.build(report, ProgressReporter(report))
except ValidationError as error:
    report.mark_failed(_flatten(error))
    return
```

**Everything else** — an error callback linked on *every* dispatch:
```python
@app.task(name="report_error_callback")
def report_error_callback(request, exception, traceback):
    """Mark the job failed when its task raised something unforeseen."""
    try:
        report_id = request.args[0]
    except IndexError:
        logger.error("Expected 'report_id' as the first argument (request.args)")
        return

    report = Report.objects.filter(pk=report_id).first()
    if report is None or report.is_finished:
        return
    logger.error("Report %s failed in %s: %s", report.uuid, request.task, exception)
    report.mark_failed(str(exception))
```

```python
generate_report.apply_async(
    args=(report.pk,),
    link_error=Signature("report_error_callback"),
)
```

The callback receives the failing **request**, not the arguments, so keep the job id as the first
positional argument of every task in the chain — that convention is what makes the row recoverable.

> ⚠️ `link_error` must be attached at **every** dispatch site, including re-queues from inside another
> task. One dispatch without it is one path that can hang a job silently.

---

## 6. Retries

Retry what is genuinely transient — a timed-out HTTP call, a briefly unavailable service. Retrying a bug
just runs it again.

❌ **Anti-pattern:**
```python
@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, max_retries=5)
```
**Why?** `Exception` covers `TypeError`, `AttributeError` and `DoesNotExist` — programming errors and
missing rows get retried five times with backoff, delaying the failure report and multiplying the logs,
before failing exactly as they would have immediately.

✅ **Recommended:**
```python
@shared_task(
    bind=True,
    autoretry_for=(RequestException, TimeoutError),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=5,
)
def sync_employee(self, employee_id: int):
    ...
```

- **`retry_backoff=True`** — exponential spacing instead of hammering a service that is already struggling.
- **`retry_jitter=True`** — stops a batch of tasks retrying in lockstep.
- **A finite `max_retries`.** Infinite retries hide an outage instead of surfacing it.
- **Anything retried must be idempotent** (§7) — a retry after a partial success must not double-write.

---

## 7. Idempotency

A message can be delivered more than once: a worker dies mid-task, a retry fires, a user double-clicks.
Design for a second run rather than assuming one.

```python
@app.task(name="generate_report", bind=True)
def generate_report(self, report_id: int):
    report = Report.objects.filter(pk=report_id).first()
    if report is None:
        return
    if report.is_finished:
        # A retry or duplicate dispatch must not overwrite a finished job.
        logger.warning("Report %s is already %s", report.uuid, report.status)
        return
```

Patterns that make a second run harmless: guard on current state before doing the work; `get_or_create` /
`update_or_create` instead of blind `create`; a natural unique key on whatever the task produces.

---

## 8. Periodic Tasks

Declared in the beat schedule next to the Celery app:

```python
app.conf.beat_schedule = {
    "delete-unbound-product-images": {
        "task": "files.tasks.delete_unbound_product_images",
        "schedule": crontab(hour=3, minute=0),
    },
}
```

Reference the task by its registered name and give the entry a descriptive key — that key is what appears
in beat's logs. Prefer `crontab(...)` over a raw interval for anything that should run at a specific time.

> ⚠️ `celerybeat-schedule*` files in the repository root are the local scheduler's own state. They change
> on every run and must never be committed.

Periodic tasks need the same care as any other: idempotent, and safe if a run is skipped or doubled.

---

## 9. Testing Tasks

Celery runs **eagerly** under pytest — `CELERY_TASK_ALWAYS_EAGER` is forced on — so a dispatched task
executes inline, synchronously, in the same transaction as the test.

✅ **Assert the effect, not the call:**
```python
def test_report_is_generated(user):
    report = ReportFactory(status=Report.STATUS.pending)

    generate_report(report.pk)

    report.refresh_from_db()
    assert report.status == Report.STATUS.done
    assert report.file
```

- **Test the task's effect**, not that `.delay` was called — mocking the dispatch tests the mock.
- **Patch `.delay` only** when the assertion is genuinely about dispatch (correct arguments, dispatched
  once, not dispatched at all on a validation failure).
- **`on_commit` callbacks do not fire** in the default test transaction. Use
  `django_capture_on_commit_callbacks(execute=True)`, or mark the test `django_db(transaction=True)`.
- **Error callbacks are not exercised by eager execution** — call the callback directly, with a stub
  request object carrying `args`, to prove a failed job is marked failed.

---

## 10. Logging

Use `get_task_logger(__name__)`, which tags records with the task name and id.

Log a line when a task gives up early — row missing, job already finished, unknown type — otherwise a task
that quietly returns is indistinguishable from one that never ran. Log ids, never personal data, tokens or
passwords; if a value is needed only for correlation, hash it.

---

## 11. Checklist

- [ ] Task lives in an installed app's `tasks.py`; worker restarted after adding the module.
- [ ] Arguments are ids and primitives, never model instances.
- [ ] The task tolerates its row having been deleted since dispatch.
- [ ] Dispatch inside a transaction goes through `transaction.on_commit`.
- [ ] Jobs a user watches carry `link_error` on **every** dispatch, with the job id as first argument.
- [ ] Retries name specific transient exceptions, with backoff and a finite `max_retries`.
- [ ] A second run of the task is harmless.
- [ ] Beat entries reference the registered task name; scheduler state files are not committed.
- [ ] Tests assert effects; `on_commit` paths use the capture fixture.
- [ ] Early returns are logged; no PII in log lines.

## Navigation
- [DRF Endpoints](../drf-endpoints/SKILL.md)
- [Django App Layout](../django-app-layout/SKILL.md)
- [Django Testing](../django-testing/SKILL.md)
- [Git Workflow & MR](../git-workflow-mr/SKILL.md)
