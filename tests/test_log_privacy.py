# SPDX-License-Identifier: GPL-3.0-or-later

import asyncio
import unittest

from astrbot_plugin_nikke.announcement_service import AnnouncementService
from astrbot_plugin_nikke.log_privacy import safe_exception_message, sanitize_log_text


class LogPrivacyTests(unittest.TestCase):
    def test_sensitive_values_are_removed_from_log_summary(self):
        raw = (
            "HTTP failure token=token-value cookie=game_token=cookie-value; "
            "game_uid=uid-value Authorization: Bearer bearer-value "
            'openid="openid-value" user@example.com'
        )

        result = sanitize_log_text(raw)

        self.assertNotIn("token-value", result)
        self.assertNotIn("cookie-value", result)
        self.assertNotIn("uid-value", result)
        self.assertNotIn("bearer-value", result)
        self.assertNotIn("openid-value", result)
        self.assertNotIn("user@example.com", result)
        self.assertIn("[已遮盖]", result)

    def test_json_and_query_credentials_are_removed(self):
        raw = '{"authorization":"secret", "token":"abc"} https://example.test/?token=query-secret'

        result = sanitize_log_text(raw)

        self.assertNotIn("secret", result)
        self.assertNotIn("abc", result)
        self.assertNotIn("query-secret", result)

    def test_exception_summary_keeps_type_and_has_bounded_length(self):
        result = safe_exception_message(ValueError("secret=abc " + "x" * 500), max_length=80)

        self.assertTrue(result.startswith("ValueError:"))
        self.assertNotIn("secret=abc", result)
        self.assertLessEqual(len(result), 80)

    def test_announcement_sync_log_uses_the_sanitized_exception(self):
        raw = "authorization=Bearer-real-secret token=raw-token"

        async def failing_fetcher():
            raise ConnectionError(raw)

        async def run_sync():
            service = AnnouncementService()
            with self.assertLogs("nikke.announcements", level="WARNING") as captured:
                success, message = await service.sync_from_source(failing_fetcher)
            return success, message, "\n".join(captured.output)

        success, message, log_output = asyncio.run(run_sync())

        self.assertFalse(success)
        self.assertNotIn("raw-token", message)
        self.assertNotIn("Bearer-real-secret", message)
        self.assertNotIn("raw-token", log_output)
        self.assertNotIn("Bearer-real-secret", log_output)


if __name__ == "__main__":
    unittest.main()
