from rest_framework import serializers


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
    # `max_length` bounds what reaches the hasher. Without it the cap is `DATA_UPLOAD_MAX_MEMORY_SIZE`
    # — 2.5 MB — and every one of those bytes is hashed, including on the unknown-email path, which
    # hashes deliberately and counts nothing towards the lockout. 128 is the width of the model's
    # `password` column and far past any password a person types.
    password = serializers.CharField(trim_whitespace=False, write_only=True, max_length=128)
    rememberMe = serializers.BooleanField(source="remember_me")


class ForgotPasswordSerializer(serializers.Serializer):
    """Request body of `POST /auth/forgot-password` — docs/auth-api.md."""

    email = serializers.EmailField()
