import unittest
import tempfile
from pathlib import Path
from unittest.mock import Mock, call, patch, sentinel

from PIL import Image

from astrbot_plugin_nikke.campaign_history_models import ClearLineupStatus, StageClearMember, StageClearRecord
from astrbot_plugin_nikke.campaign_history_renderer import CampaignHistoryRenderer
from astrbot_plugin_nikke.main import NikkePlugin


class CampaignResourceWiringTests(unittest.TestCase):
    def test_campaign_renderer_reuses_plugin_asset_manager(self):
        plugin = NikkePlugin.__new__(NikkePlugin)
        plugin.data_dir = Path("data/nikke")
        plugin.plugin_dir = Path("plugin")
        plugin.asset_manager = sentinel.shared_assets

        with patch("astrbot_plugin_nikke.main.CampaignHistoryRenderer") as renderer:
            plugin._build_campaign_renderer()

        renderer.assert_called_once_with(
            Path("data/nikke/cards"),
            Path("plugin/fonts"),
            sentinel.shared_assets,
        )

    def test_campaign_renderer_keeps_falsey_shared_asset_manager(self):
        class FalseyAssets:
            def __bool__(self):
                return False

        assets = FalseyAssets()
        renderer = CampaignHistoryRenderer(
            Path("data/nikke/cards"),
            Path(__file__).resolve().parents[1] / "fonts",
            assets,
        )

        self.assertIs(renderer.assets, assets)

    def test_campaign_renderer_reuses_same_portrait_key_within_one_card(self):
        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory) / "cards"
            assets = Mock()
            assets.get_character_portrait.return_value = Image.new("RGBA", (32, 32), "red")
            renderer = CampaignHistoryRenderer(
                output_dir,
                Path(__file__).resolve().parents[1] / "fonts",
                assets,
            )
            record = StageClearRecord(
                mode="NORMAL",
                chapter=46,
                stage_name="46-40",
                stage_id=6046044,
                status=ClearLineupStatus.AVAILABLE,
                members=[
                    StageClearMember(tid=101, level=400, combat=100000, slot=slot, resource_id="c101")
                    for slot in range(1, 6)
                ],
            )

            path = renderer.render_campaign_history(record)

            self.assertTrue(Path(path).is_file())
            assets.get_character_portrait.assert_called_once_with(101, "c101", None)

    def test_campaign_renderer_does_not_merge_distinct_portrait_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory) / "cards"
            assets = Mock()
            assets.get_character_portrait.return_value = Image.new("RGBA", (32, 32), "red")
            renderer = CampaignHistoryRenderer(
                output_dir,
                Path(__file__).resolve().parents[1] / "fonts",
                assets,
            )
            record = StageClearRecord(
                mode="NORMAL",
                chapter=46,
                stage_name="46-40",
                stage_id=6046044,
                status=ClearLineupStatus.AVAILABLE,
                members=[
                    StageClearMember(tid=101, level=400, combat=100000, slot=1, resource_id="c101"),
                    StageClearMember(tid=101, level=400, combat=100000, slot=2, resource_id="c102"),
                    StageClearMember(tid=101, level=400, combat=100000, slot=3, resource_id="c101"),
                    StageClearMember(tid=101, level=400, combat=100000, slot=4, resource_id="c102"),
                    StageClearMember(tid=101, level=400, combat=100000, slot=5, resource_id="c101"),
                ],
            )

            path = renderer.render_campaign_history(record)

            self.assertTrue(Path(path).is_file())
            self.assertEqual(assets.get_character_portrait.call_count, 2)
            assets.get_character_portrait.assert_has_calls([call(101, "c101", None), call(101, "c102", None)])

    def test_campaign_renderer_keeps_costumes_separate_for_same_resource(self):
        with tempfile.TemporaryDirectory() as directory:
            assets = Mock()
            assets.get_character_portrait.return_value = Image.new("RGBA", (32, 32), "red")
            renderer = CampaignHistoryRenderer(
                Path(directory) / "cards",
                Path(__file__).resolve().parents[1] / "fonts",
                assets,
            )
            record = StageClearRecord(
                mode="NORMAL",
                chapter=46,
                stage_name="46-40",
                stage_id=6046044,
                status=ClearLineupStatus.AVAILABLE,
                members=[
                    StageClearMember(
                        tid=101,
                        level=400,
                        combat=100000,
                        slot=slot,
                        resource_id="c101",
                        costume_id="skin_01" if slot == 1 else None,
                    )
                    for slot in range(1, 6)
                ],
            )

            renderer.render_campaign_history(record)

            self.assertEqual(assets.get_character_portrait.call_count, 2)
            assets.get_character_portrait.assert_has_calls(
                [call(101, "c101", "skin_01"), call(101, "c101", None)]
            )
