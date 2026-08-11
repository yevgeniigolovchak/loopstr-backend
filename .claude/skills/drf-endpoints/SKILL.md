---
name: drf-endpoints
description: Covers DRF endpoint conventions — router wiring, viewset anatomy, per-action serializers, validation-error shapes, per-field filters, three-layer RBAC and drf-yasg schemas. Use when adding or changing an API endpoint, viewset, serializer, filterset or permission class.
paths:
  - "**/views.py"
  - "**/views/**/*.py"
  - "**/serializers.py"
  - "**/serializers/**/*.py"
  - "**/urls.py"
  - "**/filters.py"
  - "**/permissions.py"
  - "**/api_schema*.py"
---

# DRF Endpoints

An endpoint is a `GenericViewSet`/`ModelViewSet` registered on a `SimpleRouter`, a `ModelSerializer` per
action, business logic behind the Service Pair Pattern, `django-filter` for query params, and `drf-yasg`
for docs. An endpoint that follows this shape needs no explanation in review.

## Quick Reference

| If you're about to... | Watch out for... | § |
|---|---|---|
| Import a local app | Bare module names only — `from users.models import ...` | 2 |
| Reverse a URL | Full namespace: `reverse("api:users:auth:login")` | 3 |
| Put logic in a view | Views are adapters — model method or service, never the view | 1 |
| Switch serializer by action | A typo in the dict key silently falls back to the default | 5 |
| Raise `ValidationError` | Dict values are **not** auto-wrapped — pass `{"field": ["msg"]}` | 6 |
| Add a filter | One self-contained `filter_<name>` per param, `Meta.fields = ()` | 7 |
| Return a list from an `@action` | Hand-rolled list responses lose pagination | 8 |
| Fetch an object inside a custom action | `has_object_permission` never fires without `check_object_permissions` | 9 |
| Add an ID-on-write / object-on-read field | drf-yasg can't express it — needs `<Name>ReadSerializer` | 10 |

---

## 1. Where Logic Goes: the Service Pair Pattern

Thin views, fat models — with two named homes for logic and nothing in between:

| Layer | Owns | Example |
|---|---|---|
| **Model method / manager** | internal state transitions, atomic data integrity, queryset shaping | `project.close()`, `Complaint.objects.with_status()` |
| **Service** (`<app>/services.py`) | orchestration across models, Celery dispatch, external APIs | `notify_user()`, `build_layer_options()` |
| **View** | HTTP only: validate input → call model/service → serialize output | — |

Services are plain functions or classes, matching whatever the app already uses. Anything a view computes
about domain objects is logic that escaped one of the two layers above.

> ⚠️ Do **not** import a foreign architecture on top of this. No `selectors.py` read-layer, no `APIView`
> as the default view class, no plain `serializers.Serializer` replacing `ModelSerializer`, no nested
> `InputSerializer`/`OutputSerializer`. Those belong to a different styleguide and will contradict every
> neighbouring file.

---

## 2. Imports Are Bare Module Names

`config/settings.py` appends `<project_name>/apps` to `sys.path`, so local apps import by bare module name:

✅ **Correct:**
```python
from users.models import User
from common.permissions import RoleBasedPermission
```

❌ **Incorrect:**
```python
from myproject.apps.users.models import User
```

> ⚠️ Some older repositories predate the path append and import by full dotted path from a flat
> `<project_name>/<app>/` layout. That is legacy debt, not a second valid style. Match the file you are
> editing so the module actually resolves, but write new apps the standard way and raise the conversion as
> its own ticket.

Import order: four blank-line-separated groups — stdlib → Django → third-party → local. Absolute imports
only, never `import *`. `isort --profile=black` runs in pre-commit; let the hook order them.

---

## 3. URL Wiring

The app owns a `SimpleRouter`; mounting is the root URLconf's job. Root APIs mount under `/api/v1/` with
the `api` namespace, and each app is included with its own sub-namespace.

✅ **Recommended (`<app>/urls.py`):**
```python
from complaints.views.organisation import ComplaintTypeViewSet, OrganisationComplaintViewSet
from rest_framework.routers import SimpleRouter

router = SimpleRouter()
router.register("complaints", OrganisationComplaintViewSet, basename="complaints")
router.register("complaints-type", ComplaintTypeViewSet, basename="complaints-type")

urlpatterns = router.urls
```

One line in `config/urls.py`, inside the `api/v1/` include:
```python
path("", include(("complaints.urls", "complaints"))),
```

`basename` is mandatory when the viewset has no `queryset` attribute, and it decides the reverse name.
**Always reverse by name — never hardcode a URL string in tests or code:**

```python
reverse("api:complaints:complaints-list")
reverse("api:complaints:complaints-detail", args=(complaint.pk,))
reverse("api:users:auth:login")                                    # nested sub-namespace
```

> ⚠️ A wrong namespace raises `NoReverseMatch` at call time — inside the test, not at import. Copy the
> namespace from the `include()` tuple rather than guessing it from the app name. Legacy repositories may
> mount per-app prefixes with no `api` umbrella; there the reverse is `app:base-list`.

---

## 4. ViewSet Anatomy

Declare the mixins you actually expose. A bare `ModelViewSet` on a resource that must never be deleted
through the API is a silent bug — DELETE ships enabled and nobody notices until data is gone.

✅ **Recommended:**
```python
class OrganisationComplaintViewSet(
    PermissionsViewSetMixin,
    ListModelMixin,
    RetrieveModelMixin,
    CreateModelMixin,
    GenericViewSet,
):
    permission_classes = (IsAuthenticated, RoleBasedPermission)
    allowed_roles = [User.ROLES.ADMIN, User.ROLES.MANAGER]
    filter_backends = (DjangoFilterBackend, SearchFilter, CustomOrderingFilter)
    filterset_class = ComplaintFilter
    search_fields = ("subject", "complainant_name")
    ordering_fields = ("created", "status")

    def get_queryset(self):
        return (
            Complaint.objects.select_related("complaint_type", "location")
            .prefetch_related("documents")
            .filter(organisation=self.request.user.organisation)
        )
```

- **Scope the queryset to the requester inside `get_queryset()`** — not in the serializer, not in the
  filterset. It is the one hook that runs for list *and* detail, so object-level leaks can't slip past it.
- **Kill N+1 when you write the serializer**, not after the slow-list ticket: `select_related` for forward
  FK/O2O, `prefetch_related` for reverse FK and M2M. Every nested serializer field is a join you owe.
- **Body-less checks belong in the view.** State guards for DELETE or no-payload POST actions go in
  `perform_destroy` / `perform_update` / the action method — never in a serializer invented to hold them.
- **Custom actions** use `@action(detail=..., methods=[...], url_path="...")`; `url_path` becomes the
  reverse suffix.

---

## 5. Serializers

`ModelSerializer` with an explicit `Meta.fields` tuple, one serializer per action.

❌ **Anti-pattern:**
```python
class ComplaintSerializer(serializers.ModelSerializer):
    class Meta:
        model = Complaint
        fields = "__all__"
```
**Why?** Every column added later leaks into the API — including internal flags and soft-delete
bookkeeping. The response contract must be a decision, not a side effect of a migration.

✅ **Recommended:**
```python
class ComplaintListSerializer(serializers.ModelSerializer):
    complaint_type_name = serializers.CharField(source="complaint_type.name", read_only=True)
    days_open = serializers.SerializerMethodField()

    class Meta:
        model = Complaint
        fields = ("id", "subject", "status", "complaint_type_name", "days_open", "created")

    def get_days_open(self, obj):
        return (timezone.now().date() - obj.created.date()).days
```

`source="fk.field"` follows a relation with no method needed. Reserve `SerializerMethodField` for computed
values — it is invisible to `select_related`, so the queryset must already carry what it reads.

**Per-action switching:**
```python
SERIALIZERS = {
    "list": ComplaintListSerializer,
    "retrieve": ComplaintDetailSerializer,
    "create": ComplaintCreateSerializer,
}

def get_serializer_class(self):
    return self.SERIALIZERS.get(self.action, ComplaintDetailSerializer)
```

> ⚠️ **The dict key must equal the action name character for character.** A typo does not raise — it falls
> back to the default serializer, and the endpoint quietly stops doing its job. A mistyped key here is how
> a password-reset endpoint turns into a silent no-op. Copy-paste the action name; don't retype it.

Cross-field validation goes in `validate()`, single-field in `validate_<field>()` — never in the view.
Serializers validate; they do not orchestrate side effects (that's a service, §1).

---

## 6. Validation Errors — Two Patterns, Two Gotchas

Use `serializers.ValidationError` exclusively, in serializers *and* views.

**Field-level:**
```python
raise serializers.ValidationError({"occurrence_date": ["Cannot be in the future."]})
# → {"occurrence_date": ["Cannot be in the future."]}
```

> ⚠️ **Dict values are not auto-wrapped into lists.** `{"field": "msg"}` returns the bare string, so the
> frontend's `errors.field[0]` renders `"m"`. Always pass a list explicitly.

**Non-field:**
```python
# inside serializer.validate() — DRF wraps it for you
raise serializers.ValidationError("Products must share one category.")
# → {"non_field_errors": ["Products must share one category."]}

# inside a view — NO wrapping happens; a bare string yields ["..."] with no key
raise serializers.ValidationError({"non_field_errors": ["Project is closed."]})
```

Wrap user-facing messages in `gettext_lazy as _` when the repository has a `locale/` directory.

---

## 7. Filtering: One Self-Contained `filter_<name>` per Field

Declare every query param as its own filter with its own method. Don't accumulate a shared `Q` object and
don't override `qs` with `_noop` placeholders — per-field methods stay readable and independently testable.

✅ **Recommended:**
```python
class ComplaintFilter(MultiValueQueryParamMixin, FilterSet):
    status = CharFilter(method="filter_by_status")
    complaint_type = CharFilter(method="filter_by_complaint_type")
    submitted_at_from = DateFilter(field_name="created", lookup_expr="date__gte")
    submitted_at_to = DateFilter(field_name="created", lookup_expr="date__lte")

    class Meta:
        model = Complaint
        fields = ()

    def filter_by_status(self, queryset, name, value):
        statuses = self.get_multi_values("status", value)
        return queryset.filter(status__in=statuses) if statuses else queryset

    def filter_by_complaint_type(self, queryset, name, value):
        types = self.get_multi_values("complaint_type", value)
        return queryset.filter(complaint_type_id__in=types) if types else queryset
```

`Meta.fields = ()` is intentional: declared filters are the whole contract, nothing is auto-generated from
the model. For comma-separated or repeated params, reuse the repository's multi-value mixin instead of
splitting strings by hand. Ordering goes through the project's ordering filter when one exists — the
aliasing variant lets the FE keep a stable key while the DB column is renamed underneath.

---

## 8. Pagination

Never return an unbounded queryset. `DEFAULT_PAGINATION_CLASS` is set globally, so `ListModelMixin` is
already paginated — but a hand-rolled list response opts out of it silently.

❌ **Anti-pattern:**
```python
@action(detail=False, methods=["get"])
def summary(self, request):
    return Response(SummarySerializer(self.get_queryset(), many=True).data)
```

✅ **Recommended:**
```python
@action(detail=False, methods=["get"])
def summary(self, request):
    page = self.paginate_queryset(self.get_queryset())
    serializer = SummarySerializer(page, many=True)
    return self.get_paginated_response(serializer.data)
```

---

## 9. RBAC: Three Layers

Enforce access control at three layers, whatever role set the domain uses. Superuser bypasses all of them.

| Layer | How | Effect |
|---|---|---|
| View-level | `RoleBasedPermission` in `permission_classes` + `allowed_roles` allow-list | 403 for roles outside the list |
| Object-level | `has_object_permission` on a `BasePermission` subclass | 403 on a specific row |
| Field-level, on write | permission-aware serializer driven by a central permissions map | field flipped `read_only` — writes silently dropped, **no 400** |
| Required-when-writable | required-field permission map | a field is required only for roles allowed to write it |

Access control lives in permission classes and the queryset — never inside model or service methods, and
never scattered as ad-hoc `if user.role == ...` checks across views.

> ⚠️ `has_permission` runs before `get_object()`; `has_object_permission` runs after — and **only** if you
> went through `get_object()`. A custom action that fetches a row itself must call
> `self.check_object_permissions(request, obj)`, or the object-level check never fires.

> ⚠️ The field layer fails *silently by design*. When someone reports "my PATCH did nothing", check the
> permissions map before debugging the view.

Auth and RBAC endpoints need explicit tests for **both** the allow and the deny branch — line coverage
alone does not prove a role is actually blocked.

---

## 10. drf-yasg: The write-int / read-nested Asymmetry

OpenAPI 2.0 cannot express `writeOnly`, so one field carries one schema for both directions. For fields
that accept IDs on write but return nested objects on read:

1. **Write** — declare on the base serializer:
   `images = PrimaryKeyRelatedField(many=True, write_only=True, queryset=...)`
2. **Read** — inject the nested payload at runtime in `to_representation()`.
3. **Docs** — add a `<Name>ReadSerializer` subclass overriding the field with a nested read-only serializer,
   applied as `@swagger_auto_schema(responses={200: <Name>ReadSerializer()})`.
4. Use it **only** in `responses=` — runtime serialisation still goes through the base class.
5. Apply the decorator to **every** action returning the resource (`retrieve`, `update`, `partial_update`,
   and both `method="get"` and `method="post"` on multi-method `@action`s).

Field-level `swagger_schema_fields` tricks are not enough — they cannot split request from response.

For multipart uploads, declare form fields via `manual_parameters` and set
`parser_classes = (MultiPartParser, FormParser)` — drf-yasg refuses to attach form parameters while a JSON
parser is also available.

---

## 11. Checklist Before Opening the MR

- [ ] Logic sits on a model method or a service — the view only adapts HTTP.
- [ ] Router registered with `basename`; app included in `config/urls.py` under its namespace.
- [ ] `get_queryset()` scopes by requester and carries `select_related` / `prefetch_related`.
- [ ] Only the mixins you intend to expose — no accidental `destroy`.
- [ ] Serializer keys in `get_serializer_class()` match action names exactly.
- [ ] `Meta.fields` explicit; no `"__all__"`.
- [ ] Errors are `{"field": ["msg"]}` — lists, not bare strings.
- [ ] Every hand-rolled list response is paginated.
- [ ] `@swagger_auto_schema` on each action whose response shape differs from its request.
- [ ] Tests reverse URLs by namespace and cover **both** the allow and the deny branch.
- [ ] `pre-commit run --all-files` clean; CI runs the identical commands.

## Navigation
- [Django App Layout](../django-app-layout/SKILL.md)
- [Django Testing](../django-testing/SKILL.md)
- [Files & Uploads](../files-uploads/SKILL.md)
- [Celery Tasks](../celery-tasks/SKILL.md)
- [Git Workflow & MR](../git-workflow-mr/SKILL.md)
