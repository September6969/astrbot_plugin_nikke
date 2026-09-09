# SPDX-License-Identifier: GPL-3.0-or-later
"""验证已提交的现场证据工件只包含可复核的脱敏结构。"""

from __future__ import annotations

import json
from pathlib import Path
import unittest


EVIDENCE_PATH = Path(__file__).resolve().parents[1] / "docs" / "evidence" / "arcana_live_20260909.json"


class ArcanaLiveEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.evidence = json.loads(EVIDENCE_PATH.read_text(encoding="utf-8"))

    def test_three_queries_share_one_public_character_identity(self):
        queries = self.evidence["query_resolution"]
        self.assertEqual(
            {queries[name]["name_code"] for name in ("阿爾卡娜", "阿尔卡娜", "ARCANA")},
            {5140},
        )
        self.assertEqual({queries[name]["resource_id"] for name in queries}, {581})

    def test_live_account_evidence_keeps_costume_and_option_ids(self):
        account = self.evidence["authorized_read"]
        self.assertTrue(account["arcana_held"])
        self.assertEqual(account["name_code"], 5140)
        self.assertEqual(account["costume_id"], 0)
        self.assertEqual(
            {item["option_id"] for item in account["state_effects"]},
            {"7000611", "7001011", "7001111", "7001211"},
        )
        self.assertEqual(
            {item["function_type"] for item in account["state_effects"]},
            {"StatAccuracyCircle", "StatChargeTime", "StatCritical", "StatCriticalDamage"},
        )

    def test_evidence_has_no_raw_credentials_or_private_identity_fields(self):
        serialized = json.dumps(self.evidence, ensure_ascii=False).casefold()
        for forbidden in ("cookie", "authorization", "token", "openid", "qq_id", "game_uid", "raw_response"):
            self.assertNotIn(forbidden, serialized)
        self.assertEqual(self.evidence["status"], "LIVE_READ_ONLY")
        self.assertEqual(len(self.evidence["source_urls"]), 3)
        self.assertRegex(self.evidence["authorized_read"]["state_effects_sha256"], r"^[0-9a-f]{64}$")


if __name__ == "__main__":
    unittest.main()
