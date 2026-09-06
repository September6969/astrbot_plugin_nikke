"""使用合成 WAV 验证真实 AstrBot 适配器序列化，不调用发送接口。"""
import base64
import tempfile
import wave
from pathlib import Path
from unittest import IsolatedAsyncioTestCase

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
