from django.core.exceptions import ValidationError

import pytest

from common.validators import LetterAndNumberValidator


class TestLetterAndNumberValidator:
    """ACC-02 #3 — the half of the criterion Django has no validator for."""

    def test_accepts_a_password_with_a_letter_and_a_number(self):
        assert LetterAndNumberValidator().validate("abcdefg1") is None

    @pytest.mark.parametrize(
        "password",
        [
            "abcdefghij",  # letters only
            "!!!!!!!!!!",  # neither
        ],
    )
    def test_rejects_a_password_with_no_number(self, password):
        with pytest.raises(ValidationError):
            LetterAndNumberValidator().validate(password)

    @pytest.mark.parametrize(
        "password",
        [
            "1234567890",  # digits only
            "1234567!@#",  # digits and punctuation
        ],
    )
    def test_rejects_a_password_with_no_letter(self, password):
        with pytest.raises(ValidationError):
            LetterAndNumberValidator().validate(password)

    def test_the_message_names_both_requirements(self):
        with pytest.raises(ValidationError) as failure:
            LetterAndNumberValidator().validate("abcdefghij")

        assert failure.value.messages == ["This password must contain at least one letter and one number."]

    def test_the_message_carries_a_code(self):
        # The joined `messages` are what the caller shows; the code is what another caller can
        # branch on without matching on English.
        with pytest.raises(ValidationError) as failure:
            LetterAndNumberValidator().validate("abcdefghij")

        assert failure.value.code == "password_no_letter_and_number"

    def test_the_help_text_names_both_requirements(self):
        help_text = LetterAndNumberValidator().get_help_text()

        assert "letter" in help_text
        assert "number" in help_text

    def test_a_non_ascii_letter_counts(self):
        # `isalpha()` is Unicode-aware on purpose: a password nobody could type in ASCII still
        # satisfies the criterion.
        assert LetterAndNumberValidator().validate("пароль1") is None
