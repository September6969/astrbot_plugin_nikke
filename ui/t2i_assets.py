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

    def encode(self, source: Image.Image | Path | None, size=(272, 236), crop_16_9: bool = False) -> str | None:
        if source is None:
            return None
        if not (0 < size[0] <= 1600 and 0 < size[1] <= 2400):
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

            # 9:16 → 16:9 居中裁切：若源图为纵向（宽高比 < 1.0），
            # 从垂直中心裁出与目标比例对应的区域，再缩放到 size。
            if crop_16_9 and prepared.width < prepared.height:
                target_ratio = size[0] / size[1]          # 16/9 ≈ 1.778
                crop_h = int(prepared.width / target_ratio)
                if 0 < crop_h <= prepared.height:
                    top = (prepared.height - crop_h) // 2
                    prepared = prepared.crop((0, top, prepared.width, top + crop_h))

            key = (hashlib.sha256(prepared.tobytes()).digest(), prepared.size, size, crop_16_9, "PNG")
            with self._lock:
                if key in self._cache:
                    self._cache.move_to_end(key)
                    return self._cache[key]
            prepared = ImageOps.fit(prepared, size, Image.Resampling.LANCZOS) if crop_16_9 else ImageOps.contain(prepared, size, Image.Resampling.LANCZOS)
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

