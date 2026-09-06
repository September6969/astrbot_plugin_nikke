"""只验证管线预算和生命周期，不下载资源或发送消息。"""
import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock

from astrbot_plugin_nikke.voice_pipeline import VoicePipeline


class VoicePipelineTests(IsolatedAsyncioTestCase):
    def pipeline(self, **kwargs):
        provider = SimpleNamespace(resolve=AsyncMock(return_value=Path('synthetic.mp3')), close=AsyncMock())
        encoder = SimpleNamespace(encode=AsyncMock(return_value=Path('synthetic.wav')))
        return VoicePipeline(provider, encoder, **kwargs)

    async def test_concurrent_requests_share_download_and_encode(self):
        pipeline = self.pipeline()
        results = await asyncio.gather(*(pipeline.resolve('map', 'id', 'en') for _ in range(3)))
        self.assertEqual(results, [Path('synthetic.wav')] * 3)
        pipeline.provider.resolve.assert_awaited_once()
        pipeline.encoder.encode.assert_awaited_once()
        await pipeline.close()

    async def test_response_timeout_preserves_shared_encoding(self):
        pipeline = self.pipeline()
        entered, release = asyncio.Event(), asyncio.Event()
        async def encode(*args, **kwargs):
            entered.set()
            await release.wait()
            return Path('synthetic.wav')
        pipeline.encoder.encode.side_effect = encode
        first = asyncio.create_task(pipeline.resolve('map', 'id', 'en', budget=0.01))
        await entered.wait()
        self.assertIsNone(await first)
        second = asyncio.create_task(pipeline.resolve('map', 'id', 'en'))
        await asyncio.sleep(0)
        release.set()
        self.assertEqual(await second, Path('synthetic.wav'))
        pipeline.encoder.encode.assert_awaited_once()
        await pipeline.close()

    async def test_close_cancels_encoding_and_rejects_new_work(self):
        pipeline = self.pipeline(max_pending=1)
        entered, cancelled = asyncio.Event(), asyncio.Event()
        async def encode(*args, **kwargs):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
        pipeline.encoder.encode.side_effect = encode
        task = asyncio.create_task(pipeline.resolve('map', 'id', 'en'))
        await entered.wait()
        self.assertIsNone(await pipeline.resolve('map', 'other', 'en'))
        await pipeline.close()
        self.assertTrue(cancelled.is_set())
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertIsNone(await pipeline.resolve('map', 'id', 'en'))
        pipeline.provider.close.assert_awaited_once()

    async def test_unsupported_adapter_and_invalid_budget_do_not_fetch(self):
        pipeline = self.pipeline()
        self.assertIsNone(await pipeline.resolve('map', 'id', 'en', adapter='unknown'))
        for budget in (0, -1, 6, float('nan'), float('inf')):
            with self.assertRaises(ValueError):
                await pipeline.resolve('map', 'id', 'en', budget=budget)
        pipeline.provider.resolve.assert_not_awaited()
        await pipeline.close()
