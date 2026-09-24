# SPDX-License-Identifier: GPL-3.0-or-later
"""塔罗图片文件读取与逆位图像缓存适配器。"""

from __future__ import annotations

import hashlib
import os
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
                rotated = image.convert("RGBA").rotate(180, expand=False)
                temporary = output.with_suffix(".tmp.png")
                rotated.save(temporary, format="PNG", optimize=True)
                os.replace(temporary, output)
        except (OSError, ValueError):
            return source
        return output
