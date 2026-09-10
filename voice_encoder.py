import asyncio
import hashlib
import json
import math
import shutil
import uuid
import wave
from pathlib import Path


class VoiceEncoder:
    DEFAULT_MAX_CONCURRENCY = 2

    def __init__(self, cache: Path, ffmpeg: str, ffprobe: str, *, max_concurrency: int = DEFAULT_MAX_CONCURRENCY):
        if isinstance(max_concurrency, bool) or not isinstance(max_concurrency, int) or not (1 <= max_concurrency <= 4):
            raise ValueError("编码并发数必须在 1 到 4 之间")
        self.cache = Path(cache) / "encoded"
        self.ffmpeg, self.ffprobe = ffmpeg, ffprobe
        self.max_concurrency = max_concurrency
        self._slots = asyncio.Semaphore(max_concurrency)
        self._version_lock = asyncio.Lock()
        self._cached_version_identity: tuple[str, int, int] | None = None
        self._cached_version: bytes | None = None
        self._closed = False

    def invalidate_version_cache(self) -> None:
        """显式作废当前实例的 ffmpeg 版本缓存。"""
        self._cached_version_identity = None
        self._cached_version = None

    def _ffmpeg_identity(self) -> tuple[str, int, int] | None:
        """解析 ffmpeg 可执行文件在文件系统上的物理身份 (resolved_path, mtime_ns, size)。"""
        try:
            resolved = shutil.which(self.ffmpeg)
            target = Path(resolved).resolve() if resolved else Path(self.ffmpeg)
            if target.is_file():
                st = target.stat()
                return (str(target), st.st_mtime_ns, st.st_size)
        except OSError:
            pass
        return None

    async def _get_ffmpeg_version(self) -> bytes:
        """受控获取并缓存 ffmpeg 版本信息：首次调用受限并发，热路径零子进程。"""
        current_identity = self._ffmpeg_identity()
        if self._cached_version is not None:
            if current_identity is not None and self._cached_version_identity == current_identity:
                return self._cached_version
            if current_identity is None and self._cached_version_identity is None:
                return self._cached_version

        async with self._version_lock:
            if self._cached_version is not None:
                if current_identity is not None and self._cached_version_identity == current_identity:
                    return self._cached_version
                if current_identity is None and self._cached_version_identity is None:
                    return self._cached_version

            # 版本探测子进程也占用全局槽位，确保总并发进程数绝不逃逸配置预算
            async with self._slots:
                output = await self._run(self.ffmpeg, "-version", timeout=3)
                version = output.splitlines()[0]
                self._cached_version_identity = current_identity
                self._cached_version = version
                return version

    @staticmethod
    async def _run(*args, timeout=15):
        process = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
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
        if self._closed or adapter != "aiocqhttp":
            raise ValueError("此适配器音频能力尚未验证")
        if source.stat().st_size > 12 * 1024 * 1024:
            raise ValueError("源音频过大")

        version = await self._get_ffmpeg_version()
        digest = hashlib.sha256(
            source.read_bytes() + version + b"aiocqhttp:pcm_s16le:mono:24000:v1"
        ).hexdigest()
        self.cache.mkdir(parents=True, exist_ok=True)
        target = self.cache / f"{digest}.wav"
        if target.is_file() and self._valid(target):
            return target

        # 受控并发：限制同时执行的 ffprobe/ffmpeg 子进程数量不超过 max_concurrency
        async with self._slots:
            # 获取槽位后二次检查，避免排队期间其他任务已写入目标文件
            if target.is_file() and self._valid(target):
                return target

            output = await self._run(
                self.ffprobe,
                "-v", "error",
                "-protocol_whitelist", "file,pipe",
                "-show_entries", "format=duration",
                "-of", "json",
                str(source),
            )
            duration = float(json.loads(output)["format"]["duration"])
            if not math.isfinite(duration) or not 0 < duration <= 30:
                raise ValueError("源音频时长不符合预算")

            # 使用 uuid 临时文件，支持多协程/多请求并发编码而不相互阻塞
            temporary = target.with_name(f".tmp.{uuid.uuid4().hex}.wav")
            try:
                await self._run(
                    self.ffmpeg,
                    "-nostdin", "-v", "error", "-y",
                    "-protocol_whitelist", "file,pipe",
                    "-i", str(source),
                    "-t", "30", "-vn", "-ac", "1", "-ar", "24000", "-c:a", "pcm_s16le",
                    str(temporary),
                )
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
                return (
                    (audio.getnchannels(), audio.getsampwidth(), audio.getframerate())
                    == (1, 2, 24000)
                    and 0 < audio.getnframes() <= 720000
                    and len(audio.readframes(audio.getnframes())) == audio.getnframes() * 2
                )
        except (OSError, EOFError, wave.Error):
            return False

    async def close(self):
        """编码器没有常驻子进程，但仍提供统一生命周期接口。"""
        self._closed = True
