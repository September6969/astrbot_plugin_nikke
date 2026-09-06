"""本地测试音频及 OneBot 通知过滤；不进行真实消息发送。"""
import json
import tempfile
from pathlib import Path
from unittest import IsolatedAsyncioTestCase
from astrbot_plugin_nikke.voice_audio import VoiceAudioCache, VoicePreference, is_self_poke
from astrbot_plugin_nikke.storage import NikkeStore


class VoiceAudioTests(IsolatedAsyncioTestCase):
    async def test_invalid_and_overlong_wav_are_not_cached(self):
        import wave
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            row = dict(character="rapi", locale="zh-cn", file="test.wav", source="synthetic", license="self")
            (root / "registry.json").write_text(json.dumps([row]), encoding="utf-8")
            (root / "test.wav").write_bytes(b"RIFF0000WAVEbroken")
            cache = VoiceAudioCache(root, root / "cache")
            self.assertIsNone(await cache.resolve(VoicePreference(True)))
            with wave.open(str(root / "test.wav"), "wb") as audio:
                audio.setnchannels(1)
                audio.setsampwidth(1)
                audio.setframerate(8000)
                audio.writeframes(b"\0" * (8000 * 31))
            self.assertIsNone(await cache.resolve(VoicePreference(True)))
            self.assertFalse(list((root / "cache").glob("*.wav")))

    async def test_cache_and_preferences(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = NikkeStore(root / "store")
            preference = VoicePreference(True)
            preference.save(store, "fake-user")
            self.assertTrue(VoicePreference.load(store, "fake-user").enabled)
            self.assertFalse(VoicePreference.load(store, "other-user").enabled)
            import wave
            with wave.open(str(root / "test.wav"), "wb") as audio:
                audio.setnchannels(1)
                audio.setsampwidth(2)
                audio.setframerate(24000)
                audio.writeframes(b"\0\0" * 240)
            row = dict(character="rapi", locale="zh-cn", file="test.wav", source="synthetic", license="self")
            (root / "registry.json").write_text(json.dumps([row]), encoding="utf-8")
            cache = VoiceAudioCache(root, root / "cache")
            first = await cache.resolve(preference)
            self.assertTrue(first.is_file())
            self.assertEqual(first, await cache.resolve(preference))
            preference.locale = "en"
            self.assertIsNone(await cache.resolve(preference))

    def test_only_pokes_directed_at_bot(self):
        event = dict(post_type="notice", notice_type="notify", sub_type="poke", self_id="fake-bot", target_id="fake-bot", user_id="fake-user")
        self.assertTrue(is_self_poke(event))
        self.assertFalse(is_self_poke(dict(event, target_id="someone-else")))
        self.assertFalse(is_self_poke(dict(event, user_id="fake-bot")))

    async def test_listener_default_off_and_record_sender(self):
        from types import SimpleNamespace
        from unittest.mock import AsyncMock, Mock
        from astrbot_plugin_nikke.main import NikkePlugin
        with tempfile.TemporaryDirectory() as directory:
            plugin = NikkePlugin.__new__(NikkePlugin)
            plugin.store = NikkeStore(directory)
            plugin.plugin_dir = Path(directory)
            raw = dict(post_type="notice", notice_type="notify", sub_type="poke", self_id="fake-bot", target_id="fake-bot", user_id="fake-user")
            event = SimpleNamespace(message_obj=SimpleNamespace(raw_message=raw), get_platform_name=lambda: "aiocqhttp",
                get_sender_id=lambda: "fake-user", plain_result=lambda x: x, chain_result=Mock(side_effect=lambda x: x))
            self.assertEqual([x async for x in plugin.on_nikke_poke(event)], [])
            event.get_sender_id = lambda: "other-user"
            raw["user_id"] = "other-user"
            VoicePreference(True).save(plugin.store, "aiocqhttp:other-user")
            plugin._voice_audio = SimpleNamespace(resolve=AsyncMock(return_value=Path(directory) / "fake.wav"))
            self.assertEqual(len([x async for x in plugin.on_nikke_poke(event)]), 1)
            event.get_sender_id = lambda: "fake-user"
            raw["user_id"] = "fake-user"
            event.chain_result.reset_mock()
            VoicePreference(True).save(plugin.store, "aiocqhttp:fake-user")
            plugin._voice_audio = SimpleNamespace(resolve=AsyncMock(return_value=Path(directory) / "fake.wav"))
            self.assertEqual(len([x async for x in plugin.on_nikke_poke(event)]), 1)
            event.chain_result.assert_called_once()
            self.assertEqual([x async for x in plugin.on_nikke_poke(event)], [])
