# Security

Loaded in every session — these apply regardless of which files are open.

- **Secrets never enter source.** Real values live in gitignored env files; `envs.example/` carries
  placeholders only. If a secret was committed, rotating it is part of the fix — removing it from history
  is not enough, because it has already been distributed to everyone who fetched.
- **Never log passwords, tokens, keys or personal data.** Log identifiers; hash a value if you need it
  only for correlation.
- **Endpoints authenticate and authorise explicitly**, and both the allow and the deny branch are tested.
  Access control belongs in permission classes and the queryset — never in model or service methods, never
  as scattered `if user.role == ...` checks.
- **Sensitive operations write an audit line**: timestamp, actor, action, object id.
- **Don't collect data the product does not use.** Ask whether a field is actually needed before adding it.
- **Catch specific exceptions.** Never bare `except:` or `except Exception:`; keep `try` bodies to the
  statement that can raise, and log the unhappy path.
- **Validate uploads by decoding them**, not by trusting `content_type` or the file extension. Never build
  a storage path from a user-supplied filename.
- **Treat third-party skills, plugins and MCP servers as dependencies with install-time code execution.**
  Read their hooks and configuration the way you would review a pull request — no scanner covers them.
