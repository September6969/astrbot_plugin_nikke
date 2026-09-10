"""显式授权本地音频的缓存与发送准备；不猜测远程音频 URL。"""
import asyncio
import hashlib
import json
import os
import shutil
import io
import uuid
import wave
from dataclasses import dataclass, asdict
from pathlib import Path


@dataclass
class VoicePreference:
    enabled: bool = False
    character: str = "rapi"
    locale: str = "ja"
    skin: str = "default"
    spine_asset_id: str = ""
    explicit_locale: bool = False

    @classmethod
    def load(cls, store, key):
        raw = store.get_setting("voice:" + hashlib.sha256(key.encode()).hexdigest(), {})
        if not raw:
            return cls()
        data = {k: v for k, v in raw.items() if k in cls.__dataclass_fields__}
        # 严格收口至官方语音语言 ("ja", "en", "ko")；非法或遗留语言（如 "zh-cn"、"fr" 等）一律迁移至默认 "ja"
        if data.get("locale") not in {"ja", "en", "ko"}:
            data["locale"] = "ja"
            data["explicit_locale"] = False
        return cls(**data)

    def save(self, store, key):
        store.set_setting("voice:" + hashlib.sha256(key.encode()).hexdigest(), asdict(self))


def is_self_poke(raw):
    return isinstance(raw, dict) and raw.get("post_type") == "notice" and raw.get("notice_type") == "notify" and raw.get("sub_type") == "poke" and raw.get("self_id") is not None and str(raw.get("target_id")) == str(raw["self_id"]) and str(raw.get("user_id")) != str(raw["self_id"])


class VoiceAudioCache:
    """本地登记语音缓存。

    registry.json 内容在文件未被修改时缓存在内存中（按 mtime 失效），
    避免每次 poke 都产生磁盘 I/O。
    每个 (character, locale, skin) 三元组持有独立的 asyncio.Lock，
    防止对同一语音的并发处理，同时不阻塞独立用户。
    """

    def __init__(self, root: Path, cache: Path):
        self.root = root.resolve()
        self.cache = cache
        # Registry cache: (mtime_ns, parsed_rows)
        self._registry_cache: tuple[int, list] | None = None
        self._registry_read_lock = asyncio.Lock()
        # Per-key locks: key → asyncio.Lock
        self._key_locks: dict[tuple, asyncio.Lock] = {}
        self._key_locks_meta_lock = asyncio.Lock()

    async def _get_key_lock(self, key: tuple) -> asyncio.Lock:
        async with self._key_locks_meta_lock:
            if key not in self._key_locks:
                self._key_locks[key] = asyncio.Lock()
            return self._key_locks[key]

    async def _load_registry(self) -> list:
        """加载 registry.json；mtime 未变时直接返回内存缓存。"""
        async with self._registry_read_lock:
            registry_path = self.root / "registry.json"
            try:
                mtime_ns = registry_path.stat().st_mtime_ns
            except OSError:
                return []
            if self._registry_cache is not None and self._registry_cache[0] == mtime_ns:
                return self._registry_cache[1]
            try:
                rows = json.loads(registry_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, ValueError):
                return []
            if not isinstance(rows, list):
                return []
            self._registry_cache = (mtime_ns, rows)
            return rows

    async def resolve(self, preference):
        key = (preference.character, preference.locale, preference.skin)
        lock = await self._get_key_lock(key)
        async with lock:
            return await self._resolve(preference)

    async def _resolve(self, preference):
        rows = await self._load_registry()
        for row in rows:
            if not isinstance(row, dict) or not row.get("license") or not row.get("source"):
                continue
            if (row.get("character"), row.get("locale"), row.get("skin", "default")) != (preference.character, preference.locale, preference.skin):
                continue
            source = (self.root / str(row.get("file", ""))).resolve()
            if not source.is_relative_to(self.root) or not source.is_file() or source.suffix.lower() not in {".wav", ".ogg"} or source.stat().st_size > 12*1024*1024:
                continue
            content = source.read_bytes()
            if len(content) > 12*1024*1024:
                return None
            if not (content.startswith(b"OggS") or content.startswith(b"RIFF") and content[8:12] == b"WAVE"):
                return None
            digest = hashlib.sha256(content).hexdigest()
            self.cache.mkdir(parents=True, exist_ok=True)
            target = self.cache / (digest + ".wav")
            if target.is_file():
                return target
            if source.suffix.lower() == ".wav":
                try:
                    with wave.open(io.BytesIO(content)) as audio:
                        if audio.getframerate() <= 0 or audio.getnframes() / audio.getframerate() > 30:
                            return None
                        if len(audio.readframes(audio.getnframes())) != audio.getnframes() * audio.getnchannels() * audio.getsampwidth():
                            return None
                except (wave.Error, EOFError):
                    return None
                temporary = target.with_name(uuid.uuid4().hex + ".tmp")
                try:
                    temporary.write_bytes(content)
                    temporary.replace(target)
                finally:
                    temporary.unlink(missing_ok=True)
                return target
            ffmpeg = shutil.which("ffmpeg")
            if not ffmpeg:
                return None
            temporary = target.with_name(uuid.uuid4().hex + ".wav")
            process = await asyncio.create_subprocess_exec(ffmpeg, "-nostdin", "-y", "-i", str(source),
                "-t", "30", "-ac", "1", "-ar", "24000", str(temporary), stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
            try:
                await asyncio.wait_for(process.wait(), 15)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                process.kill()
                await process.wait()
                temporary.unlink(missing_ok=True)
                raise
            if process.returncode != 0:
                temporary.unlink(missing_ok=True)
                return None
            temporary.replace(target)
            return target
        return None
