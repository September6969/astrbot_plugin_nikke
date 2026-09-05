"""已确认的研究/收藏字段保持未知、空列表与零值语义。"""
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch
from astrbot_plugin_nikke.profile_builder import ProfileBuilder
from astrbot_plugin_nikke.profile_card_renderer import ProfileCardRenderer


class StructuredProfileTests(TestCase):
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
        with tempfile.TemporaryDirectory() as directory:
            renderer = ProfileCardRenderer(Path(directory), Path(directory))
            with patch.object(renderer, "_text", wraps=renderer._text) as draw:
                output = renderer.render_profile(data)
                self.assertTrue(Path(output).is_file())
                self.assertNotIn("private-id", str(draw.call_args_list))
                self.assertIn("RESEARCH", str(draw.call_args_list))
