import pytest

from users.models import User
from users.serializers import (
    ForgotPasswordSerializer,
    LoginSerializer,
    RegisterSerializer,
    SessionUserSerializer,
    UserSerializer,
)

VALID_PAYLOAD = {"email": "member@example.com", "password": "SecretPassword1", "rememberMe": True}
VALID_REGISTRATION = {
    "fullName": "Maya Lindqvist",
    "email": "maya@example.com",
    "password": "SecretPassword1",
}


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


class TestRegisterSerializer:
    def test_maps_full_name_out_of_camel_case(self):
        serializer = RegisterSerializer(data=VALID_REGISTRATION)

        assert serializer.is_valid(), serializer.errors
        assert serializer.validated_data == {
            "full_name": "Maya Lindqvist",
            "email": "maya@example.com",
            "password": "SecretPassword1",
        }

    def test_does_not_accept_snake_case_full_name(self):
        payload = {**VALID_REGISTRATION}
        payload["full_name"] = payload.pop("fullName")

        serializer = RegisterSerializer(data=payload)

        assert not serializer.is_valid()
        assert "fullName" in serializer.errors

    @pytest.mark.parametrize("missing", ["fullName", "email", "password"])
    def test_requires_every_contract_field(self, missing):
        payload = {key: value for key, value in VALID_REGISTRATION.items() if key != missing}

        serializer = RegisterSerializer(data=payload)

        assert not serializer.is_valid()
        assert missing in serializer.errors

    def test_ignores_a_confirm_password_field(self):
        # ACC-02 #4 is the client's: the mismatch is caught in the browser, the field never reaches
        # the API, and a client that sends it anyway must not be refused for it.
        serializer = RegisterSerializer(data={**VALID_REGISTRATION, "confirmPassword": "something else"})

        assert serializer.is_valid(), serializer.errors
        assert "confirmPassword" not in serializer.validated_data

    def test_trims_the_full_name(self):
        serializer = RegisterSerializer(data={**VALID_REGISTRATION, "fullName": "  Maya Lindqvist  "})

        assert serializer.is_valid(), serializer.errors
        assert serializer.validated_data["full_name"] == "Maya Lindqvist"

    @pytest.mark.parametrize("full_name", ["", "   "])
    def test_rejects_an_empty_full_name(self, full_name):
        serializer = RegisterSerializer(data={**VALID_REGISTRATION, "fullName": full_name})

        assert not serializer.is_valid()
        assert "fullName" in serializer.errors

    def test_rejects_a_full_name_wider_than_the_column(self):
        serializer = RegisterSerializer(data={**VALID_REGISTRATION, "fullName": "n" * 256})

        assert not serializer.is_valid()
        assert "fullName" in serializer.errors

    def test_accepts_a_full_name_at_the_column_width(self):
        # The cap is applied after trimming, so surrounding whitespace does not cost a character.
        serializer = RegisterSerializer(data={**VALID_REGISTRATION, "fullName": f"  {'n' * 255}  "})

        assert serializer.is_valid(), serializer.errors
        assert len(serializer.validated_data["full_name"]) == 255

    def test_rejects_an_email_wider_than_the_column(self):
        # Uncapped it would pass validation and fail at the INSERT with a `DataError` — a 500 for
        # what is a malformed request.
        serializer = RegisterSerializer(data={**VALID_REGISTRATION, "email": f"{'e' * 245}@example.com"})

        assert not serializer.is_valid()
        assert "email" in serializer.errors

    def test_rejects_a_malformed_email(self):
        serializer = RegisterSerializer(data={**VALID_REGISTRATION, "email": "not-an-email"})

        assert not serializer.is_valid()
        assert "email" in serializer.errors

    def test_keeps_surrounding_whitespace_in_the_password(self):
        serializer = RegisterSerializer(data={**VALID_REGISTRATION, "password": "  spaced 1  "})

        assert serializer.is_valid(), serializer.errors
        assert serializer.validated_data["password"] == "  spaced 1  "

    def test_password_is_write_only(self):
        assert RegisterSerializer().fields["password"].write_only

    def test_rejects_an_oversized_password(self):
        serializer = RegisterSerializer(data={**VALID_REGISTRATION, "password": f"{'x' * 127}1"})

        assert serializer.is_valid(), serializer.errors

        serializer = RegisterSerializer(data={**VALID_REGISTRATION, "password": f"{'x' * 128}1"})

        assert not serializer.is_valid()
        assert "password" in serializer.errors

    @pytest.mark.parametrize(
        "password",
        [
            "hedger4",  # seven characters
            "abcdefghij",  # no number
            "1234567890",  # no letter
        ],
    )
    def test_rejects_a_password_the_validators_refuse(self, password):
        # ACC-02 #3 is enforced server-side too: the client's own check is one `curl` away from
        # being skipped entirely.
        serializer = RegisterSerializer(data={**VALID_REGISTRATION, "password": password})

        assert not serializer.is_valid()
        assert "password" in serializer.errors

    def test_reports_every_reason_a_password_was_refused(self):
        # `message` is what a log line carries, and one reason at a time turns a single bad password
        # into a sequence of support tickets.
        serializer = RegisterSerializer(data={**VALID_REGISTRATION, "password": "short"})

        assert not serializer.is_valid()
        assert len(serializer.errors["password"]) == 2


class TestUserSerializer:
    """The account as login, registration and `GET /users/me` all publish it.

    Built from an unsaved row on purpose: what these assert is the shape of the payload, and nothing
    about it needs a database.
    """

    def test_it_publishes_the_account_in_camel_case(self):
        user = User(id=7, email="maya@example.com", full_name="Maya Lindqvist")

        assert UserSerializer(user).data == {
            "id": 7,
            "email": "maya@example.com",
            "fullName": "Maya Lindqvist",
            "role": User.ROLES.member,
        }

    def test_it_publishes_nothing_the_fields_tuple_does_not_name(self):
        # The row carries the password hash, the staff and superuser flags and the lockout counters.
        # An explicit tuple is what keeps the next column added to the model out of the payload.
        user = User(id=7, email="maya@example.com", full_name="Maya Lindqvist", is_staff=True)
        user.set_password("SecretPassword1")

        assert set(UserSerializer(user).data) == {"id", "email", "fullName", "role"}

    def test_every_field_is_read_only(self):
        # Nothing writes an account through this serializer; a writable field here would be an
        # endpoint's worth of behaviour nobody asked for.
        assert all(field.read_only for field in UserSerializer().fields.values())


class TestSessionUserSerializer:
    def test_it_wraps_the_account_under_user(self):
        user = User(id=7, email="maya@example.com", full_name="Maya Lindqvist")

        assert SessionUserSerializer({"user": user}).data == {"user": UserSerializer(user).data}


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
