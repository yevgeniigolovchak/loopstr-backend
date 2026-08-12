"""Validators the project needs and Django does not ship."""

from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _


class LetterAndNumberValidator:
    """ACC-02 #3 — a password mixes letters and digits. Django has no rule with that meaning.

    One message for both halves rather than two validators: the criterion states a single rule, and
    the frontend recognises no code for a rejected password, so the two texts would arrive as one
    `UNKNOWN_ERROR` anyway.

    `isalpha()` and `isdigit()` are Unicode-aware, which makes this marginally more permissive than
    the client's own check. That direction is safe — the stricter side refuses first and the user
    never sees a disagreement. The reverse would be a password the client accepts and the API does
    not, with nothing on screen to explain it.
    """

    def validate(self, password, user=None):
        has_letter = any(character.isalpha() for character in password)
        has_number = any(character.isdigit() for character in password)
        if not has_letter or not has_number:
            raise ValidationError(
                _("This password must contain at least one letter and one number."),
                code="password_no_letter_and_number",
            )

    def get_help_text(self):
        return _("Your password must contain at least one letter and one number.")
