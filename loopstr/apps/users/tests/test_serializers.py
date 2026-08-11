import pytest

from users.serializers import ForgotPasswordSerializer, LoginSerializer

VALID_PAYLOAD = {"email": "member@example.com", "password": "SecretPassword1", "rememberMe": True}


class TestLoginSerializer:
    def test_maps_remember_me_out_of_camel_case(self):
        serializer = LoginSerializer(data=VALID_PAYLOAD)

        assert serializer.is_valid(), serializer.errors
        assert serializer.validated_data == {
            "email": "member@example.com",
            "password": "SecretPassword1",
            "remember_me": True,
        }

    def test_does_not_accept_snake_case_remember_me(self):
        # The mapping is one-way: the wire name is the contract's, and nothing else opts in.
        payload = {**VALID_PAYLOAD}
        payload["remember_me"] = payload.pop("rememberMe")

        serializer = LoginSerializer(data=payload)

        assert not serializer.is_valid()
        assert "rememberMe" in serializer.errors

    @pytest.mark.parametrize("missing", ["email", "password", "rememberMe"])
    def test_requires_every_contract_field(self, missing):
        payload = {key: value for key, value in VALID_PAYLOAD.items() if key != missing}

        serializer = LoginSerializer(data=payload)

        assert not serializer.is_valid()
        assert missing in serializer.errors

    def test_rejects_a_malformed_email(self):
        serializer = LoginSerializer(data={**VALID_PAYLOAD, "email": "not-an-email"})

        assert not serializer.is_valid()
        assert "email" in serializer.errors

    def test_keeps_surrounding_whitespace_in_the_password(self):
        # Stripping it would turn a correct password into a failed attempt against the lockout.
        serializer = LoginSerializer(data={**VALID_PAYLOAD, "password": "  spaced  "})

        assert serializer.is_valid(), serializer.errors
        assert serializer.validated_data["password"] == "  spaced  "

    def test_password_is_write_only(self):
        assert LoginSerializer().fields["password"].write_only

    def test_rejects_an_oversized_password(self):
        # Uncapped, the bound is `DATA_UPLOAD_MAX_MEMORY_SIZE` — 2.5 MB of input, all of it hashed,
        # on an endpoint that hashes for unknown addresses too and counts nothing for them.
        serializer = LoginSerializer(data={**VALID_PAYLOAD, "password": "x" * 129})

        assert not serializer.is_valid()
        assert "password" in serializer.errors

    def test_accepts_a_password_at_the_limit(self):
        serializer = LoginSerializer(data={**VALID_PAYLOAD, "password": "x" * 128})

        assert serializer.is_valid(), serializer.errors


class TestForgotPasswordSerializer:
    def test_accepts_a_well_formed_email(self):
        serializer = ForgotPasswordSerializer(data={"email": "member@example.com"})

        assert serializer.is_valid(), serializer.errors
        assert serializer.validated_data == {"email": "member@example.com"}

    @pytest.mark.parametrize("payload", [{}, {"email": ""}, {"email": "not-an-email"}])
    def test_rejects_anything_else(self, payload):
        serializer = ForgotPasswordSerializer(data=payload)

        assert not serializer.is_valid()
        assert "email" in serializer.errors
