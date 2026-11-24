# SPDX-License-Identifier: GPL-3.0-or-later
"""九宫格本地 PNG 渲染（29）。

T2I 不可用时用 Pillow 直接合成 3x3 图片：有本地立绘就用立绘，没有就使用按身份
稳定推导的占位色块与文字，保证同一输入始终得到同一版面。
"""

from __future__ import annotations

import hashlib
import io
import os
import tempfile
from pathlib import Path
from typing import Any, Iterable, Mapping

from PIL import Image, ImageDraw, ImageFont

CELL_COUNT = 9
DEFAULT_SIZE = 1080
_FONT_CANDIDATES = (
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/arialbd.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
)
_PALETTE = (
    (58, 74, 112), (92, 61, 84), (54, 92, 84), (98, 82, 48),
    (70, 58, 108), (104, 58, 58), (48, 84, 108), (84, 96, 56), (96, 68, 96),
)


def _font(size: int) -> ImageFont.ImageFont:
    for candidate in _FONT_CANDIDATES:
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def _placeholder_color(name_code: str) -> tuple[int, int, int]:
    digest = hashlib.sha256(str(name_code or "unknown").encode("utf-8")).digest()
    return _PALETTE[digest[0] % len(_PALETTE)]


def compose_grid_png(
    cells: Iterable[Mapping[str, Any]],
    *,
    size: int = DEFAULT_SIZE,
    portraits: Mapping[str, bytes] | None = None,
    title: str = "本命九宫格",
) -> bytes:
    """合成本地 PNG；cells 顺序即版面顺序，必须恰好九项。"""
    items = [dict(cell) for cell in cells]
    if len(items) != CELL_COUNT:
        raise ValueError("九宫格必须恰好包含九项")
    if not 300 <= size <= 2400:
        raise ValueError("图片尺寸超出 300–2400")
    cell_size = size // 3
    canvas = Image.new("RGB", (size, size), (17, 21, 28))
    draw = ImageDraw.Draw(canvas)
    title_font = _font(max(16, cell_size // 9))
    name_font = _font(max(14, cell_size // 11))
    initial_font = _font(max(28, cell_size // 3))
    margin = max(4, cell_size // 24)
    for index, cell in enumerate(items):
        row, column = divmod(index, 3)
        left = column * cell_size
        top = row * cell_size
        box = (left + margin, top + margin, left + cell_size - margin, top + cell_size - margin)
        draw.rectangle(box, fill=(28, 33, 43), outline=(52, 60, 76), width=2)
        name = str(cell.get("name") or "未知妮姬")
        name_code = str(cell.get("name_code") or index)
        portrait = (portraits or {}).get(name_code)
        image_area = (
            box[0] + margin,
            box[1] + margin,
            box[2] - margin,
            box[3] - max(margin, cell_size // 6),
        )
        if portrait:
            try:
                with Image.open(io.BytesIO(portrait)) as source:
                    picture = source.convert("RGB")
                    scale = min(
                        image_area[2] - image_area[0],
                        image_area[3] - image_area[1],
                    ) / max(1, min(picture.size))
                    resized = picture.resize(
                        (max(1, int(picture.width * scale)), max(1, int(picture.height * scale))),
                        Image.LANCZOS,
                    )
                    offset = (
                        image_area[0] + (image_area[2] - image_area[0] - resized.width) // 2,
                        image_area[1] + (image_area[3] - image_area[1] - resized.height) // 2,
                    )
                    canvas.paste(resized, offset)
            except Exception:
                portrait = None
        if not portrait:
            draw.rectangle(image_area, fill=_placeholder_color(name_code))
            initial = name[:1] or "?"
            bbox = draw.textbbox((0, 0), initial, font=initial_font)
            draw.text(
                (
                    image_area[0] + (image_area[2] - image_area[0] - (bbox[2] - bbox[0])) // 2,
                    image_area[1] + (image_area[3] - image_area[1] - (bbox[3] - bbox[1])) // 2,
                ),
                initial,
                font=initial_font,
                fill=(236, 240, 246),
            )
        draw.text(
            (box[0] + margin, box[3] - max(margin, cell_size // 6) + 2),
            name,
            font=name_font,
            fill=(230, 234, 240),
        )
    draw.text((margin, margin), title, font=title_font, fill=(200, 208, 220))
    buffer = io.BytesIO()
    canvas.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def write_grid_png(
    directory: str | Path,
    cells: Iterable[Mapping[str, Any]],
    *,
    portraits: Mapping[str, bytes] | None = None,
) -> str:
    """写入稳定命名的 PNG 文件并返回绝对路径；内容相同则复用同一文件。"""
    items = [dict(cell) for cell in cells]
    data = compose_grid_png(items, portraits=portraits)
    digest = hashlib.sha256(data).hexdigest()[:24]
    target_dir = Path(directory)
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / f"favorite-grid-{digest}.png"
    if not path.is_file():
        with tempfile.NamedTemporaryFile(
            "wb", dir=target_dir, prefix=".favorite-grid-", suffix=".tmp", delete=False
        ) as handle:
            temporary = Path(handle.name)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
    return str(path.resolve())


__all__ = ["CELL_COUNT", "compose_grid_png", "write_grid_png"]
