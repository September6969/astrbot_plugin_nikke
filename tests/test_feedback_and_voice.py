# SPDX-License-Identifier: GPL-3.0-or-later

import asyncio
import unittest

from astrbot_plugin_nikke.processing_feedback import DelayedFeedbackManager
from astrbot_plugin_nikke.voice_feedback import VoiceResolver


class DelayedFeedbackManagerTests(unittest.IsolatedAsyncioTestCase):
    async def test_fast_task_cancels_delayed_feedback_without_sending(self):
        manager = DelayedFeedbackManager(default_delay=0.1)
        sent = []

        async def fake_sender():
            sent.append("processing...")

        handle = manager.start_delayed_feedback(fake_sender)
        # 业务非常快完成（<0.1s），立即 cancel
        await asyncio.sleep(0.02)
        await handle.cancel()

        # 等待超过 0.1s 确认后台任务没有晚到发送
        await asyncio.sleep(0.15)
        self.assertEqual(sent, [])
        self.assertTrue(handle.finished)
        self.assertTrue(handle.cancelled)

    async def test_slow_task_triggers_delayed_feedback(self):
        manager = DelayedFeedbackManager(default_delay=0.05)
        sent = []

        async def fake_sender():
            sent.append("processing...")

        handle = manager.start_delayed_feedback(fake_sender)
        # 业务耗时超过 0.05s
        await asyncio.sleep(0.1)
        self.assertEqual(sent, ["processing..."])
        self.assertIsNotNone(handle.sent_at)

        await handle.cancel()

    async def test_manager_close_cancels_all_active_handles(self):
        manager = DelayedFeedbackManager(default_delay=1.0)
        sent = []

        async def fake_sender():
            sent.append("notice")

        h1 = manager.start_delayed_feedback(fake_sender)
        h2 = manager.start_delayed_feedback(fake_sender)
        self.assertEqual(len(manager._active_handles), 2)

        await manager.close()
        self.assertEqual(len(manager._active_handles), 0)
        self.assertTrue(h1.cancelled)
        self.assertTrue(h2.cancelled)
        self.assertEqual(sent, [])


class VoiceResolverTests(unittest.TestCase):
    def test_voice_adapter_support_matrix(self):
        self.assertTrue(VoiceResolver.is_voice_supported("aiocqhttp"))
        self.assertTrue(VoiceResolver.is_voice_supported("onebot_v11"))
        self.assertFalse(VoiceResolver.is_voice_supported("unverified_platform"))
        self.assertFalse(VoiceResolver.is_voice_supported(""))

    def test_poke_line_locale_and_character_resolution(self):
        # Alice zh-cn
        zh_line = VoiceResolver.resolve_poke_line("alice", "zh-cn")
        self.assertIsInstance(zh_line, str)
        self.assertTrue(any(k in zh_line for k in ("爱丽丝", "兔兔", "胡萝卜", "心跳")))

        # Alice en
        en_line = VoiceResolver.resolve_poke_line("alice", "en")
        self.assertIsInstance(en_line, str)
        self.assertTrue(any(k in en_line for k in ("Alice", "Wonderland", "Commander", "tickles")))

        # Other characters
        for char in ("red_hood", "anis", "rapi", "scarlet", "dorothy"):
            line = VoiceResolver.resolve_poke_line(char, "zh-cn")
            self.assertIsInstance(line, str)
            self.assertTrue(len(line) > 0)


if __name__ == "__main__":
    unittest.main()
