"""官网场景语音按需读取，只接受公开 voice_map 明确列出的 ID。"""
import asyncio
import hashlib
import json
import re
import time
import uuid
from pathlib import Path
import httpx
from .asset_manager import AssetManager


class VoiceResourceProvider:
    MAX_BYTES = 12 * 1024 * 1024

    def __init__(self, cache: Path, *, transport=None):
        self.cache = Path(cache) / "source"
        self.transport = transport
        self._tasks = {}
        self._failed = {}
        self._slots = asyncio.Semaphore(2)
        self._closed = False

    async def resolve(self, map_key, speech_id, locale, *, budget=4):
        if self._closed:
            return None
        if locale not in {"en", "ja", "ko"} or not all(isinstance(x, str) and re.fullmatch(r"[a-z0-9_]{1,100}", x) for x in (map_key, speech_id)):
            raise ValueError("语音语言或资源标识无效")
        key = hashlib.sha256(json.dumps([map_key, speech_id, locale]).encode()).hexdigest()
        self._failed = {item: until for item, until in self._failed.items() if until > time.monotonic()}
        if self._failed.get(key, 0) > time.monotonic():
            return None
        task = self._tasks.get(key)
        if task is None:
            if len(self._tasks) >= 20:
                return None
            task = asyncio.create_task(self._fetch(map_key, speech_id, locale, key))
            self._tasks[key] = task
            def done(completed):
                self._tasks.pop(key, None)
                if not completed.cancelled() and completed.exception() is not None:
                    self._failed[key] = time.monotonic() + 30
            task.add_done_callback(done)
        try:
            # 当前请求超时不取消共享下载，后续请求复用落盘结果。
            return await asyncio.wait_for(asyncio.shield(task), timeout=budget)
        except (asyncio.TimeoutError, httpx.HTTPError, ValueError, OSError):
            return None

    async def _fetch(self, map_key, speech_id, locale, key):
        async with self._slots:
            self.cache.mkdir(parents=True, exist_ok=True)
            target = self.cache / f"{key}.mp3"
            manifest = self.cache / f"{key}.json"
            if target.is_file() and manifest.is_file() and time.time() - manifest.stat().st_mtime < 86400 and target.stat().st_size <= self.MAX_BYTES:
                raw = target.read_bytes()
                try:
                    saved = json.loads(manifest.read_text(encoding="utf-8"))
                    if saved.get("sha256") == hashlib.sha256(raw).hexdigest() and self.is_mp3(raw):
                        return target
                except (ValueError, AttributeError):
                    pass
            async with httpx.AsyncClient(timeout=10, transport=self.transport, follow_redirects=False) as client:
                mapping = await self._read(client, f"/scene/voice_map/{map_key}.json", 1024 * 1024)
                identifiers = json.loads(mapping)
                if not isinstance(identifiers, list) or speech_id not in identifiers:
                    raise ValueError("voice_map 未确认此语音 ID")
                # 官网播放器显式请求 MP3，不依据文件名猜测 WAV 或 Silk。
                content = await self._read(client, f"/voice/{locale}/{speech_id}.mp3", self.MAX_BYTES)
            if not self.is_mp3(content):
                raise ValueError("响应不是 MP3 音频")
            temporary = target.with_name(uuid.uuid4().hex + ".tmp")
            try:
                temporary.write_bytes(content)
                temporary.replace(target)
                temporary.write_text(json.dumps({"sha256": hashlib.sha256(content).hexdigest(),
                    "source_path": f"/voice/{locale}/{speech_id}.mp3", "map_key": map_key}), encoding="utf-8")
                temporary.replace(manifest)
            finally:
                temporary.unlink(missing_ok=True)
            return target

    @staticmethod
    def is_mp3(content):
        return len(content) >= 4 and (content.startswith(b"ID3") or content[0] == 255 and content[1] & 224 == 224)

    @staticmethod
    async def _read(client, logical_path, limit):
        async with client.stream("GET", AssetManager.game_resource_url(logical_path)) as response:
            response.raise_for_status()
            content = bytearray()
            async for chunk in response.aiter_bytes():
                content.extend(chunk)
                if len(content) > limit:
                    raise ValueError("语音资源超过大小预算")
            return bytes(content)

    async def close(self):
        self._closed = True
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
