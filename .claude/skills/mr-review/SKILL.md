---
name: mr-review
description: Covers reviewing someone else's merge request — what review is and is not for, the order to read a diff in, stack-specific things that break silently, severity levels, how to write actionable comments, the extra scrutiny an agent-written diff needs, and when to approve. Use when reviewing a merge request, reading a diff written by someone else or by an agent, or responding to review feedback.
---

# Merge Request Review

Reviewing is reading someone else's diff and deciding whether it should join the codebase. It is a
different job from checking your own work before opening an MR — you arrive without the author's context,
which is exactly what makes the review worth doing.

## Quick Reference

| If you're about to... | Watch out for... | § |
|---|---|---|
| Start a review | Read the ticket and the description first — a diff alone can't be judged | 2 |
| Hunt for bugs | That is QA's job; review is for design, clarity and knowledge transfer | 1 |
| Comment on formatting | The linter already ran — if it passed, that is the answer | 7 |
| Flag something | Say what is wrong, why it matters, and what to do instead | 5 |
| Review a viewset | Check the queryset scoping and the deny path, not just the happy path | 3 |
| Review a migration | Check it runs on a database that already has rows | 3 |
| Resolve a thread | The reviewer resolves, not the author | 6 |
| Approve | Approval is not a substitute for a green pipeline | 8 |
| Review an agent-written diff | Fluency is not correctness — check it against the ticket, not just the diff | 9 |
| See a silenced lint rule or a skipped test | A bypassed guardrail is a finding, whoever wrote it | 9 |

---

## 1. What Review Is For

**Not for finding bugs.** That is what tests and QA are for, and a reviewer reading a diff will always be
worse at it than the suite. Treating review as bug-hunting produces slow reviews that still miss the bug.

Review exists for what only another person can supply:

- **Does this solve the problem the ticket describes?** — spec compliance is the one thing tests cannot check.
- **Will the next person understand it?** — naming, structure, the absence of unnecessary cleverness.
- **Is there a simpler or more conventional way?** — an alternative the author did not consider.
- **Knowledge transfer.** After the review, two people know how this works instead of one.

The reviewer is usually the tech lead, but any backend developer on the project can do it — and reviewing
code you did not write is how you learn a codebase faster than by reading it.

---

## 2. Read in This Order

Reading a diff top to bottom, file by file, is the slowest way to review and the easiest way to miss the
point of the change.

1. **The ticket.** What was actually asked for. Without this you can only review style.
2. **The MR description.** What the author says they changed. If you cannot predict the diff from it, that
   is your first comment — the description is part of the deliverable.
3. **The tests.** They state the intended behaviour more precisely than the description, and their gaps
   show what the author was unsure about.
4. **The models and migrations.** Data shape constrains everything above it.
5. **The rest of the diff**, now that you know what you are looking at.
6. **What is *not* in the diff.** A new endpoint with no permission test, a model change with no migration,
   a new task with no error handling — absence is the hardest thing to see and the most common real defect.

For a large MR, say so early rather than reviewing it badly: a diff that cannot be held in one reading
should have been several MRs, and that feedback is more valuable than line comments on half of it.

---

## 3. What Actually Breaks in This Stack

Generic review advice finds generic problems. These are the ones that reach production here, and each is
visible in a diff if you look for it:

**Queries**
- A relation traversed in a loop or a serializer without `select_related` / `prefetch_related`.
- A list endpoint or admin list page whose queryset grew a new related column.
- A `for` loop doing `save()` where `bulk_update` belongs.

**Permissions**
- `get_queryset()` that does not scope by the requester — the leak that no status code reveals.
- A new endpoint or action with tests only for the allowed role.
- A custom action fetching an object without `check_object_permissions`.

**API contract**
- `ValidationError` with a bare string value instead of a list.
- `Meta.fields = "__all__"`, or a new model field that silently joined an existing response.
- A serializer key in `get_serializer_class()` that does not match the action name.
- A response shape change with no corresponding schema decorator.

**Migrations**
- A required column added without the nullable-backfill-tighten sequence.
- `RunPython` with a direct model import, no reverse, or no guard against re-running.
- A rename that the diff performs in one step while old code is still deployed.

**Async and files**
- A task dispatched inside an open transaction, or receiving a model instance instead of an id.
- A new task with no error callback on a job someone is watching.
- A file-bearing model whose cleanup does not cover the cascade path.

**Everything**
- A bare `except Exception`, or an exception caught and neither handled nor logged.
- A new setting hardcoded at its use site.
- A `TODO` shipped in the diff.

---

## 4. Severity

Say which kind of comment you are making. A reviewer whose blocking objections and preferences look
identical trains authors to treat both as optional.

| Level | Means | Example |
|---|---|---|
| **Blocking** | Must change before merge | Missing authorisation scope; a migration that fails on a populated database |
| **Should fix** | Change unless there is a reason not to | N+1 on a list endpoint; a missing deny-path test |
| **Nit** | Preference, author's call | Naming choice, ordering of methods |
| **Question** | You do not understand yet | "What happens if this runs twice?" |

Prefix the ones that are not blocking: `nit:`, `question:`, `suggestion:`. An unprefixed comment reads as
required work.

If the whole approach is wrong, say that once, at the top, and stop line-commenting — twenty comments on
code that should not exist wastes both people's time.

---

## 5. Writing a Comment

A useful comment contains three things: **what**, **why it matters**, and **what to do instead**.

❌ **Unhelpful:**
> This is wrong.

> Use select_related here.

✅ **Actionable:**
> `get_queryset()` isn't scoped to the requester's organisation, so any authenticated user can retrieve any
> complaint by id. Add the `organisation` filter here rather than in the serializer — this is the only hook
> that runs for both list and detail.

Be specific about the consequence. "This is an N+1" is a label; "this issues one query per row, so the list
page will slow down as the table grows" is a reason someone can weigh.

**Ask when you do not know.** "Is this intentional?" costs nothing and is often correct — the author has
context you do not. Asserting and being wrong costs the review's credibility.

**Praise the non-obvious.** A comment saying a tricky piece is well handled is not politeness; it tells the
author which of their decisions read clearly to someone else.

Attack the code, never the author: "this function does three things" rather than "you wrote this badly."

---

## 6. Rounds and Threads

A review runs in rounds: the author pushes, you comment, they respond, repeat until you approve.

- **Keep each round cheap to re-read.** The author should push fixes as ordinary commits during review, so
  you can see what changed since last round. Squashing happens on merge, not mid-review.
- **The reviewer resolves threads.** An author resolving their own thread closes a conversation the other
  person may not consider finished. Author replies, reviewer resolves.
- **Re-review only what changed** — you already read the rest.
- **Disagreement gets decided in the thread**, not by quietly not doing it and not by the reviewer
  insisting on preference. If it cannot be settled, escalate rather than stalling the MR.
- **Be quick.** A review sitting for two days costs more than the defect it might find; the author has moved
  on and will have to reload the whole change to answer you.

---

## 7. What Not to Comment On

| Don't | Why |
|---|---|
| Formatting, import order, line length | The formatter and linter ran in CI; if they passed, it is correct |
| Style with no rule behind it | "I would have written it differently" is not a finding |
| Rewriting working code to your preference | Different is not better; scope creep in review is still scope creep |
| Pre-existing problems in touched files | Open a ticket — an MR is not obliged to fix what it walked past |
| Hypothetical future requirements | Review what was asked for, not what might be asked later |

If you find yourself writing many comments about things the tooling should catch, the fix is a linter rule
or a hook, not repeated review comments.

---

## 8. Approving

Approve when the change does what the ticket asked, you understand it, and nothing blocking remains.
Outstanding nits are not a reason to withhold approval — say "approving, address the nit if you agree."

- **Approval is not a substitute for a green pipeline.** Merge on both.
- **"The tests pass" is a claim about CI, not about the author's word for it** — including when the author
  is an agent.
- **If you cannot understand a change after a round of questions**, that is itself the finding: code that
  cannot be explained to a colleague cannot be maintained by one.

---

## 9. Reviewing Agent-Assisted Code

A diff an agent wrote reads better than one a person wrote at the end of a long day, and that is precisely
the difficulty: fluency is not correctness, and review instincts are calibrated on the assumption that
confident, consistent code came from someone who understood the domain.

**Label it.** The description says which parts were agent-written — not as a disclaimer, but because it
tells the reviewer where to spend attention, the same way "refactor, no behaviour change" does.

**The session that wrote the code does not review it.** It re-derives the same assumptions and confirms
them. Review needs context the author lacks: a fresh session, or a person — and a person for anything
touching authorisation, money, or data loss.

**Verify against the spec, not against the diff.** A diff review asks whether the code is sensible; a
plausible implementation of the *wrong requirement* passes that test every time. Read the ticket, then
check the code does that. This is the failure mode that actually gets through.

**Make the deterministic gate visible.** The pipeline output is the evidence — not a line in the
description saying the tests pass. "I ran the tests" is not review input, whoever wrote it.

**Check that referenced things exist.** Model fields, settings, helper functions, third-party keyword
arguments — generated code invents plausible names, and an import that resolves is not proof the attribute
does.

**Tests written after the code, from the code**, assert what the implementation happens to do rather than
what the requirement is, and pass either way. Read each assertion and ask which bug it would catch; if the
answer is none, the test is decoration.

> ⚠️ **A bypassed guardrail is a finding, always.** Completing the task is the objective, and removing the
> obstacle completes the task:
>
> - `# noqa`, `# type: ignore`, `--no-verify`, a loosened lint rule, an edited CI config
> - a test deleted, skipped, or with an assertion weakened
> - a permission class, validator or constraint removed to make something pass
> - a dependency version changed with no mention in the description
>
> Any of these may be legitimate. None is legitimate *silently* — ask, every time. The rule applies to human
> authors identically; it simply comes up more often here.

**Push back on size.** Generating a thousand-line diff costs nothing; reviewing one costs what it always
did. The limit is still what one person can hold in a single reading.

---

## 10. Receiving a Review

- **Assume good faith.** A comment is about the code; the reviewer usually has less context than you, which
  is exactly why they can see what you stopped seeing.
- **Reply to every thread**, even to agree — silence reads as disagreement.
- **Push fixes as new commits**, so the reviewer can see the delta.
- **Explain rather than comply** when you disagree. "I did it this way because X" is a legitimate answer
  and often ends the thread.
- **A repeated comment is a convention.** If the same thing comes up in three reviews, it belongs in the
  project's written conventions, not in a fourth review.

---

## 11. Checklist

- [ ] Ticket and description read before the diff.
- [ ] Change matches what the ticket asked for.
- [ ] Tests read first; gaps and missing deny-path cases noted.
- [ ] Querysets scoped by requester; relations pre-fetched.
- [ ] Error shapes, serializer contracts and schema decorators consistent.
- [ ] Migrations safe on a populated database and reversible.
- [ ] Async work: ids not instances, dispatch after commit, failures recorded.
- [ ] Exceptions specific, handled and logged.
- [ ] No guardrail silently bypassed — suppressions, skipped tests, relaxed checks all accounted for.
- [ ] Comments state what, why and what instead; non-blocking ones prefixed.
- [ ] Nothing flagged that the linter already covers.
- [ ] Approved only alongside a green pipeline.

## Navigation
- [Git Workflow & MR](../git-workflow-mr/SKILL.md)
- [DRF Endpoints](../drf-endpoints/SKILL.md)
- [Database Migrations](../db-migrations/SKILL.md)
- [Django Testing](../django-testing/SKILL.md)
