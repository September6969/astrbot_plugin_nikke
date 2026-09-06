"""模拟工具响应校验时长，不发送消息。"""
import tempfile
from pathlib import Path
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch
from astrbot_plugin_nikke.voice_encoder import VoiceEncoder


class VoiceEncoderTests(IsolatedAsyncioTestCase):
    async def test_unknown_or_overlong_duration_rejected_before_encode(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "fake.mp3"
            source.write_bytes(b"ID3synthetic")
            for duration in ("nan", "31", "0"):
                encoder = VoiceEncoder(root, "ffmpeg", "ffprobe")
                with patch.object(encoder, "_run", AsyncMock(side_effect=[b"synthetic-version", ('{"format":{"duration":"'+duration+'"}}').encode()])) as run:
                    with self.assertRaises(ValueError):
                        await encoder.encode(source)
                    self.assertEqual(run.await_count, 2)

    async def test_encoding_cache_is_keyed_by_encoder_version(self):
        import wave
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "fake.mp3"
            source.write_bytes(b"ID3synthetic")
            encoder = VoiceEncoder(root, "ffmpeg", "ffprobe")
            version = [b"version-1"]
            writes = []
            async def run(*args, **kwargs):
                if "-version" in args:
                    return version[0]
                if "-show_entries" in args:
                    return b'{"format":{"duration":"0.01"}}'
                writes.append(args[-1])
                with wave.open(args[-1], "wb") as audio:
                    audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(24000)
                    audio.writeframes(b"\0\0" * 240)
                return b""
            with patch.object(encoder, "_run", side_effect=run):
                first = await encoder.encode(source)
                self.assertEqual(first, await encoder.encode(source))
                self.assertEqual(len(writes), 1)
                version[0] = b"version-2"
                self.assertNotEqual(first, await encoder.encode(source))
