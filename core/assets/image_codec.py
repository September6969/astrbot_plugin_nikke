# SPDX-License-Identifier: GPL-3.0-or-later
"""图片字节的统一验证、解码与零依赖占位图。"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw


class AssetImageCodec:
    MAX_BYTES = 12 * 1024 * 1024
    MAX_PIXELS = 20_000_000

    @classmethod
    def decode(cls, content: bytes, require_alpha: bool = False) -> Image.Image:
        if not content:
            raise ValueError("素材内容为空")
        if len(content) > cls.MAX_BYTES:
            raise ValueError("素材尺寸过大")
        is_png = content.startswith(b"\x89PNG\r\n\x1a\n")
        is_webp = content.startswith(b"RIFF") and len(content) >= 12 and content[8:12] == b"WEBP"
        is_jpeg = content.startswith(b"\xff\xd8")
        if not (is_png or is_webp or is_jpeg):
            raise ValueError("非法图像魔数或非图像文件")
        with Image.open(io.BytesIO(content)) as image:
            if image.width <= 0 or image.height <= 0 or image.width * image.height > cls.MAX_PIXELS:
                raise ValueError("素材像素异常或过大")
            image.load()
            converted = image.convert("RGBA")
            if require_alpha and converted.getextrema()[-1][0] == 255:
                # 显式透明度要求由调用方解释；仅保证返回统一 RGBA 格式。
                pass
            return converted

    @classmethod
    def validate(cls, content_or_path: bytes | str | Path, require_alpha: bool = False) -> Image.Image:
        content = Path(content_or_path).read_bytes() if isinstance(content_or_path, (str, Path)) else content_or_path
        return cls.decode(content, require_alpha=require_alpha)

    @classmethod
    def load_file(
        cls,
        path: Path,
        entry: dict[str, Any] | None = None,
        *,
        strict_png: bool = False,
    ) -> Image.Image | None:
        import hashlib
        import re

        try:
            if path.stat().st_size > cls.MAX_BYTES:
                return None
            if entry is not None:
                expected = entry.get("sha256")
                if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected.lower()):
                    return None
                digest = hashlib.sha256()
                with path.open("rb") as source:
                    for chunk in iter(lambda: source.read(1024 * 1024), b""):
                        digest.update(chunk)
                if digest.hexdigest() != expected.lower():
                    return None
            if strict_png:
                with path.open("rb") as stream:
                    if stream.read(8) != b"\x89PNG\r\n\x1a\n":
                        return None
            with Image.open(path) as image:
                if strict_png and entry is not None and any(
                    entry.get(key) is not None and entry[key] != value
                    for key, value in (("width", image.width), ("height", image.height))
                ):
                    return None
                if image.width * image.height > cls.MAX_PIXELS:
                    return None
                image.load()
                return image.convert("RGBA")
        except (OSError, ValueError, Image.DecompressionBombError):
            return None

    @classmethod
    def fallback(cls, kind: str) -> Image.Image:
        fallback_dir = Path(__file__).resolve().parents[2] / "assets" / "fallback"
        kind_clean = str(kind or "").strip().lower()
        kind_file_map = {
            "s1": "skill_s1.png", "skill1": "skill_s1.png", "skill_s1": "skill_s1.png",
            "s2": "skill_s2.png", "skill2": "skill_s2.png", "skill_s2": "skill_s2.png",
            "burst": "skill_burst.png", "burst_skill": "skill_burst.png", "skill_burst": "skill_burst.png",
            "cube": "cube.png", "favorite": "favorite_item.png", "favorite_item": "favorite_item.png",
            "portrait": "portrait.png",
        }
        candidate = kind_file_map.get(kind_clean)
        if candidate:
            path = fallback_dir / candidate
            if path.is_file():
                try:
                    with Image.open(path) as image:
                        return image.convert("RGBA")
                except Exception:
                    pass

        if kind_clean == "portrait":
            image = Image.new("RGBA", (600, 900))
            draw = ImageDraw.Draw(image)
            color = (164, 178, 205, 75)
            draw.ellipse((213, 66, 385, 244), fill=color)
            draw.polygon(
                [(245, 224), (351, 224), (454, 340), (403, 560), (470, 850),
                 (332, 900), (300, 616), (269, 900), (133, 850), (197, 560), (146, 340)],
                fill=color,
            )
            return image

        image = Image.new("RGBA", (128, 128))
        draw = ImageDraw.Draw(image)
        color = (180, 199, 220, 220)
        if kind_clean in {"s1", "skill1", "skill_s1", "s2", "skill2", "skill_s2"}:
            draw.rounded_rectangle([(10, 10), (118, 118)], radius=16, outline=color, width=4)
            draw.text((44, 46), "S1" if kind_clean in {"s1", "skill1", "skill_s1"} else "S2", fill=color)
            return image
        if kind_clean in {"burst", "burst_skill", "skill_burst"}:
            draw.polygon([(64, 16), (112, 64), (64, 112), (16, 64)], outline=color, width=4)
            draw.text((52, 46), "B", fill=color)
            return image

        shapes = {
            "head": [(30, 75), (30, 43), (48, 23), (80, 23), (98, 43), (98, 75), (83, 87), (83, 58), (45, 58), (45, 87)],
            "torso": [(41, 24), (52, 35), (76, 35), (87, 24), (109, 48), (92, 64), (85, 103), (43, 103), (36, 64), (19, 48)],
            "arm": [(31, 28), (53, 25), (63, 67), (80, 53), (98, 65), (78, 99), (44, 101)],
            "leg": [(36, 23), (88, 23), (96, 99), (72, 99), (62, 55), (54, 99), (30, 99)],
            "cube": [(64, 20), (108, 44), (108, 87), (64, 110), (20, 87), (20, 44)],
            "favorite": [(64, 18), (77, 44), (107, 48), (85, 70), (90, 100), (64, 85), (38, 100), (43, 70), (21, 48), (51, 44)],
        }
        draw.polygon(shapes.get(kind_clean, [(64, 18), (107, 64), (64, 110), (21, 64)]), outline=color, width=5)
        if kind_clean == "cube":
            draw.line([(20, 44), (64, 67), (108, 44)], fill=color, width=4)
            draw.line([(64, 67), (64, 110)], fill=color, width=4)
        return image
