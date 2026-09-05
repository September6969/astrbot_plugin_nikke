# SPDX-License-Identifier: GPL-3.0-or-later
"""战役历史通关阵容 1400px 暗色战术卡片渲染器。"""

from __future__ import annotations

import uuid
from pathlib import Path

from PIL import Image, ImageColor, ImageDraw, ImageOps

from .asset_manager import AssetManager
from .campaign_history_models import ClearLineupStatus, StageClearRecord
from .renderer import CardRenderer

THEME = {
    "background": "#14171D",
    "panel": "#1B2028",
    "panel_border": "#2D3442",
    "primary": "#38B6FF",
    "accent_hard": "#FF4655",
    "text": "#F0F4F8",
    "muted": "#7E8B9B",
    "badge_bg": "#222936",
}


class CampaignHistoryRenderer(CardRenderer):
    WIDTH = 1400

    def __init__(self, output_dir: str | Path, font_dir: str | Path, assets: AssetManager | None = None):
        super().__init__(output_dir, font_dir)
        self.assets = assets or AssetManager(Path(output_dir) / "cache", Path(__file__).parent / "assets")

    def _text(self, draw, xy, text, size, color, *, width=None, bold=False):
        text = str(text).replace("\n", " ")
        font = self.font(size, bold)
        while width and draw.textlength(text, font=font) > width and size > 11:
            size -= 1
            font = self.font(size, bold)
        if width and draw.textlength(text, font=font) > width:
            while text and draw.textlength(text + "…", font=font) > width:
                text = text[:-1]
            text += "…"
        draw.text(xy, text, font=font, fill=color, anchor="lt")

    def _text_right(self, draw, xy, text, size, color, *, bold=False):
        font = self.font(size, bold)
        draw.text(xy, str(text), font=font, fill=color, anchor="rt")

    def _paste(self, canvas, image, box):
        x, y, width, height = box
        contained = ImageOps.contain(image, (width, height), Image.Resampling.LANCZOS)
        canvas.alpha_composite(contained, (x + (width - contained.width) // 2, y + (height - contained.height) // 2))

    def render_campaign_history(self, record: StageClearRecord) -> str:
        is_hard = record.mode.upper() == "HARD"
        primary_color = THEME["accent_hard"] if is_hard else THEME["primary"]

        # 动态计算高度：正常5人卡 vs 空态
        if record.status == ClearLineupStatus.AVAILABLE and record.members:
            height = 820
        else:
            height = 540

        canvas = Image.new("RGBA", (self.WIDTH, height), THEME["background"])
        draw = ImageDraw.Draw(canvas)

        # 顶部战术线条装饰
        accent_rgb = ImageColor.getrgb(primary_color)
        for x in range(self.WIDTH):
            weight = 0.15 * max(0, 1 - x / 800)
            base_rgb = ImageColor.getrgb(THEME["background"])
            c = tuple(round(a * (1 - weight) + b * weight) for a, b in zip(base_rgb, accent_rgb))
            draw.line((x, 0, x, 6), fill=c)

        for x in range(-200, self.WIDTH + 300, 140):
            draw.line((x, 0, x - 100, height), fill="#1A1F27", width=1)

        # 头部
        padding = 50
        self._text(draw, (padding, 40), "CAMPAIGN CLEAR ARCHIVE", 16, primary_color, bold=True)
        mode_label = "HARD / 困难难度" if is_hard else "NORMAL / 普通难度"
        self._text(draw, (padding, 64), f"STAGE {record.stage_name} · {mode_label}", 40, THEME["text"], bold=True)

        if record.status == ClearLineupStatus.AVAILABLE and record.members:
            combat_str = f"{record.total_combat:,}"
            self._text_right(draw, (self.WIDTH - padding, 46), "TOTAL COMBAT / 阵容总战力", 16, THEME["muted"])
            self._text_right(draw, (self.WIDTH - padding, 68), combat_str, 36, primary_color, bold=True)

        draw.line((padding, 126, self.WIDTH - padding, 126), fill="#2D3442", width=1)

        # 内容区
        if record.status == ClearLineupStatus.AVAILABLE and record.members:
            card_width = (self.WIDTH - padding * 2 - 4 * 16) // 5
            card_height = 550
            card_y = 150

            for index, member in enumerate(record.members[:5]):
                card_x = padding + index * (card_width + 16)
                # 槽位卡背景
                draw.rounded_rectangle(
                    (card_x, card_y, card_x + card_width, card_y + card_height),
                    12,
                    fill=THEME["panel"],
                    outline=THEME["panel_border"],
                    width=1,
                )
                # 顶部槽位标签
                slot_bg = (card_x + 12, card_y + 12, card_x + card_width - 12, card_y + 40)
                draw.rounded_rectangle(slot_bg, 6, fill=THEME["badge_bg"])
                self._text(
                    draw,
                    (card_x + 22, card_y + 16),
                    f"POSITION 0{member.slot}",
                    14,
                    primary_color,
                    bold=True,
                )

                # 角色立绘区域
                portrait = self.assets.get_character_portrait(member.tid, member.resource_id)
                portrait_box = (card_x + 14, card_y + 48, card_width - 28, 330)
                # 浅灰底衬
                draw.rounded_rectangle(
                    (portrait_box[0], portrait_box[1], portrait_box[0] + portrait_box[2], portrait_box[1] + portrait_box[3]),
                    8,
                    fill="#151A22",
                )
                self._paste(canvas, portrait, portrait_box)

                # 下方信息区
                info_y = card_y + 395
                draw.line((card_x + 14, info_y, card_x + card_width - 14, info_y), fill="#28303D", width=1)

                self._text(draw, (card_x + 16, info_y + 12), member.name_cn, 21, THEME["text"], width=card_width - 32, bold=True)
                self._text(draw, (card_x + 16, info_y + 42), f"Lv.{member.level}", 19, primary_color, bold=True)
                self._text(draw, (card_x + 16, info_y + 70), "单体战力", 14, THEME["muted"])
                self._text(draw, (card_x + 16, info_y + 90), f"{member.combat:,}", 22, THEME["text"], bold=True)

        else:
            # 空态或异常提示面板
            msg_box = (padding, 160, self.WIDTH - padding, height - 100)
            draw.rounded_rectangle(msg_box, 14, fill=THEME["panel"], outline=THEME["panel_border"], width=1)

            # 提示信息
            status_text = record.status_message or "暂无可查询的历史阵容"
            self._text(draw, (self.WIDTH // 2 - 200, 240), status_text, 28, THEME["text"], width=400, bold=True)
            self._text(
                draw,
                (self.WIDTH // 2 - 250, 290),
                "（可能由于该关卡采用快速完成通关、尚未通关或官方未保存记录）",
                16,
                THEME["muted"],
                width=500,
            )

        # 底部
        draw.line((padding, height - 60, self.WIDTH - padding, height - 60), fill="#262D38", width=1)
        footer_text = f"指挥官: {record.commander_name or '—'} · {record.fetched_at} · v{record.plugin_version} · BlaBlaLink"
        self._text(draw, (padding, height - 44), footer_text, 15, THEME["muted"])
        self._text_right(draw, (self.WIDTH - padding, height - 44), "MAIN QUEST ARCHIVE", 15, primary_color, bold=True)

        path = self.output_dir / f"campaign-{uuid.uuid4().hex}.png"
        canvas.convert("RGB").save(path, "PNG", optimize=True)
        return str(path)

