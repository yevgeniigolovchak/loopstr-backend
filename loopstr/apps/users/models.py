import math
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from model_utils import Choices
from model_utils.models import TimeStampedModel


class UserManager(BaseUserManager):
    use_in_migrations = True

    @classmethod
    def normalize_email(cls, email):
        """Lowercase the whole address, not only the domain part.

        `BaseUserManager` normalises the domain and leaves the local part alone, which makes
        `alice@example.com` and `Alice@example.com` two separately insertable rows behind a
        case-sensitive unique index — and a login that then resolves to whichever one it happens
        to find, charging the failed attempts to the other person's account.
        """
        return super().normalize_email(email).lower()

    def _create_user(self, email, password, **extra_fields):
        """Create and save a user with the given email and password."""
        if not email:
            raise ValueError("The given email must be set")

        user = self.model(email=self.normalize_email(email), **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)

        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")

        return self._create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin, TimeStampedModel):
    ROLES = Choices(("member", _("Member")))

    email = models.EmailField(_("email address"), unique=True)
    full_name = models.CharField(_("full name"), max_length=255, blank=True, default="")
    role = models.CharField(_("role"), max_length=32, choices=ROLES, default=ROLES.member)
    is_active = models.BooleanField(
        _("active"),
        default=True,
        help_text=_("Unselect this instead of deleting the account."),
    )
    is_staff = models.BooleanField(
        _("staff status"),
        default=False,
        help_text=_("Designates whether the user can log into the admin site."),
    )
    failed_login_attempts = models.PositiveSmallIntegerField(_("failed login attempts"), default=0)
    locked_until = models.DateTimeField(_("locked until"), null=True, blank=True)

    EMAIL_FIELD = "email"
    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ()

    objects = UserManager()

    class Meta:
        verbose_name = _("user")
        verbose_name_plural = _("users")
        ordering = ("-created",)

    def __str__(self):
        return self.email

    def save(self, *args, **kwargs):
        """Normalise the address before it is written, whatever did the writing.

        The manager normalises what goes through `create_user`, but the admin, a factory and a
        plain `User(...)` all bypass it — and every address being lowercase is what makes the
        column's own `unique=True` mean "one address, one account". `update_fields` needs no
        special handling: either `email` is in it and this is the value being written, or the
        column is not touched.
        """
        self.email = UserManager.normalize_email(self.email)

        return super().save(*args, **kwargs)

    def get_full_name(self):
        return self.full_name

    def get_short_name(self):
        return self.full_name or self.email

    @property
    def is_locked_out(self):
        """Whether the lockout window from ACC-01 #6 is still open."""
        return self.locked_until is not None and self.locked_until > timezone.now()

    @property
    def lockout_seconds_remaining(self):
        """Seconds left on the lock, for the `Retry-After` header. Zero when the account is usable."""
        if not self.is_locked_out:
            return 0

        return math.ceil((self.locked_until - timezone.now()).total_seconds())

    def register_failed_login(self):
        """Count one failed attempt and lock the account once the threshold is reached.

        The counter is cleared at the moment the lock is set, so an account whose window has run out
        starts again with a full set of attempts and there is no second "the lock expired" path to
        remember to run.
        """
        self.failed_login_attempts += 1
        if self.failed_login_attempts >= settings.AUTH_LOCKOUT_MAX_ATTEMPTS:
            self.failed_login_attempts = 0
            self.locked_until = timezone.now() + timedelta(minutes=settings.AUTH_LOCKOUT_MINUTES)

        self.save(update_fields=("failed_login_attempts", "locked_until", "modified"))

    def reset_login_lockout(self):
        """Clear the counter and any spent lock after a successful login.

        The lock it clears is always an expired one: a live lock is refused before the password is
        ever checked, so there is no path here that unlocks an account early.
        """
        if not self.failed_login_attempts and self.locked_until is None:
            return

        self.failed_login_attempts = 0
        self.locked_until = None
        self.save(update_fields=("failed_login_attempts", "locked_until", "modified"))
