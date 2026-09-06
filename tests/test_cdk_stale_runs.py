"""硬崩溃遗留的写请求只隔离，不重放。"""
import asyncio
import hashlib
import tempfile
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

from astrbot_plugin_nikke.main import NikkePlugin
from astrbot_plugin_nikke.storage import NikkeStore
from astrbot_plugin_nikke.client import CdkRedemptionResult
from astrbot_plugin_nikke.cdk_service import CdkService
from astrbot_plugin_nikke.cdk_models import CdkRedeemResult


def key(code):
    return 'cdk:synthetic-user:synthetic-game:' + hashlib.sha256(code.encode()).hexdigest()


class StaleRunTests(IsolatedAsyncioTestCase):
    async def test_single_final_and_retryable_states_without_plaintext(self):
        for status in ('success', 'terminal', 'unknown', 'failed', 'expired'):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as directory:
                plugin = NikkePlugin.__new__(NikkePlugin)
                plugin.store = NikkeStore(directory)
                plugin.store.claim_run(key('FAKE-CODE'), 'synthetic-user', 'cdk')
                plugin.store.finish_run(key('FAKE-CODE'), status)
                plugin.config = {'enable_cdk_redemption': True}
                plugin._account_or_error = lambda event: {'game_uid': 'synthetic-game'}
                plugin.cdk_service = SimpleNamespace(redeem_single=AsyncMock(
                    return_value=CdkRedeemResult('FAKE-CODE', True, 'FAKE-CODE')))
                event = SimpleNamespace(get_sender_id=lambda: 'synthetic-user', plain_result=lambda x: x)
                [result async for result in plugin.cdk(event, 'FAKE-CODE')]
                self.assertEqual(plugin.cdk_service.redeem_single.await_count, int(status in {'failed', 'expired'}))
                self.assertNotIn('FAKE-CODE', str(plugin.store.get_run(key('FAKE-CODE'))))

    async def test_single_stale_and_fresh_running_never_replay(self):
        for stale in (True, False):
            with self.subTest(stale=stale), tempfile.TemporaryDirectory() as directory:
                store = NikkeStore(directory)
                with patch('astrbot_plugin_nikke.storage.time.time', return_value=1000):
                    store.claim_run(key('FAKE-CODE'), 'synthetic-user', 'cdk')
                plugin = NikkePlugin.__new__(NikkePlugin)
                plugin.store = store
                plugin.config = {'enable_cdk_redemption': True}
                plugin._account_or_error = lambda event: {'game_uid': 'synthetic-game'}
                plugin.cdk_service = SimpleNamespace(redeem_single=AsyncMock())
                event = SimpleNamespace(get_sender_id=lambda: 'synthetic-user', plain_result=lambda x: x)
                async def consume():
                    return [result async for result in plugin.cdk(event, 'FAKE-CODE')]
                with patch('astrbot_plugin_nikke.storage.time.time', return_value=1180 if stale else 1010):
                    await asyncio.gather(consume(), consume())
                plugin.cdk_service.redeem_single.assert_not_awaited()
                self.assertEqual(store.get_run(key('FAKE-CODE'))['status'], 'unknown' if stale else 'running')
                self.assertNotIn('FAKE-CODE', str(store.get_run(key('FAKE-CODE'))))

    async def test_batch_stale_skipped_but_new_code_continues(self):
        with tempfile.TemporaryDirectory() as directory:
            store = NikkeStore(directory)
            with patch('astrbot_plugin_nikke.storage.time.time', return_value=1000):
                store.claim_run(key('FAKE-A'), 'synthetic-user', 'cdk')
            client = AsyncMock()
            client.redeem_cdk.return_value = CdkRedemptionResult(True, True, 'ok')
            with patch('astrbot_plugin_nikke.storage.time.time', return_value=1180), patch('astrbot_plugin_nikke.cdk_service.asyncio.sleep', new_callable=AsyncMock):
                result = await CdkService(client).redeem_batch({'game_uid': 'synthetic-game'}, ['FAKE-A', 'FAKE-B'], store=store, qq_id='synthetic-user')
            self.assertTrue(result.results[0].is_unknown)
            self.assertTrue(result.results[1].success)
            client.redeem_cdk.assert_awaited_once()
            self.assertIn('FAKE-B', str(client.redeem_cdk.await_args))
            self.assertEqual(store.get_run(key('FAKE-A'))['status'], 'unknown')

    async def test_atomic_transition_across_store_instances(self):
        with tempfile.TemporaryDirectory() as directory:
            stores = [NikkeStore(directory), NikkeStore(directory)]
            with patch('astrbot_plugin_nikke.storage.time.time', return_value=1000):
                stores[0].claim_run(key('FAKE-A'), 'synthetic-user', 'cdk')
            with patch('astrbot_plugin_nikke.storage.time.time', return_value=1180), ThreadPoolExecutor(2) as pool:
                results = list(pool.map(lambda store: store.mark_stale_running_unknown(key('FAKE-A'), stale_after=120, detail='结果未确认'), stores))
            self.assertEqual(sum(results), 1)

    async def test_batch_final_states_skip_retryable_states_retry(self):
        for status in ('success', 'terminal', 'unknown', 'failed', 'expired'):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as directory:
                store = NikkeStore(directory)
                store.claim_run(key('FAKE-A'), 'synthetic-user', 'cdk')
                store.finish_run(key('FAKE-A'), status)
                client = AsyncMock()
                client.redeem_cdk.return_value = CdkRedemptionResult(True, True, 'ok')
                await CdkService(client).redeem_batch({'game_uid': 'synthetic-game'}, ['FAKE-A'], store=store, qq_id='synthetic-user')
                self.assertEqual(client.redeem_cdk.await_count, int(status in {'failed', 'expired'}))
                self.assertNotIn('FAKE-A', str(store.get_run(key('FAKE-A'))))
