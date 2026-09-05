# SPDX-License-Identifier: GPL-3.0-or-later
"""Union Raid 1600px dark tactical dashboard image renderer."""

from __future__ import annotations

import uuid
from pathlib import Path

from PIL import Image, ImageDraw

from .renderer import CardRenderer
from .union_raid_models import BossStatus, UnionRaidOverviewData

RAID_THEME = {
    "background": "#0A1017",
    "header": "#0E1722",
    "panel": "#131E2C",
    "panel_highlight": "#182638",
    "border": "#22354A",
    "border_highlight": "#38BDF8",
    "text": "#F8FAFC",
    "muted": "#94A3B8",
    "dim": "#64748B",
    # Status colors
    "current_accent": "#38BDF8",
    "defeated_accent": "#10B981",
    "next_accent": "#F59E0B",
    "locked_accent": "#475569",
    "unknown_accent": "#64748B",
    "hp_bar_bg": "#1E293B",
}


class UnionRaidRenderer(CardRenderer):
    WIDTH = 1600

    def _text(self, draw: ImageDraw.ImageDraw, xy, text, size, color, *, width=None, bold=False):
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

    def _text_right(self, draw: ImageDraw.ImageDraw, xy, text, size, color, *, width=None, bold=False):
        text = str(text).replace("\n", " ")
        font = self.font(size, bold)
        while width and draw.textlength(text, font=font) > width and size > 12:
            size -= 1
            font = self.font(size, bold)
        if width and draw.textlength(text, font=font) > width:
            while text and draw.textlength(text + "…", font=font) > width:
                text = text[:-1]
            text += "…"
        draw.text(xy, text, font=font, fill=color, anchor="rt")

    def render_raid_overview(self, data: UnionRaidOverviewData) -> str:
        """Render Union Raid Overview card (1600px width with dynamic height)."""
        boss_count = max(1, len(data.bosses))
        boss_panel_height = 125
        boss_gap = 16
        header_height = 160
        progress_height = 145
        footer_height = 60
        padding = 40

        total_height = (
            padding * 2
            + header_height
            + 20
            + progress_height
            + 25
            + (boss_count * (boss_panel_height + boss_gap))
            + footer_height
        )

        image = Image.new("RGBA", (self.WIDTH, total_height), RAID_THEME["background"])
        draw = ImageDraw.Draw(image)

        # 1. Header Box
        header_box = (padding, padding, self.WIDTH - padding, padding + header_height)
        draw.rounded_rectangle(header_box, 16, fill=RAID_THEME["header"], outline=RAID_THEME["border"], width=1)
        # Decorative tactical line
        draw.line((padding + 30, padding + 36, padding + 70, padding + 36), fill=RAID_THEME["current_accent"], width=4)
        self._text(draw, (padding + 85, padding + 24), "UNION RAID / 联盟突袭战况总览", 24, RAID_THEME["current_accent"], bold=True)
        self._text(draw, (padding + 30, padding + 68), data.guild_name, 38, RAID_THEME["text"], bold=True, width=700)
        self._text(draw, (padding + 30, padding + 118), f"难度等级: Difficulty {data.difficulty} · Level {data.level}", 20, RAID_THEME["muted"])

        # Right side of header
        if data.season_end:
            self._text_right(draw, (self.WIDTH - padding - 30, padding + 32), f"赛季截止: {data.season_end}", 18, RAID_THEME["muted"])
        self._text_right(draw, (self.WIDTH - padding - 30, padding + 75), f"DIFFICULTY {data.difficulty}", 32, RAID_THEME["current_accent"], bold=True)
        self._text_right(draw, (self.WIDTH - padding - 30, padding + 118), f"STAGE LEVEL {data.level}", 20, RAID_THEME["muted"])

        # 2. Weighted Overall Progress Box
        prog_y = padding + header_height + 20
        prog_box = (padding, prog_y, self.WIDTH - padding, prog_y + progress_height)
        draw.rounded_rectangle(prog_box, 14, fill=RAID_THEME["panel"], outline=RAID_THEME["border"], width=1)

        draw.line((padding + 25, prog_y + 26, padding + 55, prog_y + 26), fill=RAID_THEME["current_accent"], width=3)
        self._text(draw, (padding + 65, prog_y + 16), "TOTAL STAGE PROGRESS / 本阶段加权推进总进度", 20, RAID_THEME["muted"], bold=True)

        if data.total_progress is not None:
            pct_str = f"{data.total_progress * 100:.1f}%"
            self._text_right(draw, (self.WIDTH - padding - 30, prog_y + 16), f"已击破 {pct_str}", 26, RAID_THEME["current_accent"], bold=True)
            if data.total_current_hp is not None and data.total_max_hp is not None:
                hp_str = f"剩余总血量: {data.total_current_hp:,} / {data.total_max_hp:,}"
                self._text(draw, (padding + 30, prog_y + 55), hp_str, 20, RAID_THEME["text"])
            # Progress bar
            bar_x = padding + 30
            bar_y = prog_y + 90
            bar_w = self.WIDTH - (padding * 2) - 60
            bar_h = 24
            draw.rounded_rectangle((bar_x, bar_y, bar_x + bar_w, bar_y + bar_h), 12, fill=RAID_THEME["hp_bar_bg"])
            fill_w = int(bar_w * max(0.0, min(1.0, data.total_progress)))
            if fill_w > 0:
                draw.rounded_rectangle((bar_x, bar_y, bar_x + fill_w, bar_y + bar_h), 12, fill=RAID_THEME["current_accent"])
        else:
            self._text(draw, (padding + 30, prog_y + 70), "Boss 数据不完整，加权总进度暂不可用", 22, RAID_THEME["dim"])

        # 3. Boss Panels
        boss_start_y = prog_y + progress_height + 25
        for i, boss in enumerate(data.bosses):
            by = boss_start_y + i * (boss_panel_height + boss_gap)
            bbox = (padding, by, self.WIDTH - padding, by + boss_panel_height)

            is_current = (boss.status == BossStatus.CURRENT)
            panel_bg = RAID_THEME["panel_highlight"] if is_current else RAID_THEME["panel"]
            border_color = RAID_THEME["border_highlight"] if is_current else RAID_THEME["border"]
            border_w = 2 if is_current else 1

            draw.rounded_rectangle(bbox, 14, fill=panel_bg, outline=border_color, width=border_w)

            # Boss Index & Status
            status_color = {
                BossStatus.DEFEATED: RAID_THEME["defeated_accent"],
                BossStatus.CURRENT: RAID_THEME["current_accent"],
                BossStatus.NEXT: RAID_THEME["next_accent"],
                BossStatus.LOCKED: RAID_THEME["locked_accent"],
                BossStatus.UNKNOWN: RAID_THEME["unknown_accent"],
            }.get(boss.status, RAID_THEME["unknown_accent"])

            status_cn = {
                BossStatus.DEFEATED: "已击破 · DEFEATED",
                BossStatus.CURRENT: "当前目标 · CURRENT",
                BossStatus.NEXT: "下一阶段 · NEXT",
                BossStatus.LOCKED: "未解锁 · LOCKED",
                BossStatus.UNKNOWN: "状态未知",
            }.get(boss.status, boss.status.value)

            # Badge pill
            badge_x = padding + 25
            badge_y = by + 20
            draw.rounded_rectangle((badge_x, badge_y, badge_x + 160, badge_y + 32), 6, fill=RAID_THEME["hp_bar_bg"], outline=status_color, width=1)
            self._text(draw, (badge_x + 12, badge_y + 6), status_cn, 14, status_color, bold=True)

            # Boss Title
            name_x = badge_x + 180
            name_y = by + 18
            self._text(draw, (name_x, name_y), f"#{i + 1:02d}  {boss.name}", 26, RAID_THEME["text"], bold=True, width=520)

            # Elements
            if boss.elements:
                elem_str = " · ".join(f"[{e}]" for e in boss.elements)
                self._text(draw, (name_x, by + 52), f"弱点属性: {elem_str}", 16, RAID_THEME["muted"])

            # HP Text (right-aligned)
            if boss.current_hp is not None and boss.max_hp is not None and boss.max_hp > 0:
                hp_text = f"剩余 HP: {boss.current_hp:,} / {boss.max_hp:,}"
                hp_pct = (boss.hp_percent if boss.hp_percent is not None else 0.0) * 100
                clr_pct = (boss.cleared_percent if boss.cleared_percent is not None else 0.0) * 100
                pct_text = f"剩余 {hp_pct:.1f}% (击破 {clr_pct:.1f}%)"
            else:
                hp_text = "HP: —"
                pct_text = "—"

            self._text_right(draw, (self.WIDTH - padding - 30, by + 22), hp_text, 20, RAID_THEME["muted"])
            self._text_right(draw, (self.WIDTH - padding - 30, by + 48), pct_text, 18, status_color, bold=True)

            # HP Bar
            bar_x = padding + 25
            bar_y = by + 88
            bar_w = self.WIDTH - (padding * 2) - 50
            bar_h = 16
            draw.rounded_rectangle((bar_x, bar_y, bar_x + bar_w, bar_y + bar_h), 8, fill=RAID_THEME["hp_bar_bg"])
            fill_w = int(bar_w * max(0.0, min(1.0, boss.hp_percent))) if boss.hp_percent is not None else 0
            if fill_w > 0:
                draw.rounded_rectangle((bar_x, bar_y, bar_x + fill_w, bar_y + bar_h), 8, fill=status_color)

        # 4. Footer
        foot_y = total_height - footer_height
        footer_text = f"NIKKE BlaBlaLink · Union Raid MVP · v{data.plugin_version} · 数据获取时间: {data.fetched_at}"
        self._text(draw, (padding, foot_y + 15), footer_text, 16, RAID_THEME["dim"])

        # Save to output file
        filename = f"union_raid_{uuid.uuid4().hex[:12]}.png"
        target_path = Path(self.output_dir) / filename
        target_path.parent.mkdir(parents=True, exist_ok=True)
        image.save(str(target_path), "PNG")
        return str(target_path)