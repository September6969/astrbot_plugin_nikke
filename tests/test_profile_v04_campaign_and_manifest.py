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
                self.assertLessEqual(image.height, 2200)
                self.assertEqual(image.width, 1200)


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
