"""已确认的研究/收藏字段保持未知、空列表与零值语义。"""
from unittest import TestCase
from astrbot_plugin_nikke.features.profile.builder import ProfileBuilder


class StructuredProfileTests(TestCase):
    def test_verified_research_labels_do_not_guess_unknown_ids(self):
        data = self.build({"recycle_room_researches": [{"tid": 1101, "lv": 5}, {"tid": 99999, "lv": 1}]})
        self.assertEqual(data.recycle_room_researches[0].display_name, "Attacker")
        self.assertEqual(data.recycle_room_researches[0].category, "Class")
        self.assertIsNone(data.recycle_room_researches[1].display_name)

    def build(self, outpost):
        return ProfileBuilder().build(account={}, basic={}, outpost=outpost,
            roster=None, fetched_at="", plugin_version="test")

    def test_unknown_empty_and_zero(self):
        self.assertIsNone(self.build({}).recycle_room_researches)
        self.assertEqual(self.build({"recycle_room_researches": []}).recycle_room_researches, [])
        data = self.build({"recycle_room_researches": [{"tid": "private-id", "lv": 0, "exp": 0}, {}, {"lv": "bad"}],
                           "memorial_counts": [{"category": "unknown", "count": 0}]})
        self.assertEqual(data.recycle_room_researches[0].level, 0)
        self.assertEqual(data.recycle_room_researches[0].exp, 0)
        self.assertIsNone(data.recycle_room_researches[1].tid)
        self.assertIsNone(data.recycle_room_researches[2].level)
        self.assertEqual(data.memorial_counts[0].count, 0)
        from astrbot_plugin_nikke.ui.payloads.profile import ProfileT2IPayloadBuilder

        payload = ProfileT2IPayloadBuilder().build(data)
        encoded = str(payload)
        self.assertNotIn("private-id", encoded)
        self.assertIn("研究项目名称 Unknown", encoded)
        self.assertNotIn("EXP 0", encoded)
