---
name: files-uploads
description: Covers file and image handling — storage backends, generated upload paths, thumbnails and EXIF, storage cleanup on every delete path including cascades, settings-driven limits, orphan sweeps and multipart schemas. Use when adding uploads, serving files, or working with images, documents or storage.
paths:
  - "**/files/**/*.py"
  - "**/storages.py"
  - "**/processors.py"
---

# Files & Uploads

Uploads span three systems that fail independently: the database row, the stored object, and the generated
thumbnail. Most bugs here are not crashes — they are rows without files, files without rows, and storage
that grows forever.

## Quick Reference

| If you're about to... | Watch out for... | § |
|---|---|---|
| Name an uploaded file | Never build a path from the user's filename | 2 |
| Add a file-bearing model | Storage cleanup needs **three** hooks, not one — cascades bypass `delete()` | 4 |
| Add a size or type limit | It belongs in settings, not hardcoded in a serializer | 5 |
| Trust an uploaded file's type | `content_type` is client-supplied; extension is part of a string | 5 |
| Accept uploads before the parent exists | Unbound rows need a TTL sweep or they accumulate forever | 6 |
| Document a multipart endpoint | `manual_parameters` + `parser_classes`, or the form fields vanish | 7 |
| Change thumbnail dimensions | Existing thumbnails are stale until regenerated | 3 |
| Test an upload | Storage is redirected to a tmpdir — never hit a real bucket | 8 |

---

## 1. Storage Backends

Three backends selected by environment flags: local filesystem for development, and a cloud object store
otherwise. Code never chooses — it uses `default_storage` and the configured `STORAGES` entry.

```python
from django.core.files.storage import default_storage

default_storage.delete(name)
```

❌ **Never** import a specific backend or build a URL by string concatenation in application code. The
same code must work against all three, and `MEDIA_URL` differs per backend.

> ⚠️ With a remote backend enabled, container startup runs `collectstatic` against the bucket. Stale
> credentials or a blocked network show up as a timeout in the logs while the app still comes up — so an
> apparently healthy container may have skipped static collection. Switching to local storage removes the
> round trip entirely during development.

---

## 2. Upload Paths

The stored name is generated; the user's filename is data, not a path.

✅ **Recommended:**
```python
def get_file_upload_path(instance, filename):
    _, ext = os.path.splitext(filename)

    return "{}/{}/{}{}".format(
        instance.upload_prefix,
        timezone.now().strftime("%y/%m"),
        uuid.uuid4().hex,
        ext.lower(),
    )
```

**Why each part:** the prefix keeps model families apart; the date segment stops one directory growing to
millions of entries; the UUID removes collisions and makes the stored name unguessable; the lowercased
extension keeps the object servable.

> ⚠️ A user-supplied filename used as a path is a directory-traversal bug (`../../`) and a collision risk.
> Keep the original name in its own column for display and downloads:
> ```python
> def save(self, *args, **kwargs):
>     if self._state.adding and self.file and not self.original_name:
>         self.original_name = os.path.basename(self.file.name)[:255]
>     super().save(*args, **kwargs)
> ```
> Capture it **before** `super().save()` — the upload path callable renames the file during that call.

---

## 3. Images and Thumbnails

Thumbnails are declared on the model as a spec field and generated from the source image, never uploaded
separately.

```python
class ProductImage(File):
    file = models.ImageField(upload_to=get_file_upload_path)
    thumbnail = ImageSpecField(
        source="file",
        processors=[EXIFOrientation(), ResizeToFit(*settings.FILES_IMAGE_THUMB_SIZE)],
        format=settings.FILES_IMAGE_EXTENSION,
        options={"quality": settings.FILES_IMAGE_THUMB_QUALITY},
    )
```

- **Correct EXIF orientation before resizing.** Processing strips EXIF, so a photo that displayed upright
  from a phone comes out rotated unless the rotation is baked in first.
- **Sizes and quality come from settings**, so every image in the project shares one definition.
- **Formats needing a decoder plugin** (HEIC being the common one) must be registered in `AppConfig.ready()`,
  before any thumbnail is generated:
  ```python
  def ready(self):
      from pillow_heif import register_heif_opener

      register_heif_opener()
      from files import signals  # noqa: F401
  ```

> ⚠️ Spec fields are generated lazily and cached. Changing dimensions or quality does **not** touch
> existing thumbnails — regenerate them explicitly:
> ```bash
> docker-compose -f local.yml exec app python manage.py generateimages
> ```

---

## 4. Cleanup: Three Hooks, Not One

Deleting a row does not delete its object from storage. Django offers no single hook that covers every
path, so file-bearing models need all three:

| Path | Covered by |
|---|---|
| `instance.delete()` | model `delete()` override |
| `queryset.delete()` | custom `QuerySet.delete()` — it does **not** call the model's `delete()` |
| Cascade (parent row removed, bulk parent delete) | `post_delete` receiver |

```python
class FileQuerySet(models.QuerySet):
    def delete(self):
        for obj in self.iterator():
            if obj.file.name:
                default_storage.delete(obj.file.name)
        return super().delete()


class File(TimeStampedModel):
    file = models.FileField(upload_to=get_file_upload_path)

    objects = FileQuerySet.as_manager()

    class Meta:
        abstract = True

    def delete(self, using=None, keep_parents=False):
        if self.file.name:
            default_storage.delete(self.file.name)
        return super().delete(using, keep_parents)
```

```python
@receiver(post_delete, sender=ProductImage)
@receiver(post_delete, sender=TestImage)
def delete_image_storage(sender, instance, **kwargs):
    """Remove file and thumbnail from storage whichever way the row disappeared."""
    for name in (instance.thumbnail.name, instance.file.name):
        if name:
            default_storage.delete(name)
```

> ⚠️ **The cascade path is the one that leaks.** Deleting a parent removes children at the database level
> without ever instantiating them, so neither override runs. That is the entire reason the `post_delete`
> net exists — and why it must be idempotent: deleting an already-removed object is a harmless no-op, and
> it will happen on the direct paths.

**Delete the thumbnail too.** It is a separate stored object and survives the source image otherwise.

Register receivers in `signals.py`, imported from `AppConfig.ready()` — an unimported receiver module
never connects and the leak is silent.

---

## 5. Validation

Limits live in settings, so one change applies everywhere:

```python
FILES_IMAGE_MAX_SIZE = 15 * 1024 * 1024
FILES_IMAGE_ALLOWED_EXTENSIONS = ["jpg", "jpeg", "png", "heic", "tif", "tiff"]
FILES_DOCUMENT_MAX_SIZE = 10 * 1024 * 1024
FILES_DOCUMENT_ALLOWED_EXTENSIONS = ["pdf"]
```

Read them in the serializer — never hardcode a number next to the field:

```python
max_size = settings.FILES_IMAGE_MAX_SIZE
allowed_ext = settings.FILES_IMAGE_ALLOWED_EXTENSIONS
```

Validate, in order: **extension** (lowercased, from the actual filename), **size**, then **content** —
opening an image with Pillow, or parsing the document, proves it is what it claims.

> ⚠️ `uploaded_file.content_type` comes from the client and is trivially forged; the extension is just the
> tail of a string. Neither proves anything about the bytes. For anything rendered back to users or parsed
> server-side, the decode is the real check.

Report per-file errors keyed by the field they arrived under, with list values, so the frontend can mark
the right input:

```python
errors[category] = ["File exceeds the maximum size."]
```

---

## 6. Upload-First Flows

When files are uploaded before the object they belong to exists, the upload endpoint creates rows with a
null parent, and a later save binds them. That leaves orphans whenever the user abandons the form.

```python
@app.task
def delete_unbound_product_images():
    """Drop product images uploaded but never bound to a product."""
    days = settings.FILES_IMAGE_UNBOUND_TTL_DAYS
    cutoff = timezone.now() - timedelta(days=days)
    qs = ProductImage.objects.filter(product__isnull=True, created__lt=cutoff)
    deleted_count, _ = qs.delete()
    if deleted_count:
        logger.info("Deleted %d unbound images older than %d day(s).", deleted_count, days)
    return deleted_count
```

Delete through the **queryset**, not a loop of `.delete()` calls — the queryset override already clears
storage, and one statement beats N. Schedule it in the beat schedule; without the sweep, every abandoned
form is permanent storage cost.

---

## 7. Multipart Endpoints and Their Schemas

```python
class ProductImageViewSet(CreateModelMixin, GenericViewSet):
    parser_classes = (MultiPartParser, FormParser)

    @swagger_auto_schema(manual_parameters=CATEGORY_FILE_PARAMS)
    def create(self, request, *args, **kwargs):
        ...
```

> ⚠️ Form parameters are only attached when a JSON parser is **not** also available on the viewset — the
> schema generator refuses to mix them. `parser_classes` here is a documentation requirement as much as a
> runtime one.

Declare one parameter per accepted field/category rather than a single opaque `files` blob, so the
generated docs show what the endpoint actually accepts.

---

## 8. Testing

Storage is pinned to a filesystem backend in a tmpdir by an autouse fixture, so uploads are real files that
vanish with the test. No mocking of the cloud backend, no bucket assumptions.

```python
def test_upload_creates_image(api_client, user):
    api_client.force_authenticate(user)
    upload = SimpleUploadedFile("photo.jpg", _jpeg_bytes(), content_type="image/jpeg")

    response = api_client.post(url, {"product": upload}, format="multipart")

    assert response.status_code == status.HTTP_201_CREATED
    image = ProductImage.objects.get(pk=response.data[0]["id"])
    assert image.original_name == "photo.jpg"
    assert image.file.name.endswith(".jpg")
    assert image.file.name != "photo.jpg"          # stored under a generated name
```

Worth covering explicitly, because each has failed silently before:

- **Cascade delete removes the stored file** — delete the *parent* and assert the file is gone from
  storage, not just the row from the database.
- **Rejected uploads** — oversize, wrong extension, and a file whose bytes don't match its extension.
- **The unbound sweep** — an old orphan is deleted, a recent one and a bound one are not.

Generate image bytes in the test (a small in-memory Pillow image) rather than committing binary fixtures.

---

## 9. Serving Files

- **Private files go through a view** that checks permissions and returns the file as an attachment — a
  storage URL is a capability anyone can forward.
- **Scope downloads to who may see them** (creator, or an elevated role), the same way any other object is
  scoped.
- **Set the download filename from `original_name`**, not from the stored UUID.
- **Public assets can use the storage URL directly**; do not build one by hand — `instance.file.url` is
  correct for whichever backend is configured.

---

## 10. Checklist

- [ ] Stored path generated (prefix + date + UUID + lowercased extension); user filename never used as a path.
- [ ] `original_name` captured on create, before `super().save()`.
- [ ] Model `delete()`, queryset `delete()` **and** a `post_delete` receiver all clear storage.
- [ ] Thumbnails deleted alongside their source; receivers imported from `AppConfig.ready()`.
- [ ] Size and extension limits read from settings; content verified by decoding, not by `content_type`.
- [ ] Upload-first flows have a TTL sweep scheduled in beat.
- [ ] Multipart viewsets declare `parser_classes` and `manual_parameters`.
- [ ] Tests cover cascade cleanup, rejected uploads and the orphan sweep; no binary fixtures committed.
- [ ] Private files served through a permission-checked view, not a raw storage URL.

## Navigation
- [DRF Endpoints](../drf-endpoints/SKILL.md)
- [Django App Layout](../django-app-layout/SKILL.md)
- [Celery Tasks](../celery-tasks/SKILL.md)
- [Django Testing](../django-testing/SKILL.md)
