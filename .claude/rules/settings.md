---
paths:
  - "**/settings.py"
  - "**/envs.example/**"
---

# Settings

- **Cast every variable with `env.*`**, and use `env.bool()` for anything on/off — a string `"False"` is
  truthy, so a flag read as a string is permanently on.
- **Defaults live in the `environ.Env(...)` schema**, never at the call site. `env.bool("DJANGO_DEBUG")`
  looks required but is defaulted in the constructor; check there before concluding a variable is mandatory.
- **A credential defaulted to `""` does not fail closed** — it fails later, as a permission or connectivity
  error. Where the credential is guarded by a feature flag, validate it inside that flag's branch and raise
  `ImproperlyConfigured` naming both variables.
- **Prefix by consumer** (`DJANGO_`, `DRF_`, `POSTGRES_`): the variable name is not the setting name. A
  third-party package keeps the name it documents — an alias only guarantees a silent mismatch with deploy.
- **The placeholder file gets the key in the same commit**, in the file for the service that consumes it,
  with an obviously fake value.
- **Nothing loads a `.env`** — Compose injects it, so a new variable needs the container restarted, and
  adding `read_env()` creates a second source of truth that disagrees in production.
- **A new required variable is a deploy-coordination item**: name the environments that need it in the MR.

Details: [settings-secrets](../skills/settings-secrets/SKILL.md)
