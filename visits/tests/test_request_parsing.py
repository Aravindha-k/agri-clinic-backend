from django.test import SimpleTestCase
from rest_framework.exceptions import ValidationError

from visits.request_parsing import coerce_optional_bool


class CoerceOptionalBoolTest(SimpleTestCase):
    def test_accepts_native_and_string_forms(self):
        for value, expected in [
            (True, True),
            (False, False),
            ("true", True),
            ("false", False),
            ("TRUE", True),
            ("False", False),
            ("1", True),
            ("0", False),
            (1, True),
            (0, False),
        ]:
            with self.subTest(value=value):
                self.assertEqual(
                    coerce_optional_bool(value, field="follow_up_required"),
                    expected,
                )

    def test_empty_values_are_none(self):
        self.assertIsNone(coerce_optional_bool(None, field="follow_up_required"))
        self.assertIsNone(coerce_optional_bool("", field="follow_up_required"))

    def test_invalid_value_raises_validation_error(self):
        with self.assertRaises(ValidationError):
            coerce_optional_bool("maybe", field="follow_up_required")
