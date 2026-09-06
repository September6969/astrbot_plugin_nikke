"""只用合成 MP3 头与 mock 网络，验证映射、并发、缓存和失败降级。"""
import asyncio
import tempfile
from pathlib import Path
from unittest import IsolatedAsyncioTestCase
import httpx
from astrbot_plugin_nikke.voice_resource_provider import VoiceResourceProvider
from astrbot_plugin_nikke.asset_manager import AssetManager


class VoiceResourceTests(IsolatedAsyncioTestCase):
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
