# SPDX-License-Identifier: GPL-3.0-or-later

import tempfile
import unittest
from pathlib import Path
from PIL import Image

from astrbot_plugin_nikke.campaign_history_builder import CampaignHistoryBuilder
from astrbot_plugin_nikke.campaign_history_models import ClearLineupStatus, StageClearMember, StageClearRecord
from astrbot_plugin_nikke.campaign_history_renderer import CampaignHistoryRenderer
from astrbot_plugin_nikke.campaign_stage_resolver import CampaignStage, CampaignStageResolver


class CampaignStageResolverTests(unittest.TestCase):
    def setUp(self):
        self.asset_path = Path(__file__).resolve().parents[1] / "assets" / "campaign_stages.json"
        self.resolver = CampaignStageResolver.from_file(self.asset_path)

    def test_mode_alias_normalization(self):
        self.assertEqual(CampaignStageResolver.normalize_mode("normal"), "NORMAL")
        self.assertEqual(CampaignStageResolver.normalize_mode("普通"), "NORMAL")
        self.assertEqual(CampaignStageResolver.normalize_mode("N"), "NORMAL")
        self.assertEqual(CampaignStageResolver.normalize_mode("hard"), "HARD")
        self.assertEqual(CampaignStageResolver.normalize_mode("困难"), "HARD")
        self.assertEqual(CampaignStageResolver.normalize_mode("H"), "HARD")

    def test_query_parsing(self):
        self.assertEqual(
            CampaignStageResolver.parse_query("46-40"),
            ("NORMAL", "46-40"),
        )
        self.assertEqual(
            CampaignStageResolver.parse_query("困难 35-36"),
            ("HARD", "35-36"),
        )
        self.assertEqual(
            CampaignStageResolver.parse_query("H35-36"),
            ("HARD", "35-36"),
        )
        self.assertEqual(
            CampaignStageResolver.parse_query("普通 46-14A-1"),
            ("NORMAL", "46-14A-1"),
        )

    def test_stage_resolution_matches_verified_evidence(self):
        # NORMAL 46-40 -> 6046044
        stage = self.resolver.resolve_query("46-40")
        self.assertIsNotNone(stage)
        self.assertEqual(stage.stage_id, 6046044)
        self.assertEqual(stage.mode, "NORMAL")
        self.assertEqual(stage.chapter, 46)

        # Side quest 46-14A-1 takes internal slot -> 6046015
        side = self.resolver.resolve_query("普通 46-14A-1")
        self.assertIsNotNone(side)
        self.assertEqual(side.stage_id, 6046015)

        # HARD 35-36 -> 7035044
        hard = self.resolver.resolve_query("困难 35-36")
        self.assertIsNotNone(hard)
        self.assertEqual(hard.stage_id, 7035044)
        self.assertEqual(hard.mode, "HARD")

    def test_nonexistent_stage_returns_none(self):
        self.assertIsNone(self.resolver.resolve_query("99-99"))
        self.assertIsNone(self.resolver.resolve_query("困难 99-99"))


class CampaignHistoryBuilderTests(unittest.TestCase):
    def setUp(self):
        self.directory = [
            {"name_code": 101, "name_cn": "爱丽丝", "name_en": "Alice", "resource_id": "c101"},
            {"name_code": 102, "name_cn": "红莲", "name_en": "Scarlet", "resource_id": "c102"},
            {"name_code": 103, "name_cn": "黑莲", "name_en": "Scarlet: Black Shadow", "resource_id": "c103"},
            {"name_code": 104, "name_cn": "丽塔", "name_en": "Liter", "resource_id": "c104"},
            {"name_code": 105, "name_cn": "娜嘉", "name_en": "Naga", "resource_id": "c105"},
        ]
        self.builder = CampaignHistoryBuilder(self.directory)
        self.stage = CampaignStage(mode="NORMAL", chapter=46, name="46-40", stage_id=6046044)

    def test_status_1300017_strictly_unavailable(self):
        payload = {"code": 1300017, "msg": "no lineup", "data": None}
        record = self.builder.build(self.stage, payload)
        self.assertEqual(record.status, ClearLineupStatus.UNAVAILABLE)
        self.assertEqual(record.status_message, "该关卡暂无可查询的历史阵容")
        self.assertEqual(record.members, [])
        self.assertEqual(record.total_combat, 0)

    def test_status_212000_rate_limited(self):
        payload = {"code": 212000, "msg": "frequency limit", "data": None}
        record = self.builder.build(self.stage, payload)
        self.assertEqual(record.status, ClearLineupStatus.RATE_LIMITED)
        self.assertIn("过频", record.status_message)

    def test_status_0_valid_lineup_and_combat_sum(self):
        raw_list = [
            {"tid": 101, "lv": 400, "combat": 120000, "slot": 1},
            {"tid": 102, "lv": 400, "combat": 115000, "slot": 2},
            {"tid": 103, "lv": 400, "combat": 118000, "slot": 3},
            {"tid": 104, "lv": 400, "combat": 95000, "slot": 4},
            {"tid": 105, "lv": 400, "combat": 102000, "slot": 5},
        ]
        payload = {"code": 0, "msg": "ok", "data": {"list": raw_list}}
        record = self.builder.build(self.stage, payload, commander_name="测试指挥官")
        self.assertEqual(record.status, ClearLineupStatus.AVAILABLE)
        self.assertEqual(len(record.members), 5)
        self.assertEqual(record.members[0].name_cn, "爱丽丝")
        self.assertEqual(record.members[0].resource_id, "c101")
        # 严格检查总战力等于各成员单体战力之和
        expected_combat = 120000 + 115000 + 118000 + 95000 + 102000
        self.assertEqual(record.total_combat, expected_combat)
        self.assertEqual(record.total_combat, 550000)

    def test_empty_list_treated_as_unavailable(self):
        payload = {"code": 0, "msg": "ok", "data": {"list": []}}
        record = self.builder.build(self.stage, payload)
        self.assertEqual(record.status, ClearLineupStatus.UNAVAILABLE)
        self.assertEqual(record.status_message, "该关卡暂无可查询的历史阵容")

    def test_strict_lineup_validation_4_members(self):
        raw_list = [
            {"tid": 101, "lv": 400, "combat": 120000, "slot": 1},
            {"tid": 102, "lv": 400, "combat": 115000, "slot": 2},
            {"tid": 103, "lv": 400, "combat": 118000, "slot": 3},
            {"tid": 104, "lv": 400, "combat": 95000, "slot": 4},
        ]
        payload = {"code": 0, "msg": "ok", "data": {"list": raw_list}}
        record = self.builder.build(self.stage, payload)
        self.assertEqual(record.status, ClearLineupStatus.ERROR)

    def test_strict_lineup_validation_6_members(self):
        raw_list = [
            {"tid": 101, "lv": 400, "combat": 12000, "slot": 1},
            {"tid": 102, "lv": 400, "combat": 11500, "slot": 2},
            {"tid": 103, "lv": 400, "combat": 11800, "slot": 3},
            {"tid": 104, "lv": 400, "combat": 9500, "slot": 4},
            {"tid": 105, "lv": 400, "combat": 10200, "slot": 5},
            {"tid": 106, "lv": 400, "combat": 10200, "slot": 6},
        ]
        payload = {"code": 0, "msg": "ok", "data": {"list": raw_list}}
        record = self.builder.build(self.stage, payload)
        self.assertEqual(record.status, ClearLineupStatus.ERROR)

    def test_strict_lineup_validation_duplicate_slots(self):
        raw_list = [
            {"tid": 101, "lv": 400, "combat": 12000, "slot": 1},
            {"tid": 102, "lv": 400, "combat": 11500, "slot": 2},
            {"tid": 103, "lv": 400, "combat": 11800, "slot": 3},
            {"tid": 104, "lv": 400, "combat": 9500, "slot": 4},
            {"tid": 105, "lv": 400, "combat": 10200, "slot": 4},
        ]
        payload = {"code": 0, "msg": "ok", "data": {"list": raw_list}}
        record = self.builder.build(self.stage, payload)
        self.assertEqual(record.status, ClearLineupStatus.ERROR)

    def test_strict_lineup_validation_missing_slots(self):
        raw_list = [
            {"tid": 101, "lv": 400, "combat": 12000, "slot": 1},
            {"tid": 102, "lv": 400, "combat": 11500, "slot": 2},
            {"tid": 103, "lv": 400, "combat": 11800, "slot": 3},
            {"tid": 104, "lv": 400, "combat": 9500, "slot": 4},
            {"tid": 105, "lv": 400, "combat": 10200, "slot": 6},
        ]
        payload = {"code": 0, "msg": "ok", "data": {"list": raw_list}}
        record = self.builder.build(self.stage, payload)
        self.assertEqual(record.status, ClearLineupStatus.ERROR)

    def test_strict_lineup_validation_filtered_item(self):
        raw_list = [
            {"tid": 101, "lv": 400, "combat": 12000, "slot": 1},
            {"tid": 102, "lv": 400, "combat": 11500, "slot": 2},
            {"tid": 103, "lv": 400, "combat": 11800, "slot": 3},
            {"tid": 104, "lv": 400, "combat": 9500, "slot": 4},
            {"tid": "invalid", "lv": 400, "combat": 10200, "slot": 5},
        ]
        payload = {"code": 0, "msg": "ok", "data": {"list": raw_list}}
        record = self.builder.build(self.stage, payload)
        self.assertEqual(record.status, ClearLineupStatus.ERROR)
        self.assertEqual(record.status_message, "历史阵容数据结构异常，请稍后重试")

    def test_strict_lineup_validation_only_slots_missing_required_fields(self):
        raw_list = [
            {"slot": 1},
            {"slot": 2},
            {"slot": 3},
            {"slot": 4},
            {"slot": 5},
        ]
        payload = {"code": 0, "msg": "ok", "data": {"list": raw_list}}
        record = self.builder.build(self.stage, payload)
        self.assertEqual(record.status, ClearLineupStatus.ERROR)
        self.assertEqual(record.status_message, "历史阵容数据结构异常，请稍后重试")

    def test_strict_lineup_validation_one_item_missing_combat(self):
        raw_list = [
            {"tid": 101, "lv": 400, "combat": 120000, "slot": 1},
            {"tid": 102, "lv": 400, "combat": 115000, "slot": 2},
            {"tid": 103, "lv": 400, "slot": 3},
            {"tid": 104, "lv": 400, "combat": 95000, "slot": 4},
            {"tid": 105, "lv": 400, "combat": 102000, "slot": 5},
        ]
        payload = {"code": 0, "msg": "ok", "data": {"list": raw_list}}
        record = self.builder.build(self.stage, payload)
        self.assertEqual(record.status, ClearLineupStatus.ERROR)
        self.assertEqual(record.status_message, "历史阵容数据结构异常，请稍后重试")

    def test_strict_lineup_validation_one_item_invalid_lv(self):
        raw_list = [
            {"tid": 101, "lv": 400, "combat": 120000, "slot": 1},
            {"tid": 102, "lv": None, "combat": 115000, "slot": 2},
            {"tid": 103, "lv": 400, "combat": 118000, "slot": 3},
            {"tid": 104, "lv": 400, "combat": 95000, "slot": 4},
            {"tid": 105, "lv": 400, "combat": 102000, "slot": 5},
        ]
        payload = {"code": 0, "msg": "ok", "data": {"list": raw_list}}
        record = self.builder.build(self.stage, payload)
        self.assertEqual(record.status, ClearLineupStatus.ERROR)
        self.assertEqual(record.status_message, "历史阵容数据结构异常，请稍后重试")

    def test_strict_lineup_validation_6_items_with_1_malformed_cannot_silently_fallback(self):
        raw_list = [
            {"tid": 101, "lv": 400, "combat": 120000, "slot": 1},
            {"tid": 102, "lv": 400, "combat": 115000, "slot": 2},
            {"tid": 103, "lv": 400, "combat": 118000, "slot": 3},
            {"tid": 104, "lv": 400, "combat": 95000, "slot": 4},
            {"tid": 105, "lv": 400, "combat": 102000, "slot": 5},
            {"tid": 999, "lv": "invalid", "combat": 0, "slot": 6},
        ]
        payload = {"code": 0, "msg": "ok", "data": {"list": raw_list}}
        record = self.builder.build(self.stage, payload)
        self.assertEqual(record.status, ClearLineupStatus.ERROR)
        self.assertEqual(record.status_message, "历史阵容数据结构异常，请稍后重试")

    def test_strict_lineup_validation_normal_5_members_available(self):
        raw_list = [
            {"tid": 101, "lv": 400, "combat": 120000, "slot": 1},
            {"tid": 102, "lv": 400, "combat": 115000, "slot": 2},
            {"tid": 103, "lv": 400, "combat": 118000, "slot": 3},
            {"tid": 104, "lv": 400, "combat": 95000, "slot": 4},
            {"tid": 105, "lv": 400, "combat": 102000, "slot": 5},
        ]
        payload = {"code": 0, "msg": "ok", "data": {"list": raw_list}}
        record = self.builder.build(self.stage, payload)
        self.assertEqual(record.status, ClearLineupStatus.AVAILABLE)
        self.assertEqual(len(record.members), 5)
        self.assertEqual(record.status_message, "")


class CampaignHistoryRendererTests(unittest.TestCase):
    def test_renderer_generates_1400px_card(self):
        with tempfile.TemporaryDirectory() as td:
            output_dir = Path(td) / "cards"
            output_dir.mkdir(parents=True, exist_ok=True)
            font_dir = Path(__file__).resolve().parents[1] / "fonts"

            renderer = CampaignHistoryRenderer(output_dir, font_dir)

            members = [
                StageClearMember(tid=1, level=400, combat=100000, slot=i, name_cn=f"妮姬{i}")
                for i in range(1, 6)
            ]
            record = StageClearRecord(
                mode="NORMAL",
                chapter=46,
                stage_name="46-40",
                stage_id=6046044,
                status=ClearLineupStatus.AVAILABLE,
                members=members,
                commander_name="指挥官",
                fetched_at="2026-09-05 15:00",
                plugin_version="0.3.0",
            )
            path = renderer.render_campaign_history(record)
            self.assertTrue(Path(path).is_file())

            with Image.open(path) as img:
                self.assertEqual(img.width, 1400)
                self.assertEqual(img.height, 820)

    def test_renderer_generates_empty_state_card(self):
        with tempfile.TemporaryDirectory() as td:
            output_dir = Path(td) / "cards"
            output_dir.mkdir(parents=True, exist_ok=True)
            font_dir = Path(__file__).resolve().parents[1] / "fonts"

            renderer = CampaignHistoryRenderer(output_dir, font_dir)
            record = StageClearRecord(
                mode="HARD",
                chapter=35,
                stage_name="35-36",
                stage_id=6135041,
                status=ClearLineupStatus.UNAVAILABLE,
                status_message="该关卡暂无可查询的历史阵容",
                members=[],
                commander_name="指挥官",
                fetched_at="2026-09-05 15:00",
                plugin_version="0.3.0",
            )
            path = renderer.render_campaign_history(record)
            self.assertTrue(Path(path).is_file())

            with Image.open(path) as img:
                self.assertEqual(img.width, 1400)
                self.assertEqual(img.height, 540)


class CampaignClientToBuilderIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_client_to_builder_with_full_official_response(self):
        from unittest.mock import AsyncMock
        from astrbot_plugin_nikke.client import BlaBlaClient

        client = BlaBlaClient()
        official_response = {
            "code": 0,
            "msg": "ok",
            "data": {
                "list": [
                    {"tid": 101, "lv": 400, "combat": 120000, "slot": 1},
                    {"tid": 102, "lv": 400, "combat": 115000, "slot": 2},
                    {"tid": 103, "lv": 400, "combat": 118000, "slot": 3},
                    {"tid": 104, "lv": 400, "combat": 95000, "slot": 4},
                    {"tid": 105, "lv": 400, "combat": 102000, "slot": 5},
                ]
            },
        }
        client._community_request = AsyncMock(return_value=official_response)

        account = {"cookie": "game_uid=1; game_openid=abc", "game_openid": "abc", "area_id": "1"}
        res = await client.get_main_quest_clear_lineup(account, stage_id=6046044, area_id=1)

        # 验证 Client 成功时直接返回完整响应，绝无多层包裹
        self.assertEqual(res["code"], 0)
        self.assertIn("list", res["data"])

        directory = [
            {"name_code": 101, "name_cn": "爱丽丝", "name_en": "Alice", "resource_id": "c101"},
            {"name_code": 102, "name_cn": "红莲", "name_en": "Scarlet", "resource_id": "c102"},
            {"name_code": 103, "name_cn": "黑莲", "name_en": "Scarlet: Black Shadow", "resource_id": "c103"},
            {"name_code": 104, "name_cn": "丽塔", "name_en": "Liter", "resource_id": "c104"},
            {"name_code": 105, "name_cn": "娜嘉", "name_en": "Naga", "resource_id": "c105"},
        ]
        builder = CampaignHistoryBuilder(directory)
        stage = CampaignStage(mode="NORMAL", chapter=46, name="46-40", stage_id=6046044)
        record = builder.build(stage, res, commander_name="测试指挥官")

        self.assertEqual(record.status, ClearLineupStatus.AVAILABLE)
        self.assertEqual(len(record.members), 5)
        self.assertEqual(record.total_combat, 120000 + 115000 + 118000 + 95000 + 102000)
        self.assertEqual(record.total_combat, 550000)


if __name__ == "__main__":
    unittest.main()
