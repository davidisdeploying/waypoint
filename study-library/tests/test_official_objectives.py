import unittest

from lib.official_objectives import OfficialObjectiveError, parse_layout_text


class TestOfficialObjectives(unittest.TestCase):
    def test_extracts_wrapped_headings_and_ignores_bullets(self):
        text = """
            1.1 Given a scenario, monitor mobile device hardware and use appropriate
                replacement techniques.
                • Battery
            1.2 Compare and contrast accessories.
                • Stylus
        """
        self.assertEqual(
            parse_layout_text(text, ["1.1", "1.2"]),
            [
                {
                    "code": "1.1",
                    "description": (
                        "Given a scenario, monitor mobile device hardware and use "
                        "appropriate replacement techniques."
                    ),
                },
                {"code": "1.2", "description": "Compare and contrast accessories."},
            ],
        )

    def test_missing_and_duplicate_codes_fail_closed(self):
        with self.assertRaisesRegex(OfficialObjectiveError, "missing"):
            parse_layout_text("1.1 Present.", ["1.1", "1.2"])
        with self.assertRaisesRegex(OfficialObjectiveError, "duplicate"):
            parse_layout_text("1.1 First.\n1.1 Second.", ["1.1"])
