# SPDX-License-Identifier: GPL-3.0-or-later
"""轻量 NIKKE 风格图片卡渲染。"""

from __future__ import annotations

import textwrap
import uuid
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageDraw, ImageFont
from .card_theme import UI_COLORS

@lru_cache(maxsize=128)
def _font(path: str, size: int):
    # 仅复用有界字体对象；不缓存用户数据或渲染结果。
    return ImageFont.truetype(path, size)

class CardRenderer:
    WIDTH = 1200

    def __init__(self, output_dir: str | Path, font_dir: str | Path):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        font_dir = Path(font_dir)
        regular = font_dir / "NotoSansHans-Regular.otf"
        medium = font_dir / "NotoSansHans-Medium.otf"
        self.regular_path = str(regular if regular.exists() else "DejaVuSans.ttf")
        self.medium_path = str(medium if medium.exists() else self.regular_path)

    def font(self, size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
        return _font(self.medium_path if bold else self.regular_path, size)

    @staticmethod
    def _wrap(text: str, width: int) -> list[str]:
        result: list[str] = []
        for paragraph in str(text).splitlines() or [""]:
            result.extend(textwrap.wrap(paragraph, width=width, break_long_words=True) or [""])
        return result

    def render(self, title: str, subtitle: str, rows: Iterable[tuple[str, str]], footer: str = "") -> str:
        normalized = [(str(k), str(v)) for k, v in rows]
        # 用真实像素宽度换行，中文、长英文与结果文本都完整保留。
        measure = ImageDraw.Draw(Image.new("RGB", (1, 1)))
        def wrap_pixels(value, width, size):
            lines = []
            for paragraph in str(value).splitlines() or [""]:
                if not paragraph:
                    lines.append("")
                while paragraph:
                    # 二分寻找可容纳的完整前缀，避免逐字重复测量整段文字。
                    low, high, count = 1, len(paragraph), 1
                    while low <= high:
                        middle = (low + high) // 2
                        if measure.textlength(paragraph[:middle], font=self.font(size)) <= width:
                            count, low = middle, middle + 1
                        else:
                            high = middle - 1
                    lines.append(paragraph[:count])
                    paragraph = paragraph[count:]
            return lines
        wrapped = [(wrap_pixels(k, 1050, 28), wrap_pixels(v, 1050, 27)) for k, v in normalized]
        heights = [(len(labels) + len(lines)) * 42 + 36 for labels, lines in wrapped]
        height = max(420, 210 + sum(heights) + 16 * len(heights) + 88)
        canvas = Image.new("RGB", (self.WIDTH, height), UI_COLORS["background"])
        draw = ImageDraw.Draw(canvas)
        draw.text((44, 24), "NIKKE / BLABLALINK", font=self.font(21, True), fill=UI_COLORS["accent"])
        draw.text((44, 64), title, font=self.font(44, True), fill=UI_COLORS["text"])
        draw.text((44, 130), subtitle, font=self.font(25), fill=UI_COLORS["muted"])
        y = 210
        for index, ((labels, lines), block_h) in enumerate(zip(wrapped, heights)):
            draw.rounded_rectangle((44, y, 1156, y + block_h), 12, fill=UI_COLORS["panel"], outline=UI_COLORS["border"])
            line_y = y + 16
            for label in labels:
                draw.text((68, line_y), label, font=self.font(28, True), fill=UI_COLORS["accent"], anchor="lt")
                line_y += 42
            for line in lines:
                # 仅强调明确的展示前缀，不把自由文本推断为执行状态。
                raw = normalized[index][1]
                tone = "warning" if raw.startswith("UNKNOWN_AFTER_ACTION") else next(
                    (color for prefix, color in (("成功：", "success"), ("待处理：", "warning"),
                     ("不可用：", "unknown"), ("失败：", "error")) if raw.startswith(prefix)), "text")
                draw.text((68, line_y), line, font=self.font(27), fill=UI_COLORS[tone], anchor="lt")
                line_y += 42
            y += block_h + 16
        stamp = footer or f"数据时间 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  ·  来源 BlaBlaLink"
        draw.line((44, height - 76, 1156, height - 76), fill=UI_COLORS["border"])
        draw.text((44, height - 58), stamp, font=self.font(21), fill=UI_COLORS["muted"])
        path = self.output_dir / f"card-{uuid.uuid4().hex}.png"
        canvas.save(path, "PNG", optimize=True)
        return str(path)

    def render_roster(self, nickname: str, characters: list[dict], name_map: dict[str, str]) -> str:
        sorted_chars = sorted(
            characters,
            key=lambda item: (int(item.get("combat", 0) or 0), int(item.get("lv", 0) or 0)),
            reverse=True,
        )
        rows = []
        for item in sorted_chars[:20]:
            code = str(item.get("name_code", ""))
            name = name_map.get(code, code or "未知妮姬")
            grade = int(item.get("grade", 0) or 0)
            core = int(item.get("core", 0) or 0)
            rows.append(
                (
                    name,
                    f"Lv.{item.get('lv', 1)}  战力 {item.get('combat', 0)}  技能 "
                    f"{item.get('skill1_lv', 1)}/{item.get('skill2_lv', 1)}/{item.get('ulti_skill_lv', 1)}  "
                    f"突破 {grade}  核心 {core}",
                )
            )
        subtitle = f"{nickname} · 共 {len(characters)} 名 · 按战力排序"
        if not rows:
            return self.render("妮姬练度一览", subtitle, [("暂无数据", "未获取到角色信息")])
        # 表格只改变排版；沿用既有排序、前二十名与正式名称映射。
        height = 280 + len(rows) * 88
        canvas = Image.new("RGB", (self.WIDTH, height), UI_COLORS["background"])
        draw = ImageDraw.Draw(canvas)
        draw.text((40, 24), "NIKKE / 妮姬练度一览", font=self.font(38, True), fill=UI_COLORS["text"])
        draw.text((40, 90), subtitle, font=self.font(24), fill=UI_COLORS["muted"])
        columns = (40, 490, 620, 820, 1030)
        widths = (425, 110, 175, 185, 130)
        for x, label in zip(columns, ("正式名称", "等级", "战力", "技能", "突破 / 核心")):
            draw.text((x, 153), label, font=self.font(23), fill=UI_COLORS["muted"])
        for index, ((name, _), item) in enumerate(zip(rows, sorted_chars[:20])):
            y = 198 + index * 88
            if index % 2 == 0:
                draw.rectangle((24, y - 8, 1176, y + 72), fill=UI_COLORS["panel"])
            values = (name, f"Lv.{item.get('lv', 1)}", str(item.get('combat', 0)),
                      f"{item.get('skill1_lv', 1)}/{item.get('skill2_lv', 1)}/{item.get('ulti_skill_lv', 1)}",
                      f"{int(item.get('grade', 0) or 0)} / {int(item.get('core', 0) or 0)}")
            for x, width, value in zip(columns, widths, values):
                size = 28
                while size > 20 and draw.textlength(value, font=self.font(size)) > width:
                    size -= 1
                while draw.textlength(value, font=self.font(size)) > width:
                    value = value[:-2] + "…"
                draw.text((x, y + 16), value, font=self.font(size), fill=UI_COLORS["text"], anchor="lt")
        draw.text((40, height - 52), "来源 BlaBlaLink · 按战力排序 · 最多显示 20 名", font=self.font(21), fill=UI_COLORS["muted"])
        path = self.output_dir / f"roster-{uuid.uuid4().hex}.png"
        canvas.save(path, "PNG", optimize=True)
        return str(path)

    def render_summary(self, rows: list[tuple[str, str]]) -> str:
        return self.render("每日任务汇总", f"参与账号 {len(rows)} 个", rows or [("暂无账号", "尚未有人启用推送")])

