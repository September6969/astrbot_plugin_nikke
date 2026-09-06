"""拒绝不相关日期拼接，并支持明确英文年月日。"""
from datetime import datetime, timezone
from unittest import TestCase
from astrbot_plugin_nikke.announcement_service import DeadlineParser


class DeadlineRangeTests(TestCase):
    def test_english_month_with_explicit_end(self):
        result = DeadlineParser.parse_deadlines("Event", "Ends September 6, 2026 at 18:00 UTC", "synthetic")
        self.assertEqual(result[0].end_at, datetime(2026, 9, 6, 18, tzinfo=timezone.utc))
        self.assertEqual(DeadlineParser.parse_deadlines("Event", "Starts September 6, 2026 18:00 UTC", "synthetic"), [])

    def test_unrelated_reversed_and_multiple_dates_are_rejected(self):
        for body in [
            "Published 2026-09-01 10:00 UTC. Starts 2026-09-02 10:00 UTC.",
            "2026-09-02 10:00 UTC ~ 2026-09-01 10:00 UTC",
            "2026-09-01 10:00 UTC ~ 2026-09-02 10:00 UTC; deadline 2026-09-03 10:00 UTC",
        ]:
            self.assertEqual(DeadlineParser.parse_deadlines("Event", body, "synthetic"), [])

    def test_english_explicit_range(self):
        result = DeadlineParser.parse_deadlines("Event", "September 5, 2026 18:00 UTC to September 6, 2026 18:00 UTC", "synthetic")
        self.assertEqual(len(result), 1)
        self.assertEqual((result[0].end_at-result[0].start_at).days, 1)
