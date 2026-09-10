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

    async def test_bounded_concurrency_and_temp_file_cleanup(self):
        """验证 20 个并发编码请求：最大活跃子进程数不超过限额、临时文件无碰撞、输出独立正确。"""
        import asyncio
        import wave
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            max_limit = 2
            encoder = VoiceEncoder(root, "ffmpeg", "ffprobe", max_concurrency=max_limit)

            active_count = 0
            peak_active = 0
            lock = asyncio.Lock()
            temp_files_seen = set()

            async def run(*args, **kwargs):
                nonlocal active_count, peak_active
                if "-version" in args:
                    return b"version-test"
                if "-show_entries" in args:
                    return b'{"format":{"duration":"0.05"}}'

                out_path = args[-1]
                temp_files_seen.add(out_path)
                async with lock:
                    active_count += 1
                    if active_count > peak_active:
                        peak_active = active_count

                await asyncio.sleep(0.02)

                with wave.open(out_path, "wb") as audio:
                    audio.setnchannels(1)
                    audio.setsampwidth(2)
                    audio.setframerate(24000)
                    audio.writeframes(b"\0\0" * 240)

                async with lock:
                    active_count -= 1
                return b""

            sources = []
            for i in range(20):
                s = root / f"source_{i}.mp3"
                s.write_bytes(f"ID3synthetic_{i}".encode("utf-8"))
                sources.append(s)

            with patch.object(encoder, "_run", side_effect=run):
                results = await asyncio.gather(*(encoder.encode(s) for s in sources))

            self.assertEqual(len(results), 20)
            self.assertEqual(len(set(results)), 20, "20 个不同源文件必须输出 20 个独立结果")
            self.assertLessEqual(peak_active, max_limit, f"活跃并发数峰值 ({peak_active}) 不得超过配置上限 ({max_limit})")
            self.assertEqual(len(temp_files_seen), 20, "20 个临时文件必须完全独立无碰撞")
            leftover_tmps = [p for p in encoder.cache.glob("*") if ".tmp." in p.name]
            self.assertEqual(leftover_tmps, [], "编码完成后不得遗留任何临时文件")

    async def test_cancellation_leaves_no_temp_file(self):
        """验证任务在编码中途被取消时，临时文件被确定性清理。"""
        import asyncio
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            encoder = VoiceEncoder(root, "ffmpeg", "ffprobe")
            source = root / "cancel_test.mp3"
            source.write_bytes(b"ID3synthetic_cancel")

            created_temp = []

            async def slow_run(*args, **kwargs):
                if "-version" in args:
                    return b"version-test"
                if "-show_entries" in args:
                    return b'{"format":{"duration":"0.05"}}'
                out_path = args[-1]
                created_temp.append(Path(out_path))
                Path(out_path).write_bytes(b"partial_data")
                await asyncio.sleep(10)
                return b""

            with patch.object(encoder, "_run", side_effect=slow_run):
                task = asyncio.create_task(encoder.encode(source))
                await asyncio.sleep(0.05)
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task

            self.assertTrue(len(created_temp) > 0)
            for p in created_temp:
                self.assertFalse(p.exists(), f"被取消任务的临时文件 {p} 必须被彻底清理")
