# SPDX-License-Identifier: GPL-3.0-or-later
"""人物优先的1800×1000横向角色练度海报。"""

from __future__ import annotations

import math
import uuid
from pathlib import Path

from PIL import Image, ImageColor, ImageDraw, ImageOps

from .asset_manager import AssetManager
from .card_models import CharacterCardData, EquipmentData
from .card_theme import character_theme
from .renderer import CardRenderer


class CharacterCardRenderer(CardRenderer):
    WIDTH, HEIGHT = 1800, 1000
    ELEMENT_NAMES = {"fire": "燃烧", "water": "水冷", "wind": "风压", "electric": "电击", "iron": "铁甲"}
    CORPORATION_NAMES = {"elysion": "极乐净土", "missilis": "米西利斯", "tetra": "泰特拉", "pilgrim": "朝圣者", "abnormal": "反常"}
    BURST_NAMES = {"step1": "BURST I", "step2": "BURST II", "step3": "BURST III", "allstep": "BURST 全阶段"}
    SLOT_NAMES = {"head": "HEAD · 头部", "torso": "TORSO · 躯干", "arm": "ARM · 手臂", "leg": "LEG · 腿部"}

    def __init__(self, output_dir, font_dir, assets: AssetManager | None = None):
        super().__init__(output_dir, font_dir)
        self.assets = assets or AssetManager(Path(output_dir) / "cache", Path(__file__).parent / "assets")

    @staticmethod
    def _number(value):
        return "—" if value is None else f"{value:,}"

    @staticmethod
    def _option_value(option):
        if option.unit == "percent":
            return f"{option.value * 100:.2f}%"
        if option.unit == "flat":
            return f"{round(option.value):,}"
        return "待确认"

    @staticmethod
    def _label(value, mapping):
        return mapping.get(str(value).casefold(), str(value or "—"))

    def _text(self, draw, xy, text, size, color, *, width=None, bold=False):
        # 有限宽度字段按实际字宽缩放，长中文名称不会覆盖相邻数值。
        text = str(text).replace("\n", " ")
        font = self.font(size, bold)
        while width and draw.textlength(text, font=font) > width and size > 12:
            size -= 1
            font = self.font(size, bold)
        if width and draw.textlength(text, font=font) > width:
            while text and draw.textlength(text + "…", font=font) > width:
                text = text[:-1]
            text += "…"
        draw.text(xy, text, font=font, fill=color, anchor="lt")

    @staticmethod
    def _paste(canvas, image, box):
        x, y, width, height = box
        image = ImageOps.contain(image, (width, height), Image.Resampling.LANCZOS)
        canvas.alpha_composite(image, (x + (width - image.width) // 2, y + (height - image.height) // 2))

    def _panel(self, draw, box, title, theme):
        draw.rounded_rectangle(box, 14, fill=theme.panel, outline="#303744", width=1)
        x, y, _, _ = box
        draw.line((x + 22, y + 25, x + 44, y + 25), fill=theme.primary, width=3)
        self._text(draw, (x + 56, y + 16), title, 20, theme.muted)

    def draw_background(self, canvas, theme):
        draw = ImageDraw.Draw(canvas)
        base, primary = ImageColor.getrgb(theme.background), ImageColor.getrgb(theme.primary)
        for x in range(self.WIDTH):
            weight = 0.16 * max(0, 1 - x / 1150)
            color = tuple(round(a * (1 - weight) + b * weight) for a, b in zip(base, primary))
            draw.line((x, 0, x, self.HEIGHT), fill=color)
        for x in range(-600, 1700, 170):
            draw.line((x, 1000, x + 550, 0), fill="#242A35", width=1)
        draw.line((40, 146, 1760, 146), fill="#46505D", width=1)
        draw.line((40, 146, 220, 146), fill=theme.primary, width=3)

    def draw_header(self, canvas, data, theme):
        draw = ImageDraw.Draw(canvas)
        self._text(draw, (40, 32), "NIKKE", 42, theme.text, bold=True)
        self._text(draw, (42, 91), "CHARACTER BUILD", 18, theme.primary)
        self._text(draw, (305, 27), data.name_cn, 60, theme.text, width=900, bold=True)
        self._text(draw, (308, 100), data.name_en.upper(), 26, theme.muted, width=890)
        self._text(draw, (1410, 35), f"Lv.{data.level:,}", 54, theme.text, width=345, bold=True)
        self._text(draw, (1412, 105), "PERSONAL BUILD / 个人练度", 18, theme.muted, width=345)

    def draw_character_area(self, canvas, data, theme, portrait=None):
        area = Image.new("RGBA", (600, 740), theme.background)
        draw = ImageDraw.Draw(area)
        base, accent = ImageColor.getrgb(theme.background), ImageColor.getrgb(theme.primary)
        for y in range(740):
            weight = 0.24 * (1 - abs(y - 330) / 740)
            color = tuple(round(a * (1 - weight) + b * weight) for a, b in zip(base, accent))
            draw.line((0, y, 600, y), fill=color)
        draw.ellipse((15, 75, 585, 645), outline=(*accent, 90), width=2)
        draw.ellipse((65, 125, 535, 595), outline=(*accent, 70), width=1)
        self._text(draw, (22, 48), data.name_en.upper() or "NIKKE", 105, "#42404C", width=555, bold=True)
        if portrait is None:
            portrait = self.assets.get_character_portrait(data.name_code, data.resource_id)
        bounds = portrait.getbbox()
        if bounds:
            portrait = portrait.crop(bounds)
        # 保留人物上半身的视觉尺寸，过长立绘由面板底部自然裁切。
        scale = min(590 / portrait.width, 890 / portrait.height)
        portrait = portrait.resize((max(1, round(portrait.width * scale)), max(1, round(portrait.height * scale))), Image.Resampling.LANCZOS)
        area.alpha_composite(portrait, ((600 - portrait.width) // 2, 18))
        overlay = Image.new("RGBA", area.size)
        ink = ImageDraw.Draw(overlay)
        for y in range(585, 740):
            ink.line((0, y, 600, y), fill=(*base, round(235 * (y - 585) / 155)))
        area = Image.alpha_composite(area, overlay)
        draw = ImageDraw.Draw(area)
        draw.line((18, 20, 90, 20), fill=theme.primary, width=3)
        draw.line((18, 20, 18, 85), fill=theme.primary, width=3)
        draw.line((580, 645, 580, 719, 510, 719), fill=theme.primary, width=3)
        for index in range(32):
            x = 28 + index * 5
            draw.line((x, 697, x, 718 if index % 3 else 708), fill=theme.muted, width=1 + index % 2)
        self._text(draw, (28, 628), data.name_en.upper() or "NIKKE", 38, theme.text, width=545, bold=True)
        self._text(draw, (220, 699), "TACTICAL ARCHIVE", 17, theme.primary)
        canvas.alpha_composite(area, (40, 165))

    def draw_combat_panel(self, canvas, data, theme):
        draw = ImageDraw.Draw(canvas)
        self._panel(draw, (660, 165, 1310, 434), "COMBAT POWER / 战斗力", theme)
        self._text(draw, (686, 212), self._number(data.combat), 68, theme.text, width=590, bold=True)
        tags = " · ".join([str(data.rarity or "—"), self._label(data.element, self.ELEMENT_NAMES), str(data.weapon or "—"), self._label(data.burst, self.BURST_NAMES)])
        self._text(draw, (686, 300), tags, 24, theme.primary, width=594)
        draw.line((686, 343, 1284, 343), fill="#343B46")
        for index, (label, value) in enumerate([("HP / 生命", data.hp), ("ATK / 攻击", data.attack), ("DEF / 防御", data.defense)]):
            x = 686 + index * 204
            self._text(draw, (x, 357), label, 18, theme.muted)
            self._text(draw, (x, 388), self._number(value), 28, theme.text, width=184, bold=True)

    def draw_growth_panel(self, canvas, data, theme):
        draw = ImageDraw.Draw(canvas)
        self._panel(draw, (660, 450, 1310, 707), "DEVELOPMENT / 养成", theme)
        cells = [("SKILL / 技能", f"{data.skill1_level} / {data.skill2_level} / {data.burst_skill_level}"),
                 ("LIMIT BREAK / 突破", "★" * min(3, max(0, data.grade)) or "未突破"),
                 ("CORE / 核心", f"+{data.core}"),
                 ("BOND / 好感", f"Lv.{data.bond_level}" if data.bond_level is not None else "—")]
        for index, (label, value) in enumerate(cells):
            x, y = 682 + index % 3 * 209, 501 + index // 3 * 99
            self._text(draw, (x, y), label, 17, theme.muted, width=193)
            self._text(draw, (x, y + 32), value, 31, theme.primary if index == 1 else theme.text, width=193, bold=True)
        for index, (label, item, getter) in enumerate([
            ("FAVORITE / 收藏品", data.favorite_item, self.assets.get_favorite_item_icon),
            ("CUBE / 魔方", data.cube, self.assets.get_cube_icon),
        ]):
            x, y = 891 + index * 209, 600
            self._text(draw, (x, y), label, 17, theme.muted, width=193)
            self._paste(canvas, getter(item.tid if item else None), (x, y + 28, 45, 50))
            self._text(draw, (x + 52, y + 30), (item.display_name or "已装备") if item else "未装备", 21, theme.text, width=138)
            self._text(draw, (x + 52, y + 59), f"Lv.{item.level}" if item and item.level is not None else "—", 18, theme.primary)

    def draw_equipment_column(self, canvas, data, theme):
        for index, slot in enumerate(self.SLOT_NAMES):
            item = data.equipment.get(slot, EquipmentData(slot))
            x, y = 1330, 165 + index * 189
            draw = ImageDraw.Draw(canvas)
            draw.rounded_rectangle((x, y, 1760, y + 173), 14, fill=theme.panel, outline="#343B46")
            draw.rounded_rectangle((x + 14, y + 13, x + 76, y + 75), 8, fill="#282E3A")
            self._paste(canvas, self.assets.get_equipment_icon(slot, item.equipment_id if item.equipped else None), (x + 17, y + 16, 56, 56))
            self._text(draw, (x + 90, y + 17), self.SLOT_NAMES[slot], 24, theme.text, width=317, bold=True)
            status = f"Lv.{item.level}" if item.equipped and item.level is not None else ("已装备" if item.equipped else "未装备")
            self._text(draw, (x + 90, y + 51), status, 22, theme.primary if item.equipped else theme.muted)
            options = item.options if item.equipped else []
            if not options:
                self._text(draw, (x + 20, y + 112), "暂无装备词条" if item.equipped else "未装备", 21, theme.muted)
            for row, option in enumerate(options):
                # 一个槽位可能展开多个效果，压缩行距而不静默截断。
                step = min(28, 79 / max(1, len(options)))
                yy = y + 86 + row * step
                name = option.display_name if option.unit != "unknown" else "未识别词条"
                size = max(12, min(22, int(step - 3)))
                self._text(draw, (x + 20, yy), name, size, theme.text, width=266)
                self._text(draw, (x + 301, yy), self._option_value(option), size, theme.primary, width=112, bold=True)

    def draw_option_summary(self, canvas, data, theme):
        draw = ImageDraw.Draw(canvas)
        self._panel(draw, (660, 723, 1310, 905), "OVERLOAD SUMMARY / 词条汇总", theme)
        if not data.option_totals:
            self._text(draw, (685, 804), "暂无已确认单位的装备词条", 23, theme.muted, width=600)
            return
        rows = max(2, math.ceil(len(data.option_totals) / 3))
        step = 121 / rows
        for index, item in enumerate(data.option_totals):
            x, y = 682 + index % 3 * 209, 770 + index // 3 * step
            size = max(12, min(19, int(step * 0.34)))
            self._text(draw, (x, y), item.display_name, size, theme.muted, width=193)
            self._text(draw, (x, y + step * 0.43), self._option_value(item), min(29, max(12, int(step * 0.46))), theme.primary, width=193, bold=True)

    def draw_footer(self, canvas, data, theme):
        draw = ImageDraw.Draw(canvas)
        draw.line((40, 928, 1760, 928), fill="#424954")
        footer = f"{data.commander_name} · {data.fetched_at} · v{data.plugin_version} · BlaBlaLink"
        self._text(draw, (40, 948), footer, 21, theme.muted, width=1325)
        self._text(draw, (1490, 949), "NIKKE / BUILD ARCHIVE", 18, theme.primary, width=270)

    def render_character(self, data: CharacterCardData) -> str:
        portrait = self.assets.get_character_portrait(data.name_code, data.resource_id)
        theme = character_theme(data.corporation, data.element, portrait)
        canvas = Image.new("RGBA", (self.WIDTH, self.HEIGHT), theme.background)
        self.draw_background(canvas, theme)
        self.draw_character_area(canvas, data, theme, portrait)
        self.draw_header(canvas, data, theme)
        self.draw_combat_panel(canvas, data, theme)
        self.draw_growth_panel(canvas, data, theme)
        self.draw_equipment_column(canvas, data, theme)
        self.draw_option_summary(canvas, data, theme)
        for index, icon in enumerate([
            self.assets.get_corporation_icon(data.corporation), self.assets.get_element_icon(data.element),
            self.assets.get_weapon_icon(data.weapon), self.assets.get_burst_icon(data.burst),
        ]):
            self._paste(canvas, icon, (67 + index * 67, 717, 48, 48))
        self._text(ImageDraw.Draw(canvas), (67, 768), self._label(data.corporation, self.CORPORATION_NAMES), 18, theme.secondary, width=535)
        self.draw_footer(canvas, data, theme)
        path = self.output_dir / f"character-{uuid.uuid4().hex}.png"
        canvas.convert("RGB").save(path, "PNG", optimize=True)
        return str(path)
