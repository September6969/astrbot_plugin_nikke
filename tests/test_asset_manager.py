import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from PIL import Image

from astrbot_plugin_nikke.asset_manager import AssetManager


class AssetManagerTests(unittest.TestCase):
    def test_game_resource_url_matches_official_cdn_path_contract(self):
        self.assertEqual(
            AssetManager.game_resource_url("icon/equip/icn_equipment_head_attacker_t9_3.webp"),
            "https://sg-tools-cdn.blablalink.com/ct-58/xq-81/f1333fe625de471b7221f89b15e48242.webp",
        )

    def test_cache_wins_and_corrupt_cache_falls_back_to_project(self):
        with tempfile.TemporaryDirectory() as td:
            cache, assets = Path(td) / "cache", Path(td) / "assets"
            for root, color in [(cache, "red"), (assets, "blue")]:
                (root / "portraits").mkdir(parents=True)
                Image.new("RGBA", (20, 20), color).save(root / "portraits/191.png")
            manager = AssetManager(cache, assets)
            self.assertEqual(manager.get_character_portrait("5004", "191").getpixel((0, 0)), (255, 0, 0, 255))
            (cache / "portraits/191.png").write_bytes(b"invalid")
            self.assertEqual(manager.get_character_portrait("5004", "191").getpixel((0, 0)), (0, 0, 255, 255))

    def test_missing_ids_and_network_errors_return_images(self):
        with tempfile.TemporaryDirectory() as td:
            manager = AssetManager(td, td, remote=True)
            with patch("astrbot_plugin_nikke.asset_manager.httpx.stream", side_effect=httpx.ConnectError("offline")) as request:
                for _ in range(2):
                    image = manager.get_character_portrait("unknown", "999999")
                    self.assertEqual(image.mode, "RGBA")
                    self.assertIsNotNone(image.getbbox())
                self.assertEqual(request.call_count, 1)
            for slot in ("head", "torso", "arm", "leg"):
                self.assertIsNotNone(manager.get_equipment_icon(slot, "../../absent").getbbox())

    def test_remote_asset_is_cached_and_reused(self):
        with tempfile.TemporaryDirectory() as td:
            buffer = io.BytesIO()
            Image.new("RGBA", (30, 50), "green").save(buffer, "PNG")
            response = httpx.Response(200, content=buffer.getvalue(), request=httpx.Request("GET", "https://example.com"))
            manager = AssetManager(td, td, remote=True)
            with patch("astrbot_plugin_nikke.asset_manager.httpx.stream") as stream:
                stream.return_value.__enter__.return_value = response
                self.assertEqual(manager.get_character_portrait("5004", "191").size, (30, 50))
                manager.get_character_portrait("5004", "191")
                self.assertEqual(stream.call_count, 1)

    def test_all_icon_fallbacks_and_invalid_sources(self):
        with tempfile.TemporaryDirectory() as td:
            manager = AssetManager(td, td)
            try:
                for method in (manager.get_favorite_item_icon, manager.get_cube_icon, manager.get_element_icon,
                               manager.get_corporation_icon, manager.get_weapon_icon, manager.get_burst_icon):
                    self.assertIsNotNone(method(None).getbbox())
            finally:
                manager.close()

    def test_favorite_item_and_cube_asset_chain_with_remote_cache(self):
        assets_dir = Path(__file__).resolve().parents[1] / "assets"
        with tempfile.TemporaryDirectory() as td:
            cache_dir = Path(td)
            manager = AssetManager(cache_dir, assets_dir, remote=True)
            try:
                self.assertIn("100602", manager.favorite_items_map)
                self.assertIn("1000304", manager.cubes_map)

                buffer = io.BytesIO()
                Image.new("RGBA", (45, 50), "yellow").save(buffer, "PNG")
                response = httpx.Response(200, content=buffer.getvalue(), request=httpx.Request("GET", "https://example.com"))

                with patch("astrbot_plugin_nikke.asset_manager.httpx.stream") as stream:
                    stream.return_value.__enter__.return_value = response
                    fav_img = manager.get_favorite_item_icon(100602)
                    self.assertEqual(fav_img.size, (45, 50))
                    # 缓存已写入本地
                    cached_file = cache_dir / "favorite" / "100602.png"
                    self.assertTrue(cached_file.is_file())

                    # 第二次调用命中本地缓存，不发起网络请求
                    manager.get_favorite_item_icon(100602)
                    self.assertEqual(stream.call_count, 1)

                    # 魔方同理
                    cube_img = manager.get_cube_icon(1000304)
                    self.assertEqual(cube_img.size, (45, 50))
                    self.assertTrue((cache_dir / "cube" / "1000304.png").is_file())

                # 未知 TID 安全返回 fallback
                fallback_fav = manager.get_favorite_item_icon(999999)
                self.assertIsNotNone(fallback_fav.getbbox())
                fallback_cube = manager.get_cube_icon(888888)
                self.assertIsNotNone(fallback_cube.getbbox())
            finally:
                manager.close()

    def test_resolve_character_assets_concurrent_prefetch(self):
        from astrbot_plugin_nikke.tests.test_card_builder import build_card

        assets_dir = Path(__file__).resolve().parents[1] / "assets"
        with tempfile.TemporaryDirectory() as td:
            manager = AssetManager(td, assets_dir)
            try:
                card = build_card()
                card_assets = manager.resolve_character_assets(card, timeout=5.0)

                self.assertIsNotNone(card_assets.portrait.getbbox())
                self.assertEqual(set(card_assets.equipment.keys()), {"head", "torso", "arm", "leg"})
                for slot, img in card_assets.equipment.items():
                    self.assertIsNotNone(img.getbbox())
                self.assertIsNotNone(card_assets.favorite_item.getbbox())
                self.assertIsNotNone(card_assets.cube.getbbox())
                self.assertIsNotNone(card_assets.element.getbbox())
                self.assertIsNotNone(card_assets.corporation.getbbox())
                self.assertIsNotNone(card_assets.weapon.getbbox())
                self.assertIsNotNone(card_assets.burst.getbbox())
            finally:
                manager.close()

    def test_resolve_character_assets_budget_timeout_falls_back_gracefully(self):
        import time
        from astrbot_plugin_nikke.tests.test_card_builder import build_card

        assets_dir = Path(__file__).resolve().parents[1] / "assets"
        with tempfile.TemporaryDirectory() as td:
            manager = AssetManager(td, assets_dir)
            try:
                card = build_card()

                def slow_favorite(tid):
                    time.sleep(1.0)
                    return Image.new("RGBA", (10, 10), "red")

                with patch.object(manager, "get_favorite_item_icon", side_effect=slow_favorite):
                    start = time.monotonic()
                    # 设定 0.2 秒硬预算
                    card_assets = manager.resolve_character_assets(card, timeout=0.2)
                    elapsed = time.monotonic() - start

                    # 总耗时应在 0.4 秒以内，绝不阻塞等待 slow_favorite 的 1.0 秒
                    self.assertLess(elapsed, 0.6)
                    # 超时素材降级为 fallback
                    self.assertIsNotNone(card_assets.favorite_item.getbbox())
                    self.assertEqual(card_assets.favorite_item.size, (128, 128))
            finally:
                manager.close()

    def test_spine_stays_experimental_production_does_not_queue_spine(self):
        assets_dir = Path(__file__).resolve().parents[1] / "assets"
        with tempfile.TemporaryDirectory() as td:
            manager = AssetManager(Path(td), assets_dir, remote=False)
            try:
                with patch.object(manager.spine, "is_available", return_value=True):
                    with patch.object(manager.spine.queue, "enqueue") as mock_enqueue:
                        # 生产出卡路径默认不投递
                        manager.get_character_portrait("101", "c101", allow_spine_enqueue=False)
                        mock_enqueue.assert_not_called()

                        # 显式允许时投递
                        manager.get_character_portrait("101", "c101", allow_spine_enqueue=True)
                        mock_enqueue.assert_called_once()
            finally:
                manager.close()

    def test_close_cancels_pending_tasks_in_executor(self):
        with tempfile.TemporaryDirectory() as td:
            manager = AssetManager(Path(td), Path(td), remote=False)
            executed = []
            def slow_task():
                import time
                time.sleep(0.1)
                executed.append("ran")

            # 占满 4 个 worker 并投递更多排队任务
            for _ in range(8):
                manager._executor.submit(slow_task)

            # 立即关闭，取消排队任务
            manager.close()
            import time
            time.sleep(0.2)
            # 队列中尚未开始的任务应被取消
            self.assertLess(len(executed), 8)

