# Aliased on import: `RegisterSerializer` declares a `validate_password` hook of its own, and two
# names one letter apart is how `self.validate_password(value)` gets written by a later cleanup and
# recurses until the request 500s.
from django.contrib.auth.password_validation import validate_password as run_password_validators
from django.core.exceptions import ValidationError as DjangoValidationError

from rest_framework import serializers

# What reaches the hasher. Without a cap the bound is `DATA_UPLOAD_MAX_MEMORY_SIZE` — 2.5 MB, all of
# it hashed on a login path that hashes for unknown addresses too and counts nothing for them.
#
# This is a resource limit, not password policy: ACC-02 #3 sets a floor and no ceiling, and the
# client checks no ceiling either, so a longer password passes the browser and comes back 400
# `UNKNOWN_ERROR` with nothing on screen to explain it. That is the same cost the criterion-only
# `AUTH_PASSWORD_VALIDATORS` was trimmed to avoid, accepted here because the alternative is an
# unbounded hash. 128 is far past what a person types and past what a generator is usually asked
# for; it is not the `password` column's width, which stores a fixed-size hash whatever goes in.
#
# Shared by both endpoints on purpose: a registration that accepted a longer password than login
# submits would create an account nobody could sign back into.
PASSWORD_MAX_LENGTH = 128

# The widths of the columns the registration writes. A value past either passes DRF's own
# validation — neither `EmailField` nor an uncapped `CharField` knows about the table — and fails at
# the INSERT with a `DataError`, which is a 500 for what is really a 400.
EMAIL_MAX_LENGTH = 254
FULL_NAME_MAX_LENGTH = 255


class LoginSerializer(serializers.Serializer):
    """Request body of `POST /auth/login` — docs/auth-api.md.

    A plain `Serializer`, not a `ModelSerializer`: nothing here is written to a row. camelCase stops
    at this boundary — `rememberMe` is declared under the name the client actually sends and mapped
    with `source=`, so `validated_data` comes out snake_case without a project-wide renderer that
    would rewrite every other endpoint's payload to satisfy this one.
    """

    email = serializers.EmailField()
    # `trim_whitespace=False`: a password may legitimately begin or end with a space, and stripping
    # it turns a correct password into a failed attempt that counts towards the lockout.
    #
    # The length cap matters here beyond the hashing cost: the unknown-email path hashes
    # deliberately and counts nothing towards the lockout, so it is free to repeat.
    password = serializers.CharField(trim_whitespace=False, write_only=True, max_length=PASSWORD_MAX_LENGTH)
    rememberMe = serializers.BooleanField(source="remember_me")


class RegisterSerializer(serializers.Serializer):
    """Request body of `POST /auth/register` — docs/auth-api.md.

    Three fields, not the four the Registration page shows: "Confirm password" never leaves the
    browser. The contract's body does not carry it, the frontend recognises no error code for a
    mismatch, and ACC-02 #4 is an inline check the client owns. A stray `confirmPassword` key is
    ignored rather than refused — `Serializer` reads only the fields it declares.
    """

    fullName = serializers.CharField(source="full_name", max_length=FULL_NAME_MAX_LENGTH)
    email = serializers.EmailField(max_length=EMAIL_MAX_LENGTH)
    password = serializers.CharField(trim_whitespace=False, write_only=True, max_length=PASSWORD_MAX_LENGTH)

    def validate_password(self, value):
        """Apply `AUTH_PASSWORD_VALIDATORS` — ACC-02 #3, which a client-side check cannot enforce.

        No `user=`: the configured set is the story's criterion and nothing else, and none of those
        two rules reads one. The day a validator that does is added — `UserAttributeSimilarityValidator`
        is the obvious candidate — this call has to pass an unsaved `User` built from the payload, or
        the validator is configured and silently never runs.

        Django's `ValidationError` is repacked as DRF's so the failure joins the ordinary
        invalid-body path and answers 400 with the contract's envelope.
        """
        try:
            run_password_validators(value)
        except DjangoValidationError as error:
            raise serializers.ValidationError(error.messages)

        return value


class ForgotPasswordSerializer(serializers.Serializer):
    """Request body of `POST /auth/forgot-password` — docs/auth-api.md."""

    email = serializers.EmailField()
