"""仅将已准备的本地图片转成有界、缩放后的 Data URI。"""
import base64
import hashlib
import io
from collections import OrderedDict
from pathlib import Path
from threading import Lock

from PIL import Image, ImageOps


class T2IAssetResolver:
    """线程安全的有界编码缓存；所有 Pillow 工作应在 ``asyncio.to_thread`` 中调用。"""

    def __init__(self, max_entries: int = 32, max_bytes: int = 8 * 1024 * 1024):
        self.max_entries = max(1, max_entries)
        self.max_bytes = max(1, max_bytes)
        self._cache: OrderedDict[tuple, str] = OrderedDict()
        self._bytes = 0
        self._lock = Lock()

    def _lookup(self, key: tuple) -> str | None:
        with self._lock:
            uri = self._cache.get(key)
            if uri is not None:
                self._cache.move_to_end(key)
            return uri

    def _store(self, key: tuple, uri: str) -> None:
        with self._lock:
            if key in self._cache or len(uri) > self.max_bytes:
                return
            self._cache[key] = uri
            self._bytes += len(uri)
            while len(self._cache) > self.max_entries or self._bytes > self.max_bytes:
                _, removed = self._cache.popitem(last=False)
                self._bytes -= len(removed)

    def encode(
        self,
        source: Image.Image | Path | None,
        size=(272, 236),
        cover_crop: bool = False,
        crop_to_size: bool = False,
        crop_16_9: bool = False,
    ) -> str | None:
        if source is None:
            return None
        if not (0 < size[0] <= 1600 and 0 < size[1] <= 2400):
            raise ValueError("无效的目标图片尺寸")
        do_cover = cover_crop or crop_to_size or crop_16_9
        options = (tuple(size), do_cover, "PNG")
        try:
            if isinstance(source, Path):
                stat = source.stat()
                if stat.st_size > 12 * 1024 * 1024:
                    return None
                # 本地文件以路径、修改时间与字节数为缓存键：命中时既不解码，
                # 也不对整张 RGBA 位图重复计算 SHA-256（AUD-021）。
                key = ("path", str(source.resolve()), stat.st_mtime_ns, stat.st_size, *options)
                cached = self._lookup(key)
                if cached is not None:
                    return cached
                with Image.open(source) as opened:
                    if opened.width * opened.height > 20_000_000:
                        return None
                    prepared = opened.convert("RGBA")
            elif isinstance(source, Image.Image):
                if source.width * source.height > 20_000_000:
                    return None
                verified = source.info.get("nikke_verified_source_sha256")
                if (
                    isinstance(verified, str)
                    and len(verified) == 64
                    and source.info.get("nikke_verified_source_object") == id(source)
                ):
                    # 已按文件 SHA-256 校验的原图（同一对象，未派生）：以来源摘要为键，
                    # 命中时跳过 15MB+ RGBA 全图哈希与 tobytes() 复制（AUD-021）。
                    key = ("verified", verified, source.size, *options)
                    cached = self._lookup(key)
                    if cached is not None:
                        return cached
                    prepared = source if source.mode == "RGBA" else source.convert("RGBA")
                else:
                    prepared = source if source.mode == "RGBA" else source.convert("RGBA")
                    key = ("pixels", hashlib.sha256(prepared.tobytes()).digest(), prepared.size, *options)
                cached = self._lookup(key)
                if cached is not None:
                    return cached
            else:
                return None

            # 动态 cover 裁切：按目标尺寸的长宽比做中央裁切并缩放到目标尺寸
            if do_cover:
                prepared = ImageOps.fit(prepared, size, Image.Resampling.LANCZOS, centering=(0.5, 0.5))
            else:
                prepared = ImageOps.contain(prepared, size, Image.Resampling.LANCZOS)

            output = io.BytesIO()
            prepared.save(output, format="PNG")
            uri = "data:image/png;base64," + base64.b64encode(output.getvalue()).decode("ascii")
            self._store(key, uri)
            return uri
        except (OSError, ValueError, Image.DecompressionBombError):
            return None
