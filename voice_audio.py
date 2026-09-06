"""显式授权本地音频的缓存与发送准备；不猜测远程音频 URL。"""
import asyncio
import hashlib
import json
import shutil
from dataclasses import dataclass, asdict
from pathlib import Path


@dataclass
class VoicePreference:
    enabled: bool = False
    character: str = "rapi"
    locale: str = "zh-cn"
    skin: str = "default"

    @classmethod
    def load(cls, store, key):
        raw = store.get_setting("voice:" + hashlib.sha256(key.encode()).hexdigest(), {})
        return cls(**{k: v for k, v in raw.items() if k in cls.__dataclass_fields__})

    def save(self, store, key):
        store.set_setting("voice:" + hashlib.sha256(key.encode()).hexdigest(), asdict(self))


def is_self_poke(raw):
    return isinstance(raw, dict) and raw.get("post_type") == "notice" and raw.get("notice_type") == "notify" and raw.get("sub_type") == "poke" and raw.get("self_id") is not None and str(raw.get("target_id")) == str(raw["self_id"]) and str(raw.get("user_id")) != str(raw["self_id"])


class VoiceAudioCache:
    def __init__(self, root: Path, cache: Path):
        self.root = root.resolve()
        self.cache = cache
        self._lock = asyncio.Lock()

    async def resolve(self, preference):
        async with self._lock:
            return await self._resolve(preference)

    async def _resolve(self, preference):
        registry = self.root / "registry.json"
        if not registry.is_file():
            return None
        rows = json.loads(registry.read_text(encoding="utf-8"))
        if not isinstance(rows, list):
            return None
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
                target.write_bytes(content)
                return target
            ffmpeg = shutil.which("ffmpeg")
            if not ffmpeg:
                return None
            process = await asyncio.create_subprocess_exec(ffmpeg, "-nostdin", "-y", "-i", str(source),
                "-t", "30", "-ac", "1", "-ar", "24000", str(target), stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
            try:
                await asyncio.wait_for(process.wait(), 15)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                process.kill()
                await process.wait()
                target.unlink(missing_ok=True)
                raise
            if process.returncode != 0:
                target.unlink(missing_ok=True)
                return None
            return target
        return None
