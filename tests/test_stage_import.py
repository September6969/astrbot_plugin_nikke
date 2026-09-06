"""静态关卡导入不使用章节公式或静默冲突覆盖。"""
import json
from pathlib import Path
from unittest import TestCase
from astrbot_plugin_nikke.scripts.import_campaign_stages import build_mapping
from astrbot_plugin_nikke.campaign_stage_resolver import CampaignStageResolver


class StageImportTests(TestCase):
    def test_explicit_labels_and_modes(self):
        rows = [
            {"chapter_mod": "Normal", "chapter_id": 47, "id": 6046015, "name_localkey": {"name": "46-14A-1 STAGE"}},
            {"chapter_mod": "Hard", "id": 7035036, "name_localkey": {"name": "35-36 HARD BOSS"}},
            {"chapter_mod": "Story", "id": 99, "name_localkey": {"name": "46-14A-1 STAGE"}},
            {"chapter_mod": "Normal", "id": 123, "name_localkey": {"name": "EX-1 STAGE"}},
        ]
        mapping = build_mapping(rows)
        self.assertEqual(mapping["NORMAL"], {"46": {"46-14A-1": 6046015}})
        with self.assertRaises(ValueError):
            build_mapping(rows + [dict(rows[0], id=22)])

    def test_bundled_snapshot_covers_multiple_chapters(self):
        path = Path(__file__).resolve().parents[1] / "assets/campaign_stages.json"
        mapping = json.loads(path.read_text(encoding="utf-8"))
        resolver = CampaignStageResolver(mapping)
        self.assertEqual(resolver.resolve_query("46-14A-1").stage_id, 6046015)
        self.assertIsNotNone(resolver.resolve_query("1-1"))
        self.assertIsNotNone(resolver.resolve_query("H1-1"))
        self.assertIsNone(resolver.resolve_query("999-999"))
