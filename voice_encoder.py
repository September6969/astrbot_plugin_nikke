"""按实际工具版本缓存 PCM WAV；格式和时长通过 ffprobe 验证。"""
import asyncio
import hashlib
import json
import math
import uuid
import wave
from pathlib import Path


class VoiceEncoder:
    def __init__(self, cache: Path, ffmpeg: str, ffprobe: str):
        self.cache = Path(cache) / "encoded"
        self.ffmpeg, self.ffprobe = ffmpeg, ffprobe
        self._lock = asyncio.Lock()

    @staticmethod
    async def _run(*args, timeout=15):
        process = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        try:
            output, _ = await asyncio.wait_for(process.communicate(), timeout)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            if process.returncode is None:
                process.kill()
            await process.wait()
            raise
        if process.returncode:
            raise ValueError("音频工具执行失败")
        return output

    async def encode(self, source: Path, *, adapter="aiocqhttp"):
        if adapter != "aiocqhttp":
            raise ValueError("此适配器音频能力尚未验证")
        if source.stat().st_size > 12 * 1024 * 1024:
            raise ValueError("源音频过大")
        async with self._lock:
            version = (await self._run(self.ffmpeg, "-version", timeout=3)).splitlines()[0]
            digest = hashlib.sha256(source.read_bytes() + version + b"aiocqhttp:pcm_s16le:mono:24000:v1").hexdigest()
            self.cache.mkdir(parents=True, exist_ok=True)
            target = self.cache / f"{digest}.wav"
            if target.is_file() and self._valid(target):
                return target
            output = await self._run(self.ffprobe, "-v", "error", "-protocol_whitelist", "file,pipe",
                "-show_entries", "format=duration", "-of", "json", str(source))
            duration = float(json.loads(output)["format"]["duration"])
            if not math.isfinite(duration) or not 0 < duration <= 30:
                raise ValueError("源音频时长不符合预算")
            temporary = target.with_name(uuid.uuid4().hex + ".wav")
            try:
                await self._run(self.ffmpeg, "-nostdin", "-v", "error", "-y", "-protocol_whitelist", "file,pipe",
                    "-i", str(source), "-t", "30", "-vn", "-ac", "1", "-ar", "24000", "-c:a", "pcm_s16le", str(temporary))
                if not self._valid(temporary):
                    raise ValueError("编码结果格式无效")
                temporary.replace(target)
            finally:
                temporary.unlink(missing_ok=True)
            return target

    @staticmethod
    def _valid(path):
        try:
            if path.stat().st_size > 2 * 1024 * 1024:
                return False
            with wave.open(str(path)) as audio:
                return (audio.getnchannels(), audio.getsampwidth(), audio.getframerate()) == (1, 2, 24000) and 0 < audio.getnframes() <= 720000 and len(audio.readframes(audio.getnframes())) == audio.getnframes() * 2
        except (OSError, EOFError, wave.Error):
            return False
