# SPDX-License-Identifier: GPL-3.0-or-later

import asyncio
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from PIL import Image

from astrbot_plugin_nikke.asset_manager import AssetManager
from astrbot_plugin_nikke.client import BlaBlaClient, BlaBlaError, DAILY_CONTENTS_PROGRESS, PROFILE
from astrbot_plugin_nikke.currency_registry import CurrencyDefinition, CurrencyRegistry
from astrbot_plugin_nikke.profile_builder import ProfileBuilder
from astrbot_plugin_nikke.profile_card_renderer import ProfileCardRenderer
from astrbot_plugin_nikke.profile_models import ProfileDashboardData
from astrbot_plugin_nikke.spine_prerenderer import SpinePreRenderer
from astrbot_plugin_nikke.scripts import capture_campaign_history as capture
from astrbot_plugin_nikke.scripts import sync_spine_assets as sync


class ProfileV04ContractTests(unittest.TestCase):
    def build(self, *, basic=None, outpost=None, daily=None, daily_available=True):
        return ProfileBuilder().build(
            account={"area_id": "3"},
            basic=basic or {},
            outpost=outpost or {},
            roster=[],
            daily=daily,
            daily_available=daily_available,
            fetched_at="2026-09-11 12:00",
            plugin_version="test",
        )

    def test_daily_currency_memorial_and_simulation_contracts(self):
        data = self.build(
            basic={
                "currencies": [
                    {"type": 99, "value": 26_000_000},
                    {"type": 1000, "value": 130_000_000},
                    {"type": 2000, "value": 10_497},
                    {"type": 3000, "value": 999},
                    {"type": 5100, "value": 1},
                    {"type": 5200, "value": 2},
                    {"type": 11000, "value": 3},
                    {"type": 12000, "value": 4},
                ],
                "sim_room_overclock_current_sub_season_high_score": 88,
                "sim_room_overclock_latest_season_high_score": 99,
            },
            outpost={
                "memorial_counts": [
                    {"category": "HandWriting", "count": 2},
                    {"category": "CallLog", "count": 3},
                    {"category": "Data", "count": 4},
                    {"category": "OldTales", "count": 5},
                    {"category": "UnbreakableSphere", "count": 6},
                ],
                "jukebox_count": 7,
            },
            daily={
                "outpost_battle_storage_fullness": 0.059,
                "intercept_remaining_tickets": 0,
                "counsel_remaining_count": 2,
                "rookie_arena_remaining_count": 1,
                "special_arena_remaining_count": 3,
                "dispatch_completed_count": 4,
                "dispatch_in_progress_count": 5,
                "tower_daily_info_list": [{"type": "verified-tower", "remaining": 1}],
                "sim_room_daily_best_record": {"chapter": 3, "difficulty": 5},
            },
        )
        self.assertEqual(data.storage_fullness, 0.059)
        self.assertEqual(data.intercept_remaining, 0)
        self.assertEqual(data.sim_room_daily_record.display_label, "5-C")
        self.assertNotIn("5-3", data.sim_room_daily_record.display_label)
        self.assertEqual([item.compact_value for item in data.currencies[:4]], ["26M", "130M", "10.5K", "999"])
        self.assertEqual(
            [item.display_name for item in data.currencies],
            ["珠宝", "战斗数据辑", "信用点", "芯尘", "普通招募券", "高级招募券", "躯体标签", "黄金积分券"],
        )
        self.assertEqual([item.count for item in data.memorial_summary], [2, 3, 15, 7])
        self.assertEqual([item.display_name for item in data.memorial_summary], ["手机", "通话记录", "数据资料", "BGM"])
        self.assertEqual(data.sim_room_overclock_subseason, "88")
        self.assertEqual(data.sim_room_overclock_season, "99")

    def test_invalid_capacity_is_safe_and_unknown_memorial_is_not_reclassified(self):
        self.assertEqual(ProfileCardRenderer._storage_percent(0), 0.0)
        self.assertEqual(ProfileCardRenderer._storage_percent(1), 100.0)
        self.assertEqual(ProfileCardRenderer._storage_percent(0.059), 5.9)
        self.assertIsNone(ProfileCardRenderer._storage_percent(1.1))
        self.assertIsNone(ProfileCardRenderer._storage_percent("invalid"))
        data = self.build(outpost={"memorial_counts": [{"category": "not-verified", "count": 99}]})
        self.assertIsNone(data.memorial_summary)
        self.assertTrue(data.memorial_partial)

    def test_invalid_jukebox_is_partial_and_not_zero(self):
        data = self.build(outpost={"jukebox_count": "NaN"})
        self.assertIsNone(data.memorial_summary)
        self.assertTrue(data.memorial_partial)

    def test_tower_daily_uses_opened_remaining_count_not_list_length(self):
        data = self.build(
            daily={
                "tower_daily_info_list": [
                    {"type": 1, "is_opened": False, "remaining_count": 3},
                    {"type": 2, "is_opened": True, "remaining_count": 3},
                    {"type": 3, "is_opened": False, "remaining_count": 3},
                    {"type": 4, "is_opened": False, "remaining_count": 3},
                ]
            }
        )
        self.assertFalse(data.daily_partial)
        self.assertEqual(ProfileCardRenderer._tower_value(data), "剩余 3 次")

        incomplete = self.build(daily={"tower_daily_info_list": [{"type": 2, "remaining_count": 3}]})
        self.assertEqual(ProfileCardRenderer._tower_value(incomplete), "次数待核验")

    def test_profile_v04_sections_and_height_are_bounded(self):
        data = self.build(
            basic={"currencies": [{"type": 99, "value": 26_000_000}]},
            outpost={"memorial_counts": [{"category": "HandWriting", "count": 1}]},
            daily={
                "outpost_battle_storage_fullness": 0.5,
                "intercept_remaining_tickets": 1,
                "counsel_remaining_count": 2,
                "rookie_arena_remaining_count": 3,
                "special_arena_remaining_count": 4,
                "dispatch_completed_count": 5,
                "dispatch_in_progress_count": 6,
                "tower_daily_info_list": [],
                "sim_room_daily_best_record": {"chapter": 3, "difficulty": 5},
            },
        )
        with tempfile.TemporaryDirectory() as directory:
            renderer = ProfileCardRenderer(Path(directory), Path(__file__).resolve().parents[1] / "fonts")
            with patch.object(renderer, "_section_panel", wraps=renderer._section_panel) as panel:
                output = renderer.render_profile(data)
            titles = [item.args[2] for item in panel.call_args_list]
            self.assertIn("TODAY / 今日状态", titles)
            self.assertIn("COLLECTION / 遗失物品", titles)
            self.assertIn("RESOURCES / 我的资源", titles)
            with Image.open(output) as image:
                self.assertLessEqual(image.height, 1850)
                self.assertEqual(image.width, 1200)

    def test_currency_icon_registry_is_explicit_and_local_only(self):
        coverage = CurrencyRegistry.icon_coverage()
        self.assertEqual(coverage["total"], 8)
        self.assertEqual(coverage["verified"], 8)
        self.assertEqual(coverage["unverified"], 0)
        self.assertEqual(coverage["unverified_types"], [])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manager = AssetManager(root / "cache", root, remote=True)
            try:
                with patch("astrbot_plugin_nikke.asset_manager.httpx.stream", side_effect=AssertionError("currency icon network")):
                    self.assertIsNone(manager.get_currency_icon(99))

                icon = root / "cache" / "currency" / "gem.png"
                icon.parent.mkdir(parents=True)
                Image.new("RGBA", (16, 16), "gold").save(icon)
                definition = CurrencyDefinition(
                    99,
                    "珠宝",
                    "gem",
                    "offline-test",
                    hashlib.sha256(icon.read_bytes()).hexdigest(),
                )
                with patch.dict(CurrencyRegistry.DEFINITIONS, {99: definition}):
                    loaded = manager.get_currency_icon(99)
                self.assertIsNotNone(loaded)
                self.assertEqual(loaded.size, (16, 16))
            finally:
                manager.close()

    def test_profile_renderer_pastes_verified_currency_icon(self):
        data = self.build(
            basic={"currencies": [{"type": 1000, "value": 130_000_000}]},
            outpost={},
            daily={},
        )
        with tempfile.TemporaryDirectory() as directory:
            icon = Image.new("RGBA", (24, 24), (255, 64, 32, 220))
            renderer = ProfileCardRenderer(
                Path(directory),
                Path(__file__).resolve().parents[1] / "fonts",
                currency_icon_provider=lambda _currency_type: icon,
            )
            output = renderer.render_profile(data)
            with Image.open(output) as rendered:
                self.assertEqual(rendered.width, 1200)
                self.assertLessEqual(rendered.height, 1850)

        with tempfile.TemporaryDirectory() as directory:
            assets = Path(__file__).resolve().parents[1] / "assets"
            manager = AssetManager(Path(directory) / "cache", assets, remote=True)
            try:
                with patch("astrbot_plugin_nikke.asset_manager.httpx.stream", side_effect=AssertionError("currency icon network")):
                    loaded = manager.get_currency_icon(1000)
                self.assertIsNotNone(loaded)
                self.assertEqual(loaded.size, (105, 96))
                self.assertEqual(manager.get_currency_icon(99).size, (53, 57))
            finally:
                manager.close()

    def test_profile_renderer_omits_unidentified_currency_from_card(self):
        currencies = [{"type": item, "value": item} for item in CurrencyRegistry.DEFINITIONS]
        currencies.insert(0, {"type": 98, "value": 16})
        data = self.build(basic={"currencies": currencies}, outpost={}, daily={})
        with tempfile.TemporaryDirectory() as directory:
            renderer = ProfileCardRenderer(Path(directory), Path(__file__).resolve().parents[1] / "fonts")
            with patch.object(renderer, "_text", wraps=renderer._text) as text:
                output = renderer.render_profile(data)
            labels = [str(call.args[2]) for call in text.call_args_list]
            self.assertEqual(len(data.currencies), 9)  # 底层数据不丢失。
            self.assertNotIn("未知资源", labels)
            self.assertIn("黄金积分券", labels)
            with Image.open(output) as rendered:
                self.assertLessEqual(rendered.height, 1850)


class ProfileDailyClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_daily_is_fourth_independent_read(self):
        calls = []

        async def post(path, cookie, payload):
            calls.append(path)
            if path == PROFILE:
                return {"data": {"basic_info": {"nickname": "合成账号"}}}
            if path == DAILY_CONTENTS_PROGRESS:
                raise BlaBlaError("daily unavailable", code="212000", endpoint=path)
            if path.endswith("GetUserProfileOutpostInfo"):
                return {"data": {"outpost_info": {"synchro_level": 1}}}
            return {"data": {"characters": []}}

        client = BlaBlaClient()
        client._post = AsyncMock(side_effect=post)
        result = await client.get_profile_dashboard(
            {"cookie": "synthetic-cookie", "area_id": "3", "game_openid": "synthetic-openid"}
        )
        self.assertEqual(len(calls), 4)
        self.assertFalse(result["daily_available"])
        self.assertEqual(result["roster"], [])
        self.assertEqual(result["outpost"]["synchro_level"], 1)


class SpineManifestHotPathTests(unittest.TestCase):
    def test_v2_manifest_hash_is_used_without_network_or_worker(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rendered = root / "spine-rendered"
            rendered.mkdir()
            image_path = rendered / "c010.png"
            Image.new("RGBA", (32, 48), "red").save(image_path)
            manifest = {
                "schema_version": 2,
                "assets": {
                    "c010": {
                        "asset_id": "c010",
                        "rendered_png": "c010.png",
                        "sha256": hashlib.sha256(image_path.read_bytes()).hexdigest(),
                    }
                },
            }
            (root / "spine_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            manager = AssetManager(root / "cache", root, remote=True)
            try:
                with patch("astrbot_plugin_nikke.asset_manager.httpx.stream", side_effect=AssertionError("network")), patch.object(
                    SpinePreRenderer, "cached_portrait", side_effect=AssertionError("worker cache")
                ):
                    portrait = manager.get_character_portrait("5010", "10")
                self.assertEqual(portrait.size, (32, 48))
            finally:
                manager.close()

    def test_manifest_hash_or_path_escape_falls_back(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rendered = root / "spine-rendered"
            rendered.mkdir()
            image_path = rendered / "c010.png"
            Image.new("RGBA", (32, 48), "red").save(image_path)
            payload = {"schema_version": 2, "assets": {"c010": {"rendered_png": "../outside.png", "sha256": "0" * 64}}}
            (root / "spine_manifest.json").write_text(json.dumps(payload), encoding="utf-8")
            manager = AssetManager(root / "cache", root, remote=True)
            try:
                portrait = manager.get_character_portrait("5010", "10")
                self.assertEqual(portrait.size, (600, 900))
            finally:
                manager.close()

    def test_declared_manifest_invalid_asset_is_fail_closed_before_legacy_cache(self):
        """manifest 一旦声明角色，损坏条目不能绕过合同命中旧缓存或 Worker。"""
        invalid_entries = (
            {"rendered_png": "../outside.png", "sha256": "0" * 64},
            {"rendered_png": "missing.png", "sha256": "0" * 64},
            {"rendered_png": "c010.png", "sha256": "f" * 64},
            {"rendered_png": "c010.png"},
            [],
        )
        for entry in invalid_entries:
            with self.subTest(entry=entry), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                rendered = root / "spine-rendered"
                legacy = root / "cache" / "spine-rendered"
                rendered.mkdir(parents=True)
                legacy.mkdir(parents=True)
                legacy_path = legacy / "c010.png"
                Image.new("RGBA", (32, 48), "red").save(legacy_path)
                declared_path = rendered / "c010.png"
                Image.new("RGBA", (32, 48), "blue").save(declared_path)
                manifest = {"schema_version": 2, "assets": {"c010": entry}}
                manifest_path = root / "spine_manifest.json"
                manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
                manager = AssetManager(root / "cache", root, remote=True)
                try:
                    with self.assertLogs("nikke.asset_manager", level="WARNING") as logs, patch.object(
                        SpinePreRenderer,
                        "cached_portrait",
                        side_effect=AssertionError("invalid manifest must not inspect Worker cache"),
                    ):
                        portrait = manager.get_character_portrait("5010", "10")
                    self.assertEqual(portrait.size, (600, 900))
                    self.assertNotEqual(portrait.getpixel((0, 0)), (255, 0, 0, 255))
                    self.assertIn("STATIC_SPINE_ASSET_INVALID", "\n".join(logs.output))
                finally:
                    manager.close()

    def test_static_manifest_hot_path_does_not_touch_network_or_worker(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rendered = root / "spine-rendered"
            rendered.mkdir()
            image_path = rendered / "c010.png"
            Image.new("RGBA", (32, 48), "green").save(image_path)
            manifest = {
                "schema_version": 2,
                "assets": {
                    "c010": {
                        "asset_id": "c010",
                        "rendered_png": "c010.png",
                        "sha256": hashlib.sha256(image_path.read_bytes()).hexdigest(),
                    }
                },
            }
            (root / "spine_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            manager = AssetManager(root / "cache", root, remote=True)
            try:
                with patch("astrbot_plugin_nikke.asset_manager.httpx.stream", side_effect=AssertionError("network")), patch.object(
                    SpinePreRenderer, "cached_portrait", side_effect=AssertionError("worker cache")
                ), patch.object(SpinePreRenderer, "enqueue", side_effect=AssertionError("worker enqueue")):
                    portrait = manager.get_character_portrait("5010", "10")
                self.assertEqual(portrait.size, (32, 48))
            finally:
                manager.close()


class SpineSyncTests(unittest.TestCase):
    def test_all_targets_accept_only_verified_costume_entries(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            assets = root / "assets"
            assets.mkdir()
            (assets / "character_master.json").write_text(
                json.dumps({"characters": [{"spine_asset_id": "c010"}, {"spine_asset_id": "not-valid"}]}),
                encoding="utf-8",
            )
            (assets / "costumes.json").write_text(
                json.dumps({"schema_version": 2, "entries": [
                    {"spine_asset_id": "c010_03", "source": "table", "source_sha256": "a" * 64, "verified_at": "2026-09-11"},
                    {"spine_asset_id": "c011_01", "source": "table", "source_sha256": "bad", "verified_at": "2026-09-11"},
                ]}),
                encoding="utf-8",
            )
            targets, defaults, costumes = sync.enumerate_targets(root, all_targets=True)
            self.assertEqual(defaults, ["c010"])
            self.assertEqual(costumes, ["c010_03"])
            self.assertEqual(targets, ["c010", "c010_03"])

    def test_sync_writes_manifest_v2_and_coverage(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            db = root / "db" / "l2d" / "c010"
            db.mkdir(parents=True)
            (db / "c010_00.skel").write_bytes(b"header 4.0.47")
            Image.new("RGBA", (12, 12), "green").save(db / "page.png")
            (db / "c010_00.atlas").write_text("page.png\nsize: 12, 12\n", encoding="utf-8-sig")
            output = root / "out"
            manifest_path = root / "manifest.json"
            coverage_path = root / "coverage.json"

            def fake_render(_asset, _skel, _atlas, _textures, destination, *_workers, **_kwargs):
                Image.new("RGBA", (20, 30), "blue").save(destination)
                return {"runtime_version": "4.0"}

            with patch.object(sync, "render_spine_portrait", side_effect=fake_render):
                code = sync.main([
                    "--assets", "c010", "--nikke-db-root", str(root / "db"),
                    "--out-dir", str(output), "--manifest-path", str(manifest_path),
                    "--coverage-report", str(coverage_path),
                ])
            self.assertEqual(code, 0)
            saved = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["schema_version"], 2)
            self.assertEqual(saved["assets"]["c010"]["runtime_version"], "4.0")
            self.assertEqual(json.loads(coverage_path.read_text(encoding="utf-8"))["render_success"], 1)

    def test_sync_reports_invalid_existing_manifest_separately(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            db = root / "db" / "l2d" / "c010"
            db.mkdir(parents=True)
            (db / "c010_00.skel").write_bytes(b"header 4.0.47")
            Image.new("RGBA", (12, 12), "green").save(db / "page.png")
            (db / "c010_00.atlas").write_text("page.png\nsize: 12, 12\n", encoding="utf-8-sig")
            output = root / "out"
            output.mkdir()
            old_png = output / "c010.png"
            Image.new("RGBA", (20, 30), "red").save(old_png)
            manifest_path = root / "manifest.json"
            manifest_path.write_text(
                json.dumps({
                    "schema_version": 2,
                    "assets": {
                        "c010": {
                            "asset_id": "c010",
                            "rendered_png": "c010.png",
                            "sha256": "0" * 64,
                        }
                    },
                }),
                encoding="utf-8",
            )
            coverage_path = root / "coverage.json"

            def fake_render(_asset, _skel, _atlas, _textures, destination, *_workers, **_kwargs):
                Image.new("RGBA", (20, 30), "blue").save(destination)
                return {"runtime_version": "4.0"}

            with patch.object(sync, "render_spine_portrait", side_effect=fake_render):
                code = sync.main([
                    "--assets", "c010", "--nikke-db-root", str(root / "db"),
                    "--out-dir", str(output), "--manifest-path", str(manifest_path),
                    "--coverage-report", str(coverage_path),
                ])
            self.assertEqual(code, 0)
            coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
            self.assertEqual(coverage["render_invalid"], 1)
            self.assertEqual(coverage["render_invalid_ids"], ["c010"])
            self.assertEqual(coverage["render_success"], 1)


class CampaignCaptureTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def stage_file(root: Path, *, hard: bool = True) -> Path:
        payload = {"NORMAL": {"1": {"1-1": 6001001}}, "HARD": {"1": {"1-1": 7001001}} if hard else {}}
        path = root / "stages.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    async def test_capture_is_private_and_builds_tid_costume_inventory(self):
        class FakeClient:
            def __init__(self):
                self.calls = []

            async def get_main_quest_clear_lineup(self, account, stage_id, area_id):
                self.calls.append(stage_id)
                if stage_id == 7001001:
                    return {"code": 1300017, "msg": "private openid should not be saved", "data": None}
                return {"code": 0, "data": {"list": [
                    {"tid": 101, "lv": 400, "combat": 10, "slot": 1, "costume_id": "10005"},
                    {"tid": 102, "lv": 400, "combat": 20, "slot": 2},
                    {"tid": 103, "lv": 400, "combat": 30, "slot": 3},
                    {"tid": 104, "lv": 400, "combat": 40, "slot": 4},
                    {"tid": 99999999, "lv": 400, "combat": 50, "slot": 5},
                ]}}

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake = FakeClient()
            result = await capture.capture(
                root / "data", root / "out", stage_file=self.stage_file(root),
                account={"area_id": "1", "cookie": "SECRET_COOKIE", "game_openid": "SECRET_OPENID"},
                client=fake, sleep=AsyncMock(), jitter=lambda *_: 0,
            )
            self.assertEqual(result["total_count"], 2)
            content = "".join(path.read_text(encoding="utf-8") for path in (root / "out").glob("*.json*"))
            self.assertNotIn("SECRET_COOKIE", content)
            self.assertNotIn("SECRET_OPENID", content)
            tid_inventory = json.loads((root / "out" / capture.TID_INVENTORY_NAME).read_text(encoding="utf-8"))
            self.assertEqual(tid_inventory["unresolved"], 1)
            self.assertTrue(any(item["raw_tid"] == 99999999 for item in tid_inventory["entries"]))
            normal_line = json.loads((root / "out" / capture.NORMAL_SNAPSHOT).read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(normal_line["total_combat"], 150)
            self.assertEqual(normal_line["members"][0]["costume_id"], "10005")

    async def test_bounded_concurrency_keeps_single_writer_snapshot_complete(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stage_file = root / "stages.json"
            stage_file.write_text(json.dumps({
                "NORMAL": {"1": {f"1-{index}": 6001000 + index for index in range(1, 7)}},
                "HARD": {},
            }), encoding="utf-8")

            class ConcurrentClient:
                def __init__(self):
                    self.active = 0
                    self.maximum = 0

                async def get_main_quest_clear_lineup(self, account, stage_id, area_id):
                    self.active += 1
                    self.maximum = max(self.maximum, self.active)
                    await asyncio.sleep(0.01)
                    self.active -= 1
                    return {"code": 1300017, "data": None}

            client = ConcurrentClient()
            result = await capture.capture(
                root / "data", root / "out", stage_file=stage_file,
                account={"area_id": "1"}, client=client, sleep=AsyncMock(),
                jitter=lambda *_: 0, concurrency=3,
            )
            rows = (root / "out" / capture.NORMAL_SNAPSHOT).read_text(encoding="utf-8").splitlines()
            self.assertEqual(client.maximum, 3)
            self.assertEqual(result["request_count"], 6)
            self.assertEqual(len(rows), 6)
            self.assertEqual(len({json.loads(row)["stage_id"] for row in rows}), 6)

            with self.assertRaisesRegex(ValueError, "1–4"):
                await capture.capture(
                    root / "data", root / "invalid", stage_file=stage_file,
                    account={"area_id": "1"}, client=client, concurrency=5,
                )

    async def test_resume_force_and_rate_limit_backoff(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stage_file = self.stage_file(root, hard=False)

            class FakeClient:
                def __init__(self):
                    self.calls = 0

                async def get_main_quest_clear_lineup(self, account, stage_id, area_id):
                    self.calls += 1
                    return {"code": 0, "data": {"list": [
                        {"tid": 101, "lv": 1, "combat": 1, "slot": slot} for slot in range(1, 6)
                    ]}}

            fake = FakeClient()
            common = dict(stage_file=stage_file, account={"area_id": "1"}, client=fake, sleep=AsyncMock(), jitter=lambda *_: 0)
            await capture.capture(root / "data", root / "out", **common)
            await capture.capture(root / "data", root / "out", resume=True, **common)
            self.assertEqual(fake.calls, 1)
            await capture.capture(root / "data", root / "out", force=True, **common)
            self.assertEqual(fake.calls, 2)

            sleeps = []

            async def record_sleep(value):
                sleeps.append(value)

            class RateClient:
                async def get_main_quest_clear_lineup(self, account, stage_id, area_id):
                    return {"code": 212000, "data": None}

            limited = await capture.capture(
                root / "data", root / "limited", stage_file=stage_file,
                account={"area_id": "1"}, client=RateClient(), sleep=record_sleep,
                jitter=lambda *_: 0, max_rate_retries=2,
            )
            self.assertEqual(limited["stopped_reason"], "RATE_LIMITED")
            self.assertEqual(sleeps, [5.0, 10.0])

    async def test_resume_retries_malformed_and_filters_stale_stage_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stage_file = self.stage_file(root, hard=False)
            output = root / "out"
            output.mkdir()
            old_rows = [
                {
                    "mode": "NORMAL",
                    "chapter": 1,
                    "stage_name": "1-1",
                    "stage_id": 6001001,
                    "status": "malformed",
                    "members": [],
                },
                {
                    "mode": "NORMAL",
                    "chapter": 99,
                    "stage_name": "99-9",
                    "stage_id": 9999999,
                    "status": "unavailable",
                    "members": [],
                },
            ]
            (output / capture.NORMAL_SNAPSHOT).write_text(
                "".join(json.dumps(row) + "\n" for row in old_rows), encoding="utf-8"
            )

            class FakeClient:
                def __init__(self):
                    self.calls = []

                async def get_main_quest_clear_lineup(self, account, stage_id, area_id):
                    self.calls.append(stage_id)
                    return {"code": 0, "data": {"list": [
                        {"tid": 101, "lv": 1, "combat": 1, "slot": slot}
                        for slot in range(1, 6)
                    ]}}

            fake = FakeClient()
            result = await capture.capture(
                root / "data", output, stage_file=stage_file, resume=True,
                account={"area_id": "1"}, client=fake, sleep=AsyncMock(), jitter=lambda *_: 0,
            )
            self.assertEqual(fake.calls, [6001001])
            self.assertEqual(result["total_count"], 1)
            saved = [
                json.loads(line)
                for line in (output / capture.NORMAL_SNAPSHOT).read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual([row["stage_id"] for row in saved], [6001001])
            self.assertEqual(result["status_counts"]["available"], 1)
            unresolved = json.loads((output / capture.TID_UNRESOLVED_NAME).read_text(encoding="utf-8"))
            self.assertEqual(unresolved["unresolved"], 0)

    def test_replay_normalizes_untrusted_timestamp_without_copying_text(self):
        row = {
            "mode": "NORMAL",
            "chapter": 1,
            "stage_name": "1-1",
            "stage_id": 6001001,
            "captured_at": "COOKIE=SECRET",
            "api_code": 0,
            "status": "available",
            "members": [],
        }
        normalized = capture._normalize_snapshot(row)
        self.assertIsNotNone(normalized)
        self.assertEqual(normalized["captured_at"], "")
        self.assertNotIn("SECRET", json.dumps(normalized))
