"""只保留字段关系的合成剧情样例。"""
from unittest import TestCase
from astrbot_plugin_nikke.voice_scene_catalog import parse_scene_voices


class SceneVoiceTests(TestCase):
    def test_cross_checks_identity_and_map(self):
        def row(identifier, speaker):
            return {"value": {"id": identifier, "speaker": speaker}, "speaker": {"value": speaker}}
        detail = {"scenario_group_id": {"records": {"value": [row("test_line", "test_speaker"), row("unvoiced", "other")]}}}
        result = parse_scene_voices(detail, ["test_line"])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].speaker, "test_speaker")
        self.assertEqual(result[0].voice_type, "story")
        self.assertIsNone(result[0].skin)
        detail["scenario_group_id"]["records"]["value"][0]["speaker"]["value"] = "conflicting"
        with self.assertRaises(ValueError):
            parse_scene_voices(detail, ["test_line"])
