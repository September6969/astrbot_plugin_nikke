# SPDX-License-Identifier: GPL-3.0-or-later
"""塔罗图片文件读取与逆位图像缓存适配器。"""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

from PIL import Image

from astrbot_plugin_nikke.features.tarot.models import DrawnTarotCard
from astrbot_plugin_nikke.features.tarot.service import TarotDeckRepository


class TarotImageProvider:
    """解析牌面图片，并为逆位牌生成物理旋转缓存。"""

    def __init__(
        self,
        deck: TarotDeckRepository,
        cache_dir: Path,
        *,
        rotate_reversed: bool = True,
    ) -> None:
        self.deck = deck
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.rotate_reversed = bool(rotate_reversed)

    def image_for(self, draw: DrawnTarotCard) -> Path | None:
        source = self.deck.resolve_image(draw.card)
        if source is None or not draw.is_reversed or not self.rotate_reversed:
            return source
        try:
            stat = source.stat()
        except OSError:
            return None
        fingerprint = hashlib.sha256(
            f"{source}:{stat.st_mtime_ns}:{stat.st_size}".encode("utf-8")
        ).hexdigest()[:12]
        safe_key = draw.card.key.replace(":", "_").replace("/", "_")
        output = self.cache_dir / f"{safe_key}_reversed_{fingerprint}.png"
        if output.is_file():
            return output
        try:
            with Image.open(source) as image:
                # 在源图模式下做精确 180° 旋转（不再把 RGB/JPEG 牌面升为 RGBA）；
                # 缓存保持无损 PNG，不给 JPEG 源叠加第二代有损压缩。
                rotated = _png_safe(image).transpose(Image.Transpose.ROTATE_180)
                temporary = output.with_suffix(".tmp.png")
                rotated.save(temporary, format="PNG", optimize=True)
                os.replace(temporary, output)
        except (OSError, ValueError):
            return source
        self._prune_stale(safe_key, keep=output.name)
        return output

    def _prune_stale(self, safe_key: str, *, keep: str) -> None:
        """删除同一张牌旧指纹的逆位缓存（牌面文件替换后遗留）。

        只匹配本目录下 ``<safe_key>_reversed_<12 位十六进制>.png`` 的精确文件名；
        仅在写入新缓存时触发，正在发送旧路径的极端并发情形只影响那一次发送。
        """
        pattern = re.compile(rf"{re.escape(safe_key)}_reversed_[0-9a-f]{{12}}\.png")
        try:
            entries = list(self.cache_dir.iterdir())
        except OSError:
            return
        for entry in entries:
            if entry.name == keep or not pattern.fullmatch(entry.name):
                continue
            try:
                entry.unlink()
            except OSError:
                continue


def _png_safe(image: Image.Image) -> Image.Image:
    """返回可无损写入 PNG 的图像，尽量保持源模式。"""
    if image.mode in {"RGB", "RGBA", "L", "LA"}:
        return image
    if image.mode == "P":
        return image.convert("RGBA" if "transparency" in image.info else "RGB")
    return image.convert("RGBA" if "A" in image.getbands() else "RGB")
