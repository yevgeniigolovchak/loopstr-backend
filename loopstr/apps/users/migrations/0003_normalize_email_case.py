from django.db import migrations


def normalize_email_case(apps, schema_editor):
    """Lowercase every stored address, so what is already in the table matches what is written now.

    Idempotent: a row that is already lowercase is not rewritten, so a re-run is a no-op. Two rows
    that differ only in case cannot be merged here — whichever one this kept would be somebody's
    account and whichever it dropped would be somebody's data — so it stops and names them for a
    human to resolve, rather than letting the unique index raise an IntegrityError that says
    nothing about which addresses collided.
    """
    User = apps.get_model("users", "User")

    collisions = []
    for user in User.objects.order_by("pk").iterator():
        normalized = user.email.lower()
        if normalized == user.email:
            continue

        if User.objects.filter(email=normalized).exclude(pk=user.pk).exists():
            collisions.append(user.email)
            continue

        User.objects.filter(pk=user.pk).update(email=normalized)

    if collisions:
        raise RuntimeError(
            "Cannot normalise these addresses: another account already holds the lowercase form. "
            "Merge or deactivate the duplicates by hand, then re-run the migration: "
            f"{', '.join(collisions)}"
        )


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0002_add_login_lockout_fields"),
    ]

    operations = [
        # No reverse: the original casing is not recoverable, and nothing downstream needs it back.
        migrations.RunPython(normalize_email_case, migrations.RunPython.noop),
    ]
