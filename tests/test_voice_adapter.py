"""使用合成 WAV 验证真实 AstrBot 适配器序列化，不调用发送接口。"""
import base64
import tempfile
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock

from astrbot.api.message_components import Record
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import AiocqhttpMessageEvent


class VoiceAdapterTests(IsolatedAsyncioTestCase):
    async def test_local_wav_serializes_to_onebot_base64_without_shared_path(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'synthetic.wav'
            with wave.open(str(path), 'wb') as audio:
                audio.setnchannels(1)
                audio.setsampwidth(2)
                audio.setframerate(24000)
                audio.writeframes(b'\x00\x00' * 240)
            segment = Record.fromFileSystem(str(path))
            payload = await AiocqhttpMessageEvent._from_segment_to_dict(segment)
            self.assertEqual(payload['type'], 'record')
            encoded = payload['data']['file']
            self.assertTrue(encoded.startswith('base64://'))
            self.assertEqual(base64.b64decode(encoded[9:]), path.read_bytes())
            self.assertNotIn(str(path), str(payload))

    async def test_event_adapter_converts_poke_and_emits_only_application_audio(self):
        from astrbot_plugin_nikke.adapters.astrbot.voice_adapter import AstrBotVoiceAdapter
        from astrbot_plugin_nikke.features.voice.application import VoicePokeContext

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "authorized-local.wav"
            with wave.open(str(path), "wb") as audio:
                audio.setnchannels(1)
                audio.setsampwidth(2)
                audio.setframerate(24000)
                audio.writeframes(b"\x00\x00" * 240)
            application = SimpleNamespace(resolve_poke=AsyncMock(return_value=path))
            adapter = AstrBotVoiceAdapter(application)
            raw = {
                "post_type": "notice",
                "notice_type": "notify",
                "sub_type": "poke",
                "self_id": "fake-bot",
                "target_id": "fake-bot",
                "user_id": "fake-user",
            }
            event = SimpleNamespace(
                message_obj=SimpleNamespace(raw_message=raw),
                get_platform_name=lambda: "aiocqhttp",
                get_sender_id=lambda: "fake-user",
                unified_msg_origin="group:fake-room",
                chain_result=Mock(side_effect=lambda chain: chain),
            )

            results = [item async for item in adapter.on_poke(event, closing=True)]

            self.assertEqual(len(results), 1)
            context = application.resolve_poke.await_args.args[0]
            self.assertEqual(
                context,
                VoicePokeContext(
                    platform_name="aiocqhttp",
                    actor_id="fake-user",
                    sender_id="fake-user",
                    unified_msg_origin="group:fake-room",
                    supported_platform=True,
                    is_self_poke=True,
                    closing=True,
                ),
            )
            record = results[0][0]
            self.assertEqual(Path(record.path), path.resolve())
            payload = await AiocqhttpMessageEvent._from_segment_to_dict(record)
            self.assertEqual(payload["type"], "record")
            encoded = payload["data"]["file"]
            self.assertTrue(encoded.startswith("base64://"))
            self.assertEqual(base64.b64decode(encoded[9:]), path.read_bytes())

    async def test_event_adapter_settings_uses_neutral_identity_and_plain_reply(self):
        from astrbot_plugin_nikke.adapters.astrbot.voice_adapter import AstrBotVoiceAdapter

        application = SimpleNamespace(update_settings=Mock(return_value="语音已开启"))
        adapter = AstrBotVoiceAdapter(application)
        event = SimpleNamespace(
            get_platform_name=lambda: "aiocqhttp",
            get_sender_id=lambda: "fake-user",
            plain_result=lambda text: ("plain", text),
        )

        results = [item async for item in adapter.voice_settings(event, "开", "")]

        self.assertEqual(results, [("plain", "语音已开启")])
        application.update_settings.assert_called_once_with(
            "aiocqhttp", "fake-user", "开", ""
        )

    async def test_event_adapter_rejects_unverified_platform_without_emitting(self):
        from astrbot_plugin_nikke.adapters.astrbot.voice_adapter import AstrBotVoiceAdapter

        application = SimpleNamespace(resolve_poke=AsyncMock(return_value=None))
        adapter = AstrBotVoiceAdapter(application)
        event = SimpleNamespace(
            message_obj=SimpleNamespace(raw_message={}),
            get_platform_name=lambda: "unverified",
            get_sender_id=lambda: "fake-user",
            unified_msg_origin="room",
            chain_result=Mock(),
        )

        results = [item async for item in adapter.on_poke(event)]

        self.assertEqual(results, [])
        application.resolve_poke.assert_awaited_once()
        self.assertFalse(application.resolve_poke.await_args.args[0].supported_platform)
