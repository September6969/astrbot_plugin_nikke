# SPDX-License-Identifier: GPL-3.0-or-later
"""生成 assets/fallback/ 下的语义兜底 PNG 素材。"""

from __future__ import annotations

import logging
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(levelname)s] %(message)s")
logger = logging.getLogger("generate_fallback_assets")


def generate_fallbacks(output_dir: Path | str) -> None:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    # 1. 技能 S1 兜底 (128x128 RGBA)
    img_s1 = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
    d1 = ImageDraw.Draw(img_s1)
    # 底色圆角背景
    d1.rounded_rectangle([(8, 8), (120, 120)], radius=20, fill=(35, 45, 65, 230), outline=(70, 130, 210, 240), width=4)
    # S1 标志
    d1.rectangle([(30, 30), (98, 98)], outline=(120, 180, 255, 180), width=2)
    # 居中文字 S1
    d1.text((42, 42), "S1", fill=(220, 235, 255, 255), font_size=40)
    img_s1.save(out / "skill_s1.png", format="PNG")

    # 2. 技能 S2 兜底 (128x128 RGBA)
    img_s2 = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
    d2 = ImageDraw.Draw(img_s2)
    d2.rounded_rectangle([(8, 8), (120, 120)], radius=20, fill=(45, 35, 65, 230), outline=(140, 70, 210, 240), width=4)
    d2.rectangle([(30, 30), (98, 98)], outline=(190, 130, 255, 180), width=2)
    d2.text((42, 42), "S2", fill=(240, 225, 255, 255), font_size=40)
    img_s2.save(out / "skill_s2.png", format="PNG")

    # 3. 技能 Burst 兜底 (128x128 RGBA)
    img_burst = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
    db = ImageDraw.Draw(img_burst)
    db.rounded_rectangle([(8, 8), (120, 120)], radius=20, fill=(65, 40, 30, 230), outline=(220, 100, 50, 240), width=4)
    # 六边形或菱形
    db.polygon([(64, 24), (104, 64), (64, 104), (24, 64)], outline=(255, 160, 80, 200), width=3)
    db.text((50, 42), "B", fill=(255, 235, 210, 255), font_size=42)
    img_burst.save(out / "skill_burst.png", format="PNG")

    # 4. Cube 兜底 (128x128 RGBA)
    img_cube = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
    dc = ImageDraw.Draw(img_cube)
    color = (130, 175, 230, 230)
    dc.polygon([(64, 18), (110, 44), (110, 92), (64, 116), (18, 92), (18, 44)], outline=color, width=4)
    dc.line([(18, 44), (64, 70), (110, 44)], fill=color, width=4)
    dc.line([(64, 70), (64, 116)], fill=color, width=4)
    img_cube.save(out / "cube.png", format="PNG")

    # 5. Favorite item 兜底 (128x128 RGBA)
    img_fav = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
    df = ImageDraw.Draw(img_fav)
    color_fav = (235, 195, 80, 240)
    # 五角星
    pts = [(64, 18), (77, 44), (107, 48), (85, 70), (90, 100), (64, 85), (38, 100), (43, 70), (21, 48), (51, 44)]
    df.polygon(pts, outline=color_fav, fill=(80, 65, 30, 180), width=4)
    img_fav.save(out / "favorite_item.png", format="PNG")

    # 6. Portrait 兜底 (600x900 RGBA)
    img_p = Image.new("RGBA", (600, 900), (0, 0, 0, 0))
    dp = ImageDraw.Draw(img_p)
    p_color = (164, 178, 205, 120)
    dp.ellipse((213, 66, 385, 244), fill=p_color)
    dp.polygon(
        [
            (245, 224), (351, 224), (454, 340), (403, 560),
            (470, 850), (332, 900), (300, 616), (269, 900),
            (133, 850), (197, 560), (146, 340)
        ],
        fill=p_color,
    )
    img_p.save(out / "portrait.png", format="PNG")

    logger.info("Generated all 6 fallback PNGs in %s", out)


if __name__ == "__main__":
    base_dir = Path(__file__).resolve().parent.parent
    fallback_dir = base_dir / "assets" / "fallback"
    generate_fallbacks(fallback_dir)
