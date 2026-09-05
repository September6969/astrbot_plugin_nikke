"""证据转换只使用人工输入，禁止将本测试当作真实响应。"""
import json
from fractions import Fraction
from unittest import TestCase
from astrbot_plugin_nikke.scripts.raid_evidence import semantic_sanitize


class EvidenceTests(TestCase):
    def test_relationships_and_damage_totals(self):
        rows = [{"openid": who, "nickname": "同名", "total_damage": damage,
                 "cookie": "PRIVATE", "squad": [{"slot": 1, "tid": "private-tid"}]}
                for who, damage in [("fake-a", 10), ("fake-a", 20), ("fake-b", 30)]]
        result = semantic_sanitize(rows)
        self.assertEqual(result[0]["openid"], result[1]["openid"])
        self.assertNotEqual(result[0]["openid"], result[2]["openid"])
        self.assertEqual(Fraction(result[0]["total_damage"]) + Fraction(result[1]["total_damage"]),
                         Fraction(result[2]["total_damage"]))
        self.assertEqual(result[0]["squad"][0]["slot"], 1)
        for secret in ["fake-a", "fake-b", "PRIVATE", "private-tid", "同名"]:
            self.assertNotIn(secret, json.dumps(result, ensure_ascii=False))
