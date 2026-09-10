"""官网场景语音按需读取，只接受公开 voice_map 明确列出的 ID。"""
import asyncio
import hashlib
import json
import math
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
        self._validated_cache: dict[tuple, tuple[int, int, int]] = {}

    def _cache_path_is_safe(self) -> bool:
        """缓存路径任一现有层级为符号链接时拒绝读写，避免越出数据目录。"""
        current = self.cache
        while current != current.parent:
            try:
                if current.is_symlink():
                    return False
            except OSError:
                return False
            current = current.parent
        return True

    async def resolve(self, map_key, speech_id, locale, *, budget=4):
        if self._closed:
            return None
        if (
            isinstance(budget, bool)
            or not isinstance(budget, (int, float))
            or not math.isfinite(float(budget))
            or budget <= 0
        ):
            raise ValueError("语音资源预算必须是正数")
        if locale not in {"en", "ja", "ko"} or not all(isinstance(x, str) and re.fullmatch(r"[a-zA-Z0-9_]{1,100}", x) for x in (map_key, speech_id)):
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
            if not self._cache_path_is_safe():
                raise OSError("语音缓存路径不安全")
            self.cache.mkdir(parents=True, exist_ok=True)
            if not self._cache_path_is_safe():
                raise OSError("语音缓存路径不安全")
            target = self.cache / f"{key}.mp3"
            manifest = self.cache / f"{key}.json"
            cached = self._cached_source(target, manifest, map_key, speech_id, locale)
            if cached is not None:
                return cached
            async with httpx.AsyncClient(timeout=10, transport=self.transport, follow_redirects=False) as client:
                if map_key.startswith("roledata_"):
                    resource_id = map_key[len("roledata_"):]
                    roledata_raw = await self._read(client, f"/roledata/{resource_id}-v2-en.json", 1024 * 1024)
                    roledata = json.loads(roledata_raw)
                    dialog_list = roledata.get("character_dialog_group_list", [])
                    identifiers = {
                        item.get("speech_id")
                        for item in dialog_list
                        if isinstance(item, dict) and item.get("category_group") == 1
                    }
                else:
                    mapping = await self._read(client, f"/scene/voice_map/{map_key}.json", 1024 * 1024)
                    identifiers = json.loads(mapping)
                if not isinstance(identifiers, (list, set, tuple)) or speech_id not in identifiers:
                    raise ValueError("voice_map 未确认此语音 ID")
                # 官网播放器显式请求 MP3，不依据文件名猜测 WAV 或 Silk。
                content = await self._read(client, f"/voice/{locale}/{speech_id}.mp3", self.MAX_BYTES)
            if not self.is_mp3(content):
                raise ValueError("响应不是 MP3 音频")
            content_temporary = target.with_name(uuid.uuid4().hex + ".tmp")
            manifest_temporary = manifest.with_name(uuid.uuid4().hex + ".tmp")
            try:
                # 内容与清单分别原子替换，避免内容替换后临时路径消失导致清单写入失败。
                content_temporary.write_bytes(content)
                content_temporary.replace(target)
                manifest_temporary.write_text(json.dumps({"sha256": hashlib.sha256(content).hexdigest(),
                    "source_path": f"/voice/{locale}/{speech_id}.mp3", "map_key": map_key}), encoding="utf-8")
                manifest_temporary.replace(manifest)
            finally:
                content_temporary.unlink(missing_ok=True)
                manifest_temporary.unlink(missing_ok=True)
            return target

    def _cached_source(self, target, manifest, map_key, speech_id, locale):
        """只接受与当前请求身份、完整性和有效期都一致的本地缓存。"""
        try:
            if not self._cache_path_is_safe() or target.is_symlink() or manifest.is_symlink():
                return None
            target_stat = target.stat()
            manifest_stat = manifest.stat()
            age = time.time() - manifest_stat.st_mtime
            if not target.is_file() or not manifest.is_file() or not 0 <= age < 86400 or target_stat.st_size > self.MAX_BYTES:
                return None

            cache_key = (target, map_key, speech_id, locale)
            cached_meta = self._validated_cache.get(cache_key)
            if cached_meta is not None and cached_meta == (target_stat.st_mtime_ns, manifest_stat.st_mtime_ns, target_stat.st_size):
                return target

            raw = target.read_bytes()
            saved = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ValueError):
            return None
        expected_source_path = f"/voice/{locale}/{speech_id}.mp3"
        if (
            not isinstance(saved, dict)
            or saved.get("sha256") != hashlib.sha256(raw).hexdigest()
            or saved.get("source_path") != expected_source_path
            or saved.get("map_key") != map_key
            or not self.is_mp3(raw)
        ):
            return None
        self._validated_cache[cache_key] = (target_stat.st_mtime_ns, manifest_stat.st_mtime_ns, target_stat.st_size)
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
        self._tasks.clear()
