---
name: git-workflow-mr
description: Covers branching, commit message format, rebasing and squashing, the merge request description contract, and the author's self-review checklist. Use when starting a branch, writing a commit message, preparing history for review, or opening a merge request.
---

# Git Workflow & Merge Requests

Feature-branch workflow off `develop`, rebased rather than merged, squashed on accept. The commit history
is documentation: it should read as a sequence of deliberate changes, not a transcript of how the day went.

## Quick Reference

| If you're about to... | Watch out for... | § |
|---|---|---|
| Start work | Branch off an up-to-date `develop` — never commit to it directly | 1 |
| Write a commit message | `ABC-123: Add thing` — imperative, ≤50 chars, capitalised | 2 |
| Finish a commit message | Every commit gets a body: motivation, and how it differs from before | 2.1 |
| Commit an infra change with no ticket | `feat:` / `fix:` / `chore:` prefix instead of a ticket id | 2 |
| Push a branch with WIP commits | Squash them first — one topic per commit | 3 |
| Open the MR | Ticket link + bulleted changes; enable squash and delete-source-branch | 5 |
| Request review | Self-review the diff first — reviewers are not linters | 6 |
| Rewrite pushed history | `--force-with-lease`, never plain `--force` | 3 |
| Commit anything | Secrets, `.env`, local scheduler state and commented-out code stay out | 9 |

---

## 1. Branching

```bash
git checkout develop
git pull
git checkout -b ABC-123
```

Name the branch after the ticket. Rebase often so the eventual MR is a small, current diff:

```bash
git fetch origin
git rebase origin/develop
```

> ⚠️ A pre-commit hook blocks direct commits to `develop`, `staging` and `master`. If it fires, you are on
> the wrong branch — move the work rather than bypassing the hook:
> ```bash
> git branch ABC-123 && git reset --hard origin/develop && git checkout ABC-123
> ```

Prefer rebase over merge while the branch is in flight. Merge commits from `develop` into a feature branch
turn the MR diff into a history lesson nobody asked for.

---

## 2. Commit Messages

**Ticketed work** — the overwhelming majority:

```text
ABC-123: Add async report generation and API
```

- Ticket id, colon, space, then a **capitalised imperative summary**: "Add", not "Added" or "Adds".
- **50 characters maximum**, no trailing period.
- Blank line, then the body (§2.1) — the summary alone is not a finished message.

**Changes with no ticket** — infrastructure, tooling, dependency bumps:

```text
feat: add pre-commit hook for secrets scanning
fix: correct Celery broker URL in local compose
chore: bump black to the current release
```

### 2.1 The Body

Separate it from the summary by a blank line, and answer two questions:

1. **What was the motivation for the change?**
2. **How does it differ from the previous implementation?**

```text
ABC-123: Redirect user to the requested page after login

Users landed on the home page after logging in, losing the page they
originally asked for — the deep link they followed was discarded as soon
as the login form took over.

- Store the requested path in a session variable
- Redirect to the stored location once authentication succeeds
- Fall back to the home page when no path was stored
```

Prose, bullets, or both — whichever states the reasoning most plainly.

The body answers **why**, never **what**: the diff already says what. Restating the diff in words is what
makes bodies feel like busywork, and it is the reason they get skipped.

> ⚠️ A commit whose motivation genuinely fits in the summary — a typo fix, a version bump — still gets a
> body line saying so. "Nothing to add" costs one line; a missing body costs whoever runs `git blame` on
> this line in two years an hour of archaeology.

---

## 3. One Topic per Commit

A commit is a coherent, reviewable unit that leaves the tree working. `wip`, `fix tests`, `oops` and
`review fixes` are not commits — they are keystrokes. Squash them before pushing:

```bash
git rebase -i origin/develop
```

Fixing something in an earlier commit of your own branch:

```bash
git commit --fixup <sha>
git rebase -i --autosquash origin/develop
```

After any history rewrite on a branch you have already pushed:

```bash
git push --force-with-lease
```

> ⚠️ `--force-with-lease` refuses the push if someone else advanced the branch; plain `--force` silently
> discards their work. Never use plain `--force` on a shared branch.

---

## 4. Before You Push

```bash
pre-commit run --all-files
docker-compose -f local.yml run --rm app pytest
```

Both must be clean locally. CI runs the same commands with the same pinned versions — a failure there that
passes here means environment drift, not a flaky pipeline, and it is yours to resolve either way.

```bash
git push -u origin ABC-123
```

---

## 5. The Merge Request

**Title** — a short description of the change, readable in a history list:

```text
Add async report generation and API
```

Prefix with `Draft:` while the branch is still moving; that disables the merge button until you remove it.

**Description** — the ticket link, then what actually changed, as bullets:

```text
https://<tracker>/browse/ABC-123

- Add Report model with status lifecycle and progress tracking
- Add per-type builder registry so a new report needs no endpoint changes
- Publish progress over websockets, with a polling endpoint as fallback
- Cover builder failures with an error callback so jobs never hang in progress
```

Bullets describe **changes**, not files touched. A reviewer should be able to predict the diff from the
description; if they can't, the description is a table of contents rather than a summary.

**Settings on every MR:**

- **Assignee** — the person doing the first review, usually the project tech lead.
- **Squash commits when merge request is accepted** — enabled.
- **Delete source branch when merge request is accepted** — enabled.

Call out anything that needs action beyond merging: a migration to run, a new env var, a required service
restart, a fixture to load. Those belong in the description, not in a chat message that scrolls away.

---

## 6. Self-Review Before Requesting Review

Read your own diff on the MR page first. It is a different medium from the editor and shows things the
editor hides — debug prints, an unrelated formatting sweep, a file you never meant to stage.

Reviewers are looking for readability, alternatives and knowledge transfer — not bugs, and not lint. Clear
this list yourself so their round is spent on what only a human can see:

- [ ] The diff contains **only** this ticket. Unrelated cleanup goes in its own MR.
- [ ] No debug leftovers: prints, `ipdb`, `.only()` in tests, commented-out blocks.
- [ ] Names say what things are; no abbreviations, no `data2`.
- [ ] No single-responsibility, KISS or DRY violation you would flag in someone else's code.
- [ ] Queries reviewed for N+1 and race conditions.
- [ ] Endpoints authenticate and authorise as the spec says — including the deny path.
- [ ] Unhappy paths are handled and logged; exceptions caught are specific.
- [ ] Tests cover the interesting cases, not only the happy one.
- [ ] `README` / setup docs updated if the change affects how the project is run.
- [ ] No `TODO` left behind — resolve it or open a ticket.

---

## 7. Resolving Feedback

Review happens in rounds: you push, the reviewer comments, you respond. Keep each round cheap to re-read.

- Push fixes as ordinary commits during review — do **not** rewrite history mid-review, or reviewers lose
  the "changes since last round" view. Squashing happens on merge.
- Reply to every thread, then let the **reviewer** resolve it. Resolving your own thread silently closes a
  conversation the other person may not have finished.
- Disagreeing is fine — say why, and reach a decision in the thread rather than quietly not doing it.

---

## 8. Merging and Cleanup

Merge once approved and green: approvals are not a substitute for a passing pipeline, and a self-report
that "tests pass" is not a substitute for either.

Rebase onto the latest `develop` and resolve conflicts on your branch if others landed first — the MR
should merge cleanly, not force the reviewer to referee a conflict.

With squash-and-delete enabled, cleanup is automatic. Otherwise:

```bash
git push origin --delete ABC-123
git branch --delete ABC-123
```

---

## 9. What Never Gets Committed

| Never | Instead |
|---|---|
| `.env`, credentials, tokens, keys | placeholders in `envs.example/`, real values only locally |
| Local scheduler/state files (`celerybeat-schedule*`) | gitignored — they are runtime artefacts |
| Commented-out code | delete it; git remembers |
| Hand-edited migrations that are already applied | a new migration |
| An unrelated reformat bundled with a feature | its own MR |
| Generated files, `.pyc`, editor config | `.gitignore` |

If a secret was committed, rotating it is part of the fix — removing it from the history is not enough on
its own, because the value has already been distributed to everyone who fetched.

---

## 10. Checklist

- [ ] Branch cut from an up-to-date `develop`, named after the ticket.
- [ ] Rebased on `origin/develop`; no merge commits from `develop`.
- [ ] Commits squashed into coherent units, one topic each.
- [ ] Subjects are `ABC-123: Imperative summary`, ≤50 chars — or `feat:`/`fix:`/`chore:` when there is no ticket.
- [ ] Every commit has a body: the motivation, and how it differs from the previous implementation.
- [ ] `pre-commit` and the test suite pass locally.
- [ ] MR title readable in a list; description has the ticket link and bulleted changes.
- [ ] Squash and delete-source-branch both enabled; assignee set.
- [ ] Migration / env var / restart requirements called out in the description.
- [ ] Self-review done — the diff contains only this ticket.

## Navigation
- [Merge Request Review](../mr-review/SKILL.md) — reviewing someone else's diff
- [DRF Endpoints](../drf-endpoints/SKILL.md)
- [Django App Layout](../django-app-layout/SKILL.md)
- [Django Testing](../django-testing/SKILL.md)
