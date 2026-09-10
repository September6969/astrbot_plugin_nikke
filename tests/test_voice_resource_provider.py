"""只用合成 MP3 头与 mock 网络，验证映射、并发、缓存和失败降级。"""
import asyncio
import hashlib
import json
import os
import tempfile
import time
from pathlib import Path
from unittest import IsolatedAsyncioTestCase
import httpx
from astrbot_plugin_nikke.voice_resource_provider import VoiceResourceProvider
from astrbot_plugin_nikke.asset_manager import AssetManager


class VoiceResourceTests(IsolatedAsyncioTestCase):
    async def test_symlinked_cache_root_is_rejected_without_network_or_external_write(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as external:
            cache = Path(directory, "cache")
            cache.mkdir()
            os.symlink(Path(external), cache / "source", target_is_directory=True)
            calls = []

            def handle(request):
                calls.append(request)
                return httpx.Response(200, content=b"ID3unexpected")

            provider = VoiceResourceProvider(cache, transport=httpx.MockTransport(handle))
            self.assertIsNone(await provider.resolve("fixture", "synthetic_line", "en"))
            self.assertEqual(calls, [])
            self.assertEqual(list(Path(external).iterdir()), [])
            await provider.close()

    async def test_invalid_budget_is_rejected_before_fetch(self):
        calls = []

        def handle(request):
            calls.append(request)
            return httpx.Response(200, json=["synthetic_line"])

        with tempfile.TemporaryDirectory() as directory:
            provider = VoiceResourceProvider(Path(directory), transport=httpx.MockTransport(handle))
            for budget in (True, "4", 0, -1, float("nan"), float("inf")):
                with self.subTest(budget=budget):
                    with self.assertRaises(ValueError):
                        await provider.resolve("fixture", "synthetic_line", "en", budget=budget)
            self.assertEqual(calls, [])
            await provider.close()

    async def test_singleflight_and_persistent_source_cache(self):
        calls = []
        async def handle(request):
            calls.append(str(request.url))
            await asyncio.sleep(0.01)
            self.assertNotIn("cookie", request.headers)
            if str(request.url) == AssetManager.game_resource_url("/scene/voice_map/fixture.json"):
                return httpx.Response(200, json=["synthetic_line"])
            return httpx.Response(200, content=b"ID3synthetic")
        with tempfile.TemporaryDirectory() as directory:
            provider = VoiceResourceProvider(Path(directory), transport=httpx.MockTransport(handle))
            results = await asyncio.gather(*(provider.resolve("fixture", "synthetic_line", "en") for _ in range(5)))
            self.assertEqual(len(calls), 2)
            self.assertTrue(all(path == results[0] for path in results))
            self.assertIsNotNone(results[0])
            manifest = next(Path(directory, "source").glob("*.json"))
            saved = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertEqual(saved["map_key"], "fixture")
            self.assertEqual(saved["source_path"], "/voice/en/synthetic_line.mp3")
            await provider.close()
            restarted = VoiceResourceProvider(Path(directory), transport=httpx.MockTransport(handle))
            self.assertEqual(await restarted.resolve("fixture", "synthetic_line", "en"), results[0])
            self.assertEqual(len(calls), 2)
            await restarted.close()

    async def test_unverified_id_and_path_are_not_downloaded(self):
        calls = []
        def handle(request):
            calls.append(request)
            return httpx.Response(200, json=[])
        with tempfile.TemporaryDirectory() as directory:
            provider = VoiceResourceProvider(Path(directory), transport=httpx.MockTransport(handle))
            self.assertIsNone(await provider.resolve("fixture", "missing", "en"))
            self.assertIsNone(await provider.resolve("fixture", "missing", "en"))
            self.assertEqual(len(calls), 1)
            with self.assertRaises(ValueError):
                await provider.resolve("../escape", "missing", "en")
            await provider.close()

    async def test_manifest_identity_mismatch_is_refetched(self):
        for field, invalid_value in (
            ("source_path", "/voice/ja/synthetic_line.mp3"),
            ("map_key", "another_map"),
        ):
            with self.subTest(field=field):
                calls = []

                def handle(request):
                    calls.append(str(request.url))
                    if str(request.url) == AssetManager.game_resource_url("/scene/voice_map/fixture.json"):
                        return httpx.Response(200, json=["synthetic_line"])
                    return httpx.Response(200, content=b"ID3verified")

                with tempfile.TemporaryDirectory() as directory:
                    source = Path(directory, "source")
                    source.mkdir()
                    key = hashlib.sha256(json.dumps(["fixture", "synthetic_line", "en"]).encode()).hexdigest()
                    target = source / f"{key}.mp3"
                    manifest = source / f"{key}.json"
                    target.write_bytes(b"ID3stale")
                    saved = {
                        "sha256": hashlib.sha256(b"ID3stale").hexdigest(),
                        "source_path": "/voice/en/synthetic_line.mp3",
                        "map_key": "fixture",
                    }
                    saved[field] = invalid_value
                    manifest.write_text(json.dumps(saved), encoding="utf-8")

                    provider = VoiceResourceProvider(Path(directory), transport=httpx.MockTransport(handle))
                    result = await provider.resolve("fixture", "synthetic_line", "en")

                    self.assertEqual(len(calls), 2)
                    self.assertEqual(result.read_bytes(), b"ID3verified")
                    saved = json.loads(manifest.read_text(encoding="utf-8"))
                    self.assertEqual(saved["map_key"], "fixture")
                    self.assertEqual(saved["source_path"], "/voice/en/synthetic_line.mp3")
                    await provider.close()

    async def test_future_manifest_is_refetched(self):
        calls = []

        def handle(request):
            calls.append(str(request.url))
            if str(request.url) == AssetManager.game_resource_url("/scene/voice_map/fixture.json"):
                return httpx.Response(200, json=["synthetic_line"])
            return httpx.Response(200, content=b"ID3verified")

        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory, "source")
            source.mkdir()
            key = hashlib.sha256(json.dumps(["fixture", "synthetic_line", "en"]).encode()).hexdigest()
            target = source / f"{key}.mp3"
            manifest = source / f"{key}.json"
            content = b"ID3stale"
            target.write_bytes(content)
            manifest.write_text(json.dumps({
                "sha256": hashlib.sha256(content).hexdigest(),
                "source_path": "/voice/en/synthetic_line.mp3",
                "map_key": "fixture",
            }), encoding="utf-8")
            future = time.time() + 86400
            os.utime(manifest, (future, future))

            provider = VoiceResourceProvider(Path(directory), transport=httpx.MockTransport(handle))
            result = await provider.resolve("fixture", "synthetic_line", "en")

            self.assertEqual(len(calls), 2)
            self.assertEqual(result.read_bytes(), b"ID3verified")
            await provider.close()

    async def test_close_cancels_pending_fetch_and_releases_task_references(self):
        with tempfile.TemporaryDirectory() as directory:
            provider = VoiceResourceProvider(Path(directory))
            entered, cancelled = asyncio.Event(), asyncio.Event()

            async def pending_fetch(*_args):
                entered.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    cancelled.set()

            provider._fetch = pending_fetch
            request = asyncio.create_task(provider.resolve("fixture", "synthetic_line", "en"))
            await entered.wait()
            self.assertEqual(len(provider._tasks), 1)

            await provider.close()

            self.assertTrue(cancelled.is_set())
            self.assertEqual(provider._tasks, {})
            with self.assertRaises(asyncio.CancelledError):
                await request
            self.assertIsNone(await provider.resolve("fixture", "synthetic_line", "en"))

    async def test_roledata_voice_verification_and_fetch(self):
        calls = []

        async def handle(request):
            calls.append(str(request.url))
            if str(request.url) == AssetManager.game_resource_url("/roledata/10-v2-en.json"):
                return httpx.Response(200, json={
                    "character_dialog_group_list": [
                        {"speech_id": "c010_Lobby_Touch_1", "category_group": 1},
                        {"speech_id": "c010_Lobby_Touch_2", "category_group": 1},
                        {"speech_id": "c010_Story_Line", "category_group": 2},
                        {"speech_id": "c010_Missing_Group"},
                    ]
                })
            if str(request.url) == AssetManager.game_resource_url("/voice/ja/c010_Lobby_Touch_1.mp3"):
                return httpx.Response(200, content=b"ID3touch_audio")
            return httpx.Response(404)

        with tempfile.TemporaryDirectory() as directory:
            provider = VoiceResourceProvider(Path(directory), transport=httpx.MockTransport(handle))
            result = await provider.resolve("roledata_10", "c010_Lobby_Touch_1", "ja")
            self.assertIsNotNone(result)
            self.assertEqual(result.read_bytes(), b"ID3touch_audio")

            # Unverified speech_id in roledata rejected
            self.assertIsNone(await provider.resolve("roledata_10", "c010_Lobby_Touch_99", "ja"))

            # Items with category_group != 1 or missing category_group rejected
            self.assertIsNone(await provider.resolve("roledata_10", "c010_Story_Line", "ja"))
            self.assertIsNone(await provider.resolve("roledata_10", "c010_Missing_Group", "ja"))
            await provider.close()
