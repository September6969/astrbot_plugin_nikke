"""仅将已准备的本地图片转成有界、缩放后的 Data URI。"""
import base64
import hashlib
import io
from collections import OrderedDict
from pathlib import Path
from threading import Lock

from PIL import Image, ImageOps


class T2IAssetResolver:
    def __init__(self, max_entries: int = 32, max_bytes: int = 8 * 1024 * 1024):
        self.max_entries = max(1, max_entries)
        self.max_bytes = max(1, max_bytes)
        self._cache: OrderedDict[tuple, str] = OrderedDict()
        self._bytes = 0
        self._lock = Lock()

    def encode(self, source: Image.Image | Path | None, size=(272, 236)) -> str | None:
        if source is None:
            return None
        if not (0 < size[0] <= 1600 and 0 < size[1] <= 1000):
            raise ValueError("无效的目标图片尺寸")
        try:
            if isinstance(source, Path):
                if source.stat().st_size > 12 * 1024 * 1024:
                    return None
                with Image.open(source) as opened:
                    if opened.width * opened.height > 20_000_000:
                        return None
                    prepared = opened.convert("RGBA")
            elif isinstance(source, Image.Image):
                if source.width * source.height > 20_000_000:
                    return None
                prepared = source.convert("RGBA")
            else:
                return None
            key = (hashlib.sha256(prepared.tobytes()).digest(), prepared.size, size, "PNG")
            with self._lock:
                if key in self._cache:
                    self._cache.move_to_end(key)
                    return self._cache[key]
            prepared = ImageOps.contain(prepared, size, Image.Resampling.LANCZOS)
            output = io.BytesIO()
            prepared.save(output, format="PNG")
            uri = "data:image/png;base64," + base64.b64encode(output.getvalue()).decode("ascii")
            with self._lock:
                if key not in self._cache and len(uri) <= self.max_bytes:
                    self._cache[key] = uri
                    self._bytes += len(uri)
                    while len(self._cache) > self.max_entries or self._bytes > self.max_bytes:
                        _, removed = self._cache.popitem(last=False)
                        self._bytes -= len(removed)
            return uri
        except (OSError, ValueError, Image.DecompressionBombError):
            return None
