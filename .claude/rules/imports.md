---
paths:
  - "**/apps/**/*.py"
---

# Imports

- Local apps import by **bare module name** — `from users.models import User`. The apps directory is on
  `sys.path`; a dotted project path does not resolve.
- Four import groups separated by blank lines: stdlib → Django → third-party → local.
- Absolute imports only. Never `import *`.
- `isort --profile=black` runs in pre-commit — let the hook order them rather than hand-arranging.

Older repositories that predate the path append import by full dotted path from a flat layout. Match the
file you are editing so the module resolves, but write new apps the standard way.
