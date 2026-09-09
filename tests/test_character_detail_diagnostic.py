import unittest

from astrbot_plugin_nikke.character_detail_diagnostic import summarize_character_details


class CharacterDetailDiagnosticTests(unittest.TestCase):
    def test_reports_numeric_shape_without_account_values(self):
        summary = summarize_character_details(
            {
                "hp": 123456,
                "attack": "98765",
                "defense": 0,
                "ratio": 1.25,
                "is_valid": True,
                "cookie_token": 123456789,
            }
        )

        fields = summary["detail_numeric_keys"]
        self.assertEqual(fields["hp"]["type"], "int")
        self.assertEqual(fields["hp"]["digit_count"], 6)
        self.assertEqual(fields["attack"]["type"], "str")
        self.assertEqual(fields["defense"]["sign"], "zero")
        self.assertEqual(fields["ratio"]["fraction_digits"], 2)
        self.assertNotIn("is_valid", fields)
        self.assertNotIn("cookie_token", fields)
        self.assertNotIn("123456", str(summary))
        self.assertNotIn("98765", str(summary))

    def test_malformed_and_missing_values_are_not_guessed(self):
        summary = summarize_character_details(
            {"hp": None, "attack": "unknown", "defense": "12x", "combat": 287405}
        )

        self.assertEqual(set(summary["detail_numeric_keys"]), {"combat"})
        self.assertTrue(summary["detail_numeric_keys"]["combat"]["non_empty"])


if __name__ == "__main__":
    unittest.main()

