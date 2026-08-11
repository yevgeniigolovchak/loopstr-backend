---
name: agent-configuration
description: Covers per-repository AI agent setup — choosing between CLAUDE.md, path-scoped rules, skills and hooks, writing and pruning a project CLAUDE.md, settings precedence, mandatory deny rules for secrets, vetting third-party skills and MCP servers, isolating parallel sessions in worktrees, and onboarding a repository. Use when setting up or fixing agent configuration, writing or trimming CLAUDE.md, adding permission rules or hooks, installing a third-party skill or plugin, or when the agent keeps ignoring an instruction.
paths:
  - "**/CLAUDE.md"
  - "**/CLAUDE.local.md"
  - "**/.claude/**"
---

# Agent Configuration

Configuring a repository for agent work is four decisions: what the agent should always know, what it
should know only sometimes, what it must be prevented from doing, and what must happen regardless of what
it decides. Each has its own mechanism, and using the wrong one is why instructions get ignored.

## Quick Reference

| If you're about to... | Watch out for... | § |
|---|---|---|
| Write down a convention | Pick the right mechanism — always-on context is the most expensive one | 1 |
| Add to `CLAUDE.md` | Target is **under 200 lines**; longer files reduce adherence | 2 |
| Document one subsystem | Scope it with a path rule instead of loading it every session | 3 |
| Split a long `CLAUDE.md` | `@imports` organise, they do **not** save context — everything still loads | 2 |
| Commit permissions | `deny` for `.env` and secrets is not optional | 5 |
| Rely on an instruction | `CLAUDE.md` is context, not enforcement — if it must happen, use a hook | 6 |
| Store a personal preference | Local settings, not the committed file | 4 |
| Install a third-party skill, plugin or MCP server | It is a dependency that runs code — review it like an MR | 7 |
| Run two sessions on one repository | Give each its own worktree, project name and ports | 8 |
| Debug "it ignored my rule" | Check the file actually loaded before rewriting it | 10 |

---

## 1. Four Mechanisms, Four Jobs

| Mechanism | Loads | Use for |
|---|---|---|
| `CLAUDE.md` | every session, in full | facts true for all work: commands, layout, conventions, non-obvious gotchas |
| `.claude/rules/*.md` | every session, or only for matching files when scoped with `paths` | conventions for one subsystem or file type |
| Skills | only when relevant or invoked | procedures and reference material — a checklist, a multi-step workflow |
| Hooks + `permissions` | enforced by the client, always | things that must happen or must never happen, regardless of what the agent decides |

The deciding question is **cost versus certainty**. `CLAUDE.md` costs context in every session and buys
influence, not guarantees. Hooks and deny rules cost nothing per session and are absolute.

> ⚠️ A section of `CLAUDE.md` that has grown into a *procedure* belongs in a skill. A rule that only
> matters for one directory belongs in a path-scoped rule. Leaving both in `CLAUDE.md` is how it grows past
> the point where any of it is followed reliably.

---

## 2. Project `CLAUDE.md`

Lives at `./CLAUDE.md` or `./.claude/CLAUDE.md`, committed and shared with the team.

**Target under 200 lines.** It loads in full at the start of every session, so every line competes with the
actual task. Longer files measurably reduce how consistently instructions are followed.

Write what a capable new teammate could not infer from the code in an hour:

```markdown
# Project: <Name>

## Stack
Django + DRF, Postgres, Celery (worker + beat). Local dev runs entirely in Docker via `local.yml`.
Local apps import by bare module name — `from users.models import User`.

## Commands
- Up: `docker-compose -f local.yml up -d`
- Test: `docker-compose -f local.yml run --rm app pytest`
- Lint: `pre-commit run --all-files`

## Conventions
- Business logic on models and services; views stay thin.
- `ValidationError` values must be lists: `{"field": ["msg"]}`.
- URLs are reversed by full namespace, never hardcoded.

## Non-obvious rules
- The Celery worker registers tasks at boot — restart it after adding a task module.
- `develop.yml` is staging-flavoured; never use it for local development.
```

**Belongs in `CLAUDE.md`:** build and test commands, the import convention, architectural decisions that
look arbitrary from inside a single file, traps that fail silently.

**Does not belong:** anything derivable from the code (directory listings, dependency lists, model
inventories), personal preferences, procedures better served by a skill, and anything time-sensitive.

Add an entry when the agent makes the same mistake twice, or when you type the same correction you typed
last session. Remove entries that contradict each other — given two conflicting rules, one gets picked
arbitrarily.

**Prune deliberately** — nothing removes a line but you, so the file only ever grows. Re-read it whenever it
passes the limit or the project changes shape, and delete:

- entries describing code that no longer exists, or a workaround for a bug that was fixed;
- anything now enforced by tooling — a linter rule, a hook, a deny rule;
- anything that turned out to be derivable from the code after all;
- what a path-scoped rule or a skill now says, once you have moved it there;
- instructions you cannot recall the agent ever needing.

A stale line is worse than a missing one: it is followed with exactly the confidence of a correct one.

> ⚠️ `@path` imports organise a long file but **do not reduce context** — imported files are expanded and
> loaded at launch just the same. Only path-scoped rules and skills actually defer loading.

Subdirectory `CLAUDE.md` files load on demand when the agent reads files in that directory — a good place
for context that only matters inside one app.

---

## 3. Path-Scoped Rules

`.claude/rules/*.md` holds modular instructions. With a `paths` frontmatter field, a rule loads only when
the agent works with matching files:

```markdown
---
paths:
  - "*/apps/*/migrations/*.py"
---

# Migration rules

- Data migrations use `apps.get_model()`, never a direct model import.
- Every `RunPython` needs a reverse function or an explicit `noop`.
- Never edit a migration that has been applied outside your own machine.
```

```text
.claude/
├── CLAUDE.md
└── rules/
    ├── testing.md          # paths: "**/tests/**"
    ├── migrations.md       # paths: "**/migrations/*.py"
    └── security.md         # no paths — loads every session
```

A rule without `paths` loads unconditionally, at the same priority as `CLAUDE.md` — so use `paths`
deliberately, or you have simply moved the size problem to another file.

Glob patterns match the same way everywhere: `**/*.py`, `src/**/*`, `**/*.{ts,tsx}`. Use forward slashes.

---

## 4. Settings Files and Precedence

| Scope | Path | Committed |
|---|---|---|
| Managed policy | system location, deployed by IT | n/a — cannot be overridden |
| Local | `.claude/settings.local.json` | **no** — gitignored |
| Project | `.claude/settings.json` | **yes** — shared with the team |
| User | `~/.claude/settings.json` | no — applies to all your projects |

Higher scopes win for ordinary keys — **but permission rules merge across scopes rather than override**.
A team `deny` cannot be lifted by a personal `allow`.

Put in the **committed** `.claude/settings.json` what the whole team needs: deny rules, allow rules for the
project's routine commands. Put in **local** settings anything personal — your MCP servers, your model
preference, exclusions relevant only to your machine.

---

## 5. Permissions: Deny First

```json
{
  "permissions": {
    "deny": [
      "Read(./.env)",
      "Read(./.env.*)",
      "Read(./**/secrets/**)",
      "Read(./docker/**/.env)"
    ],
    "allow": [
      "Bash(docker-compose -f local.yml run --rm app pytest*)",
      "Bash(pre-commit run *)",
      "Bash(git status)",
      "Bash(git diff *)"
    ]
  }
}
```

**Deny rules for secrets are mandatory, not a nicety.** Env files in this stack hold database credentials,
storage keys and third-party tokens; a file the agent cannot read is a file that cannot reach a transcript.
Deny the committed `envs.example/` placeholders too if they ever get filled in locally.

**Allow rules exist to remove friction, not to widen reach.** Good candidates are read-only and idempotent:
the test command, the linter, `git status`, `git diff`. Keep destructive and outbound operations out —
migrations against a real database, `git push`, `curl`, anything that deletes.

> ⚠️ A deny rule is enforced by the client regardless of what the agent decides. An instruction in
> `CLAUDE.md` saying "never read .env" is a request. For anything that actually matters, use the rule.

---

## 6. Hooks: When Context Is Not Enough

`CLAUDE.md` shapes behaviour; hooks execute at fixed lifecycle points and apply regardless of what the
agent chose to do. Reach for a hook when an instruction must hold every time — formatting after each edit,
a check before every commit, blocking a command shape outright.

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "${CLAUDE_PROJECT_DIR}/.claude/hooks/block-prod-migrate.sh",
            "if": "Bash(*manage.py migrate*)"
          }
        ]
      }
    ]
  }
}
```

A `PreToolUse` hook blocks by exiting with code `2` (stderr becomes the reason), or by printing a decision:

```bash
jq -n '{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": "Run migrations yourself against this database."
  }
}'
```

Useful events for this stack: `PreToolUse` (block or gate a command), `PostToolUse` (run the formatter on
what was just edited), `Stop` (run the test suite before the turn ends).

Keep hooks fast and quiet. A hook that runs the whole suite on every file edit makes the agent slower than
doing the work by hand.

---

## 7. Third-Party Skills, Plugins and MCP Servers

Installing one is taking on a dependency that executes code: hooks run commands without a prompt, an MCP
server is a process on your machine holding your credentials, and a third-party skill's text enters the
same context as your own instructions. No scanner in the ecosystem checks any of it.

Review before installing, the way you would review a merge request:

- **Read the hooks first.** A `PostToolUse` hook is an arbitrary command run after every edit you make.
- **Read the skill bodies.** Instructions telling the agent to fetch a URL, send a file somewhere, or
  disregard earlier instructions are prompt injection, not configuration.
- **Check what an MCP server connects to, and with which token.** One holding a write-scoped API key acts
  as you, in your name, with no second pair of eyes.
- **Pin the version.** A package that auto-updates is an unreviewed change entering every future session.
- **Prefer vendoring what you actually use** — copy the skill into `.claude/skills/` and commit it. Then it
  goes through review like the rest of the repository and cannot change underneath you.

Give every integration the narrowest credential that lets it work: a read-only token wherever reading is
all it does.

---

## 8. Isolating Parallel Work

Two sessions sharing one checkout collide: one rebases while the other is mid-edit, a test run picks up
half of an unrelated change. `git worktree` gives each its own directory and branch against the same
repository and the same object store:

```bash
git worktree add ../repo-ABC-123 -b ABC-123 origin/develop
git worktree list
git worktree remove ../repo-ABC-123          # once the branch is merged
```

Each worktree needs its own environment. Copy the env files across, and give the stack a distinct project
name so containers and volumes do not collide:

```bash
docker-compose -p abc-123 -f local.yml up -d
```

Two stacks cannot bind the same host ports — stop one, or override the mapping. Committed configuration
travels with the checkout; `.claude/settings.local.json` and `CLAUDE.local.md` do not, so copy them if you
depend on them.

Worth the setup when a long task runs unattended and you want to keep working meanwhile, or when comparing
two approaches to the same ticket. Not worth it for something you will finish in one sitting.

---

## 9. What Never Goes in Committed Config

| Never | Instead |
|---|---|
| Secrets or tokens in any settings file | environment variables; deny reading the files that hold them |
| Personal MCP servers, model choice, editor mode | `.claude/settings.local.json` or user settings |
| `allow` rules for destructive commands | leave them prompting |
| A `CLAUDE.md` restating what the code already says | delete it — it costs context every session |

Add `.claude/settings.local.json` and `CLAUDE.local.md` to `.gitignore`. Commit `.claude/settings.json`,
`.claude/rules/` and `.claude/skills/` — they are team configuration and belong in review like any code.

---

## 10. When an Instruction Is Ignored

Diagnose in this order, before rewriting anything:

1. **Did the file load?** `/context` lists the memory files actually in the session. A file that is not
   there cannot be followed — usually it is in the wrong location or a subdirectory that was never read.
2. **Is it specific enough?** "Use 2-space indentation" is followed; "format code properly" is not.
   Instructions that can be verified are instructions that get applied.
3. **Does something contradict it?** Check ancestor `CLAUDE.md` files, `.claude/rules/`, and user-level
   config. Given two conflicting rules, one is picked arbitrarily.
4. **Must it hold every time?** Then it was never a `CLAUDE.md` job. Move it to a hook or a deny rule.

`/status` shows which settings sources loaded. `/memory` opens the memory files. `/doctor` reports config
problems, including entries stripped from managed settings.

---

## 11. Onboarding a Repository

- [ ] `CLAUDE.md` exists, under 200 lines, and states stack, commands, conventions and non-obvious traps.
- [ ] `.claude/settings.json` committed with `deny` rules for `.env`, env directories and secrets.
- [ ] `allow` rules cover the routine read-only commands (tests, linter, `git status`).
- [ ] `.claude/settings.local.json` and `CLAUDE.local.md` are gitignored.
- [ ] Subsystem-specific conventions live in path-scoped rules, not in `CLAUDE.md`.
- [ ] Repeatable procedures live in skills, not in `CLAUDE.md`.
- [ ] Hooks configured for anything that must happen every time.
- [ ] `/context` confirms the intended files load in a fresh session.
- [ ] Third-party skills, plugins and MCP servers reviewed and pinned before use.

---

## 12. Checklist

- [ ] The right mechanism for each instruction: always-on, scoped, on-demand, or enforced.
- [ ] `CLAUDE.md` under 200 lines, with nothing derivable from the code.
- [ ] Pruned when last read — no entries for code, bugs or tooling that have moved on.
- [ ] No contradictions between `CLAUDE.md`, rules and user config.
- [ ] Secrets denied by rule, not by request.
- [ ] Allow rules are read-only and idempotent.
- [ ] Personal configuration kept out of committed files.
- [ ] Config changes reviewed in the MR like code.

## Navigation
- [DRF Endpoints](../drf-endpoints/SKILL.md)
- [Django App Layout](../django-app-layout/SKILL.md)
- [Database Migrations](../db-migrations/SKILL.md)
- [Git Workflow & MR](../git-workflow-mr/SKILL.md)
