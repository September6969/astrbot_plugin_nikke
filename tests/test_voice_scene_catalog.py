"""只保留字段关系的合成剧情样例。"""
from unittest import TestCase
from astrbot_plugin_nikke.voice_scene_catalog import audit_story_voice_mapping, parse_scene_voices


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

    def test_audit_reports_exact_story_coverage_without_poke_inference(self):
        def row(identifier, speaker):
            return {"value": {"id": identifier, "speaker": speaker}, "speaker": {"value": speaker}}

        detail = {"scenario_group_id": {"records": {"value": [row("d_main_01_01_e_1", "Marian"), row("d_main_01_01_e_2", "Self")]}}}
        report = audit_story_voice_mapping(
            "d_main_01_01_e", detail, ["d_main_01_01_e_1", "d_main_01_01_e_2", "d_main_01_01_s_1"]
        )

        self.assertTrue(report.coverage_complete)
        self.assertEqual(report.map_count, 2)
        self.assertEqual(report.detail_count, 2)
        self.assertEqual(report.matched_ids, ("d_main_01_01_e_1", "d_main_01_01_e_2"))
        self.assertEqual(report.speakers, ("Marian", "Self"))
        self.assertEqual(report.scope, "STORY_SCENE")
        self.assertEqual(report.interaction_type_evidence, "NOT_OBSERVED")
        self.assertEqual(report.skin_evidence, "NOT_OBSERVED")

    def test_audit_keeps_partial_coverage_and_duplicate_ids_visible(self):
        def row(identifier, speaker):
            return {"value": {"id": identifier, "speaker": speaker}, "speaker": {"value": speaker}}

        detail = {"scenario_group_id": {"records": {"value": [row("d_main_01_01_e_1", "Marian"), row("d_main_01_01_e_7", "Marian")]}}}
        report = audit_story_voice_mapping(
            "d_main_01_01_e",
            detail,
            ["d_main_01_01_e_1", "d_main_01_01_e_1", "d_main_01_01_e_9", "d_main_01_01_s_1"],
        )

        self.assertFalse(report.coverage_complete)
        self.assertEqual(report.map_only_ids, ("d_main_01_01_e_9",))
        self.assertEqual(report.detail_only_ids, ("d_main_01_01_e_7",))
        self.assertEqual(report.duplicate_map_ids, ("d_main_01_01_e_1",))
