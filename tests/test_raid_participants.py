"""人工语义样例基于已脱敏真实 shape，不证明赛季完整性。"""
import json
from dataclasses import asdict
from unittest import TestCase
from astrbot_plugin_nikke.raid_participants import build_member_ranking, build_ranking, format_ranking, format_compact_number



def attack(who, damage):
    return dict(openid=who, nickname="同名", boss_id="synthetic-boss", day=0, difficulty=1,
                level=1, step=1, total_damage=str(damage), is_final_hit=False,
                squad=[dict(tid=str(i), lv=100, combat=1000, slot=i) for i in range(1, 6)])


class RankingTests(TestCase):
    def test_aggregation_ties_and_privacy(self):
        result = build_ranking({"participate_data": [attack("fake-a", 10), attack("fake-a", 20), attack("fake-b", 30), attack("fake-c", 0)]})
        self.assertEqual([p.rank for p in result.participants], [1, 1, 3])
        self.assertEqual([p.total_damage for p in result.participants], [30, 30, 0])
        self.assertEqual(len(result.participants[0].attacks), 2)
        self.assertEqual(result.scope, "CURRENT_RESPONSE")
        output = json.dumps(asdict(result)) + format_ranking(result)
        self.assertNotIn("openid", output)
        self.assertNotIn("fake-a", output)

    def test_empty_and_malformed(self):
        self.assertEqual(build_ranking({"participate_data": []}).participants, [])
        for rows in [None, [None], [{}], [dict(attack("fake", 1), squad=[])], [dict(attack("fake", 1), total_damage="bad")]]:
            with self.assertRaises(ValueError):
                build_ranking({"participate_data": rows})

    def test_blank_identity_and_boss_or_character_ids_are_rejected(self):
        for row in [
            attack("   ", 1),
            dict(attack("fake", 1), boss_id=""),
            dict(attack("fake", 1), boss_id=None),
            dict(attack("fake", 1), squad=[
                dict(tid="", lv=100, combat=1000, slot=slot)
                for slot in range(1, 6)
            ]),
        ]:
            with self.subTest(row=row):
                with self.assertRaises(ValueError):
                    build_ranking({"participate_data": [row]})

    def test_member_filter_uses_exact_stable_identity_and_keeps_scope_honest(self):
        result = build_member_ranking(
            {"participate_data": [attack("me", 10), attack("other", 100)]},
            "me",
        )
        self.assertEqual(result.scope, "CURRENT_RESPONSE_MEMBER")
        self.assertEqual([item.total_damage for item in result.participants], [10])
        output = format_ranking(result)
        self.assertIn("我的当前响应范围", output)
        self.assertIn("不代表完整赛季", output)
        self.assertNotIn("other", output)

    def test_member_filter_rejects_missing_identity_and_malformed_rows(self):
        with self.assertRaises(ValueError):
            build_member_ranking({"participate_data": []}, "")
        with self.assertRaises(ValueError):
            build_member_ranking({"participate_data": [None]}, "me")

    def test_format_compact_number_boundaries(self):
        cases = [
            (0, "0"),
            (950, "950"),
            (999, "999"),
            (1_000, "1K"),
            (1_250, "1.25K"),
            (12_000, "12K"),
            (999_499, "999.5K"),
            (999_999, "1M"),
            (1_000_000, "1M"),
            (1_200_000, "1.2M"),
            (87_500_000, "87.5M"),
            (999_999_999, "1B"),
            (1_000_000_000, "1B"),
            (1_250_000_000, "1.25B"),
            (-950, "-950"),
            (-1_250, "-1.25K"),
            (-999_999, "-1M"),
            (None, "0"),
        ]
        for val, expected in cases:
            with self.subTest(val=val, expected=expected):
                self.assertEqual(format_compact_number(val), expected)

    def test_format_ranking_uses_compact_numbers(self):
        result = build_ranking({
            "participate_data": [
                attack("u1", 1_250_000),
                attack("u2", 999_999),
            ]
        })
        output = format_ranking(result)
        self.assertIn("1.25M", output)
        self.assertIn("1M", output)
        self.assertNotIn("1,250,000", output)
        self.assertNotIn("999,999", output)
