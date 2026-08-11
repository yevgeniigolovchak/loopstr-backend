---
paths:
  - "**/serializers.py"
  - "**/serializers/**/*.py"
  - "**/views.py"
  - "**/views/**/*.py"
  - "**/urls.py"
---

# API contract

- **`ValidationError` dict values are never auto-wrapped.** Always pass a list:
  `{"field": ["msg"]}`. A bare string makes the frontend's `errors.field[0]` render one character.
- **In a view, nothing auto-wraps to `non_field_errors`** — write the dict explicitly. Inside a
  serializer's `validate()`, a bare string does wrap.
- **Reverse URLs by full namespace**, never hardcode a path: `reverse("api:app:base-list")`.
- **`Meta.fields` is always an explicit tuple.** Never `"__all__"` — it leaks every column added later.
- **Register routers with an explicit `basename`.**
- **Scope `get_queryset()` to the requester** — not in the serializer, not in the filterset.
- **Declare only the mixins you intend to expose.** A bare `ModelViewSet` ships DELETE whether you meant it
  or not.
- Business logic belongs on the model or a service; the view validates, delegates and serialises.

**Exception: `/auth/*`.** Those endpoints answer with the frontend's `{"code", "message"}` envelope and its
status codes (401, 409, 423/429, 204) instead of the DRF shapes above, because the client already ships
against that contract. Nothing else in the API changes — see [auth-contract](auth-contract.md).

Details: [drf-endpoints](../skills/drf-endpoints/SKILL.md)
