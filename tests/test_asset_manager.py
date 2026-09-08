import io
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import MagicMock, patch

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

    def test_costume_portraits_use_distinct_remote_cache_keys(self):
        with tempfile.TemporaryDirectory() as td:
            manager = AssetManager(td, td, remote=True)
            manager.nikke_db.COSTUME_OVERRIDES.update({"skin_01": "c191_01", "skin_02": "c191_02"})
            responses = []
            for color in ("red", "blue"):
                payload = io.BytesIO()
                Image.new("RGBA", (30, 50), color).save(payload, "PNG")
                context = MagicMock()
                context.__enter__.return_value = httpx.Response(
                    200,
                    content=payload.getvalue(),
                    request=httpx.Request("GET", "https://example.com"),
                )
                responses.append(context)
            try:
                with patch("astrbot_plugin_nikke.asset_manager.httpx.stream", side_effect=responses) as stream:
                    first = manager.get_character_portrait("5004", "191", "skin_01")
                    second = manager.get_character_portrait("5004", "191", "skin_02")
                self.assertEqual(first.getpixel((0, 0)), (255, 0, 0, 255))
                self.assertEqual(second.getpixel((0, 0)), (0, 0, 255, 255))
                self.assertEqual(stream.call_count, 2)
                self.assertNotEqual(stream.call_args_list[0].args[1], stream.call_args_list[1].args[1])
            finally:
                manager.close()

    def test_unknown_or_invalid_costume_never_reuses_default_portrait(self):
        with tempfile.TemporaryDirectory() as td:
            manager = AssetManager(td, td, remote=True)
            (Path(td) / "portraits").mkdir(parents=True)
            Image.new("RGBA", (20, 20), "green").save(Path(td) / "portraits/191.png")
            try:
                with patch("astrbot_plugin_nikke.asset_manager.httpx.stream") as stream:
                    unknown = manager.get_character_portrait("5004", "191", "unknown_skin")
                    invalid = manager.get_character_portrait("5004", "191", True)
                self.assertNotEqual(unknown.getpixel((0, 0)), (0, 128, 0, 255))
                self.assertNotEqual(invalid.getpixel((0, 0)), (0, 128, 0, 255))
                stream.assert_not_called()
            finally:
                manager.close()

    def test_global_remote_download_limit_returns_fallback_without_cooldown(self):
        """不同实例、不同键共用限额；压力降级不能被写成五分钟失败。"""
        with tempfile.TemporaryDirectory() as td:
            first = AssetManager(Path(td) / "first", Path(td) / "assets", remote=True)
            second = AssetManager(Path(td) / "second", Path(td) / "assets", remote=True)
            entered = threading.Event()
            release = threading.Event()
            payload = io.BytesIO()
            Image.new("RGBA", (20, 20), "green").save(payload, "PNG")
            response = httpx.Response(200, content=payload.getvalue(), request=httpx.Request("GET", "https://example.com"))
            case = self

            class BlockingStream:
                def __enter__(self):
                    entered.set()
                    case.assertTrue(release.wait(2.0))
                    return response

                def __exit__(self, *_):
                    return False

            try:
                with patch.object(AssetManager, "_remote_download_slots", threading.BoundedSemaphore(1)):
                    with patch("astrbot_plugin_nikke.asset_manager.httpx.stream", side_effect=lambda *_args, **_kwargs: BlockingStream()) as stream:
                        with ThreadPoolExecutor(max_workers=1) as executor:
                            future = executor.submit(first._load, "portraits", "first", "https://example.com/first")
                            self.assertTrue(entered.wait(2.0))
                            started = time.monotonic()
                            self.assertIsNone(second._load("portraits", "second", "https://example.com/second"))
                            self.assertLess(time.monotonic() - started, 0.2)
                            self.assertNotIn("portraits/second.png", second._failed)
                            release.set()
                            self.assertEqual(future.result(timeout=3.0).size, (20, 20))

                        self.assertEqual(stream.call_count, 1)
            finally:
                release.set()
                first.close()
                second.close()

    def test_cached_asset_bypasses_global_remote_download_limit(self):
        with tempfile.TemporaryDirectory() as td:
            cache = Path(td) / "cache"
            (cache / "portraits").mkdir(parents=True)
            Image.new("RGBA", (20, 20), "blue").save(cache / "portraits/cached.png")
            manager = AssetManager(cache, Path(td) / "assets", remote=True)
            try:
                with patch.object(AssetManager, "_remote_download_slots", threading.BoundedSemaphore(1)) as slots:
                    self.assertTrue(slots.acquire(blocking=False))
                    try:
                        with patch("astrbot_plugin_nikke.asset_manager.httpx.stream") as stream:
                            image = manager._load("portraits", "cached", "https://example.com/cached")
                        self.assertEqual(image.getpixel((0, 0)), (0, 0, 255, 255))
                        stream.assert_not_called()
                    finally:
                        slots.release()
            finally:
                manager.close()

    def test_failed_remote_download_releases_global_slot(self):
        with tempfile.TemporaryDirectory() as td:
            manager = AssetManager(Path(td), Path(td) / "assets", remote=True)
            payload = io.BytesIO()
            Image.new("RGBA", (20, 20), "green").save(payload, "PNG")
            response = httpx.Response(
                200,
                content=payload.getvalue(),
                request=httpx.Request("GET", "https://example.com/second"),
            )
            success_context = MagicMock()
            success_context.__enter__.return_value = response

            try:
                with patch.object(AssetManager, "_remote_download_slots", threading.BoundedSemaphore(1)):
                    with patch(
                        "astrbot_plugin_nikke.asset_manager.httpx.stream",
                        side_effect=[httpx.ConnectError("offline"), success_context],
                    ) as stream:
                        self.assertIsNone(manager._load("portraits", "failed", "https://example.com/failed"))
                        image = manager._load("portraits", "second", "https://example.com/second")

                    self.assertEqual(image.size, (20, 20))
                    self.assertEqual(stream.call_count, 2)
            finally:
                manager.close()

    def test_concurrent_same_remote_asset_uses_single_flight_request(self):
        with tempfile.TemporaryDirectory() as td:
            buffer = io.BytesIO()
            Image.new("RGBA", (30, 50), "green").save(buffer, "PNG")
            response = httpx.Response(
                200,
                content=buffer.getvalue(),
                request=httpx.Request("GET", "https://example.com"),
            )
            manager = AssetManager(td, td, remote=True)
            entered = threading.Event()
            release = threading.Event()

            def enter_stream():
                entered.set()
                self.assertTrue(release.wait(2.0))
                return response

            try:
                with patch("astrbot_plugin_nikke.asset_manager.httpx.stream") as stream:
                    stream.return_value.__enter__.side_effect = enter_stream
                    with ThreadPoolExecutor(max_workers=5) as executor:
                        futures = [
                            executor.submit(manager.get_character_portrait, "5004", "191")
                            for _ in range(5)
                        ]
                        self.assertTrue(entered.wait(2.0))
                        time.sleep(0.05)
                        release.set()
                        images = [future.result(timeout=3.0) for future in futures]

                    self.assertEqual(stream.call_count, 1)
                    self.assertTrue(all(image.size == (30, 50) for image in images))
            finally:
                manager.close()

    def test_waiters_reuse_memory_result_when_cache_write_fails(self):
        with tempfile.TemporaryDirectory() as td:
            buffer = io.BytesIO()
            Image.new("RGBA", (30, 50), "green").save(buffer, "PNG")
            response = httpx.Response(
                200,
                content=buffer.getvalue(),
                request=httpx.Request("GET", "https://example.com"),
            )
            manager = AssetManager(td, td, remote=True)
            entered = threading.Event()
            release = threading.Event()

            def enter_stream():
                entered.set()
                self.assertTrue(release.wait(2.0))
                return response

            try:
                with patch("astrbot_plugin_nikke.asset_manager.httpx.stream") as stream:
                    stream.return_value.__enter__.side_effect = enter_stream
                    with patch("PIL.Image.Image.save", side_effect=OSError("synthetic disk full")):
                        with ThreadPoolExecutor(max_workers=5) as executor:
                            futures = [
                                executor.submit(manager.get_character_portrait, "5004", "191")
                                for _ in range(5)
                            ]
                            self.assertTrue(entered.wait(2.0))
                            time.sleep(0.05)
                            release.set()
                            images = [future.result(timeout=3.0) for future in futures]

                    self.assertEqual(stream.call_count, 1)
                    self.assertTrue(all(image.size == (30, 50) for image in images))
            finally:
                manager.close()

    def test_concurrent_distinct_asset_keys_keep_separate_requests(self):
        with tempfile.TemporaryDirectory() as td:
            responses = []
            for color in ("red", "blue"):
                buffer = io.BytesIO()
                Image.new("RGBA", (30, 50), color).save(buffer, "PNG")
                responses.append(
                    httpx.Response(
                        200,
                        content=buffer.getvalue(),
                        request=httpx.Request("GET", "https://example.com"),
                    )
                )
            barrier = threading.Barrier(2)
            manager = AssetManager(td, td, remote=True)

            def open_stream(*args, **kwargs):
                barrier.wait(2.0)
                context = MagicMock()
                context.__enter__.return_value = responses.pop()
                return context

            try:
                with patch("astrbot_plugin_nikke.asset_manager.httpx.stream", side_effect=open_stream) as stream:
                    with ThreadPoolExecutor(max_workers=2) as executor:
                        futures = [
                            executor.submit(manager.get_element_icon, element)
                            for element in ("fire", "water")
                        ]
                        images = [future.result(timeout=3.0) for future in futures]

                    self.assertEqual(stream.call_count, 2)
                    self.assertEqual({image.getpixel((0, 0))[:3] for image in images}, {(255, 0, 0), (0, 0, 255)})
            finally:
                manager.close()

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

    def test_registry_unknown_ids_do_not_use_generic_sources(self):
        assets_dir = Path(__file__).resolve().parents[1] / "assets"
        with tempfile.TemporaryDirectory() as td:
            cache_dir = Path(td) / "cache"
            for kind, identifier in (("equipment", "999999"), ("favorite", "999999"), ("cube", "999999")):
                path = cache_dir / kind / f"{identifier}.png"
                path.parent.mkdir(parents=True, exist_ok=True)
                Image.new("RGBA", (17, 19), "red").save(path)
            manager = AssetManager(cache_dir, assets_dir, remote=True)
            try:
                # 未知 registry ID 既不能远程请求，也不能命中残留的本地同名缓存。
                manager.sources.update({
                    "equipment/999999.png": "https://example.com/equipment.png",
                    "favorite/999999.png": "https://example.com/favorite.png",
                    "cube/999999.png": "https://example.com/cube.png",
                })
                with patch("astrbot_plugin_nikke.asset_manager.httpx.stream") as stream:
                    equipment = manager.get_equipment_icon("head", 999999)
                    favorite = manager.get_favorite_item_icon(999999)
                    cube = manager.get_cube_icon(999999)
                    self.assertNotEqual(equipment.size, (17, 19))
                    self.assertNotEqual(favorite.size, (17, 19))
                    self.assertNotEqual(cube.size, (17, 19))
                    stream.assert_not_called()
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
                finished = threading.Event()

                def slow_favorite(tid):
                    try:
                        time.sleep(1.0)
                        return Image.new("RGBA", (10, 10), "red")
                    finally:
                        finished.set()

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
                    # 已运行的 Python 线程不能安全强杀；在退出 mock 前等待其自然结束。
                    self.assertTrue(finished.wait(2.0))
            finally:
                manager.close()

    def test_prefetch_queue_saturation_falls_back_without_submitting(self):
        from astrbot_plugin_nikke.tests.test_card_builder import build_card

        with tempfile.TemporaryDirectory() as td:
            manager = AssetManager(td, td)
            slots = []
            try:
                for _ in range(manager.MAX_PREFETCH_TASKS):
                    self.assertTrue(manager._prefetch_slots.acquire(blocking=False))
                    slots.append(True)
                with patch.object(manager._executor, "submit") as submit:
                    assets = manager.resolve_character_assets(build_card(), timeout=0.1)
                submit.assert_not_called()
                self.assertEqual(assets.portrait.size, (600, 900))
                self.assertEqual(assets.equipment["head"].size, (128, 128))
            finally:
                while slots:
                    slots.pop()
                    manager._prefetch_slots.release()
                manager.close()

    def test_prefetch_slot_returns_after_task_completion(self):
        with tempfile.TemporaryDirectory() as td:
            manager = AssetManager(td, td)
            try:
                future = manager._submit_prefetch(lambda: "done")
                self.assertEqual(future.result(timeout=1.0), "done")
                self.assertTrue(manager._prefetch_slots.acquire(blocking=False))
                manager._prefetch_slots.release()
            finally:
                manager.close()

    def test_prefetch_timeout_cancels_queued_tasks(self):
        from astrbot_plugin_nikke.tests.test_card_builder import build_card

        with tempfile.TemporaryDirectory() as td:
            manager = AssetManager(td, td)
            manager._executor.shutdown(wait=False, cancel_futures=True)
            manager._executor = ThreadPoolExecutor(max_workers=1)
            started = threading.Event()
            release = threading.Event()
            try:
                def slow_portrait(*_):
                    started.set()
                    self.assertTrue(release.wait(2.0))
                    return manager.fallback("portrait")

                with patch.object(manager, "get_character_portrait", side_effect=slow_portrait):
                    with patch.object(manager, "get_equipment_icon") as equipment:
                        assets = manager.resolve_character_assets(build_card(), timeout=0.05)
                        self.assertTrue(started.is_set())
                        self.assertEqual(assets.portrait.size, (600, 900))
                        release.set()
                        # 若 queued future 没有被取消，单 worker 释放后会继续调用装备读取。
                        manager._executor.submit(lambda: None).result(timeout=1.0)
                        equipment.assert_not_called()
            finally:
                release.set()
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

