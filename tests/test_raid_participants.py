"""人工语义样例基于已脱敏真实 shape，不证明赛季完整性。"""
import json
from dataclasses import asdict
from unittest import TestCase
from astrbot_plugin_nikke.raid_participants import build_ranking, format_ranking


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
