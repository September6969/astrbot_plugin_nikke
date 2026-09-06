"""证据转换只使用人工输入，禁止将本测试当作真实响应。"""
import json
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
        self.assertEqual(result[0]["participant_total_order"], result[2]["participant_total_order"])
        self.assertEqual(result[0]["total_damage"], "ordinal_3")
        self.assertEqual(result[0]["squad"][0]["slot"], 1)
        for secret in ["fake-a", "fake-b", "PRIVATE", "private-tid", "同名"]:
            self.assertNotIn(secret, json.dumps(result, ensure_ascii=False))

    def test_coprime_inputs_do_not_preserve_numeric_ratios(self):
        def rows(values):
            return [{"openid": who, "total_damage": value} for who, value in zip(("a", "a", "b"), values)]
        self.assertEqual(semantic_sanitize(rows((1000003, 2000007, 3000010))), semantic_sanitize(rows((7, 11, 18))))
