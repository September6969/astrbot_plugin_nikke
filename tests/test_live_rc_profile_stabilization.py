import tempfile
import unittest
from pathlib import Path

from PIL import Image

from astrbot_plugin_nikke.campaign_stage_resolver import CampaignStageResolver
from astrbot_plugin_nikke.profile_builder import ProfileBuilder, parse_profile_created_at
from astrbot_plugin_nikke.profile_card_renderer import ProfileCardRenderer


class CampaignProfileReverseLookupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.resolver = CampaignStageResolver.from_file(
            Path(__file__).resolve().parents[1] / "assets" / "campaign_stages.json"
        )

    def test_verified_normal_and_hard_ids_round_trip(self):
        normal = self.resolver.resolve_id(6048044, mode_hint="NORMAL")
        hard = self.resolver.resolve_id("7037041", mode_hint="困难")
        self.assertEqual((normal.mode, normal.name, normal.stage_id), ("NORMAL", "48-36", 6048044))
        self.assertEqual((hard.mode, hard.name, hard.stage_id), ("HARD", "37-33", 7037041))

    def test_mode_hint_does_not_silently_relabel_a_stage(self):
        self.assertIsNone(self.resolver.resolve_id(6048044, mode_hint="HARD"))
        self.assertIsNone(self.resolver.resolve_id(999999999))


class ProfileDataContractTests(unittest.TestCase):
    def test_created_at_uses_explicit_utc_plus_eight_display(self):
        self.assertEqual(parse_profile_created_at(1728295672), "2024-10-07")
        self.assertEqual(parse_profile_created_at("1728295672000"), "2024-10-07")
        self.assertEqual(parse_profile_created_at("2024-10-07T10:07:52Z"), "2024-10-07")
        self.assertIsNone(parse_profile_created_at("17282956720"))
        self.assertIsNone(parse_profile_created_at("not-a-date"))
        self.assertIsNone(parse_profile_created_at(1.5))

    def test_builder_reuses_campaign_catalog_and_keeps_unknown_id(self):
        resolver = CampaignStageResolver.from_file(
            Path(__file__).resolve().parents[1] / "assets" / "campaign_stages.json"
        )
        data = ProfileBuilder(resolver).build(
            account={},
            basic={
                "progress_normal_campaign": 6048044,
                "progress_hard_campaign": 7037041,
                "created_at": 1728295672,
            },
            outpost={},
            roster=None,
            fetched_at="2026-09-09 00:00",
            plugin_version="test",
        )
        self.assertEqual(data.normal_campaign, "48-36")
        self.assertEqual(data.hard_campaign, "37-33")
        self.assertEqual(data.created_at, "2024-10-07")

        unknown = ProfileBuilder(resolver).build(
            account={},
            basic={"progress_normal_campaign": 999999999},
            outpost={},
            roster=None,
            fetched_at="",
            plugin_version="test",
        )
        self.assertEqual(unknown.normal_campaign, "未映射 · ID 999999999")

    def test_renderer_receives_formatted_date_only(self):
        resolver = CampaignStageResolver.from_file(
            Path(__file__).resolve().parents[1] / "assets" / "campaign_stages.json"
        )
        data = ProfileBuilder(resolver).build(
            account={},
            basic={"created_at": 1728295672},
            outpost={},
            roster=None,
            fetched_at="",
            plugin_version="test",
        )
        self.assertEqual(ProfileCardRenderer._extra_items(data), [("注册时间", "2024-10-07")])
        with tempfile.TemporaryDirectory() as directory:
            renderer = ProfileCardRenderer(Path(directory), Path(directory))
            output = renderer.render_profile(data)
            with Image.open(output) as image:
                self.assertEqual(image.width, 1200)

    def test_internal_academy_ids_keep_neutral_unknown_semantics(self):
        data = ProfileBuilder().build(
            account={},
            basic={},
            outpost={"tactic_academy_class": 13000, "tactic_academy_lesson": "13003"},
            roster=None,
            fetched_at="",
            plugin_version="test",
        )
        self.assertEqual(data.tactic_academy_class, "未映射 · ID 13000")
        self.assertEqual(data.tactic_academy_lesson, "未映射 · ID 13003")


if __name__ == "__main__":
    unittest.main()
