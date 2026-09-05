# SPDX-License-Identifier: GPL-3.0-or-later
"""Profile dashboard image renderer."""

from __future__ import annotations

import uuid
from pathlib import Path

from PIL import Image, ImageDraw

from .profile_models import ProfileDashboardData
from .renderer import CardRenderer


PROFILE_THEME = {
    "header": "#0B1118",
    "background": "#0E141B",
    "panel": "#151D26",
    "panel_alt": "#192430",
    "primary": "#29A7E8",
    "secondary": "#70D6FF",
    "text": "#F3F7FA",
    "muted": "#8FA0AF",
    "border": "#263646",
}


class ProfileCardRenderer(CardRenderer):
    WIDTH = 1200

    def _text(self, draw, xy, text, size, color, *, width=None, bold=False):
        text = str(text).replace("\n", " ")
        font = self.font(size, bold)
        while width and draw.textlength(text, font=font) > width and size > 12:
            size -= 1
            font = self.font(size, bold)
        if width and draw.textlength(text, font=font) > width:
            while text and draw.textlength(text + "\u2026", font=font) > width:
                text = text[:-1]
            text += "\u2026"
        draw.text(xy, text, font=font, fill=color, anchor="lt")

    def _text_right(self, draw, xy, text, size, color, *, width=None, bold=False):
        text = str(text).replace("\n", " ")
        font = self.font(size, bold)
        while width and draw.textlength(text, font=font) > width and size > 12:
            size -= 1
            font = self.font(size, bold)
        if width and draw.textlength(text, font=font) > width:
            while text and draw.textlength(text + "\u2026", font=font) > width:
                text = text[:-1]
            text += "\u2026"
        draw.text(xy, text, font=font, fill=color, anchor="rt")

    def _section_panel(self, draw, box, title, *, fill=None):
        x, y, w, h = box
        fill = fill or PROFILE_THEME["panel"]
        draw.rounded_rectangle(box, 14, fill=fill, outline=PROFILE_THEME["border"], width=1)
        draw.line((x + 22, y + 25, x + 50, y + 25), fill=PROFILE_THEME["primary"], width=3)
        self._text(draw, (x + 60, y + 16), title, 20, PROFILE_THEME["muted"])

    @staticmethod
    def _number(value) -> str:
        return "\u2014" if value is None else f"{value:,}"

    def render_profile(self, data: ProfileDashboardData) -> str:
        theme = PROFILE_THEME
        sections = self._collect_sections(data)
        header_h = 140
        panel_gap = 20
        footer_h = 60
        if sections:
            content_h = sum(h for _, h in sections) + (len(sections) - 1) * panel_gap
        else:
            content_h = 160 + panel_gap
        total_h = header_h + content_h + footer_h + 40

        canvas = Image.new("RGB", (self.WIDTH, total_h), theme["background"])
        draw = ImageDraw.Draw(canvas)

        # Header
        draw.rectangle((0, 0, self.WIDTH, header_h), fill=theme["header"])
        draw.line((0, header_h, self.WIDTH, header_h), fill=theme["primary"], width=2)
        self._text(draw, (40, 24), "NIKKE", 38, theme["text"], bold=True)
        self._text(draw, (40, 75), "COMMANDER PROFILE / \u6307\u6325\u5b98\u6863\u6848", 22, theme["primary"])
        self._text_right(draw, (self.WIDTH - 40, 30), data.commander_name, 36, theme["text"], width=500, bold=True)

        # Sections or empty-state fallback
        y = header_h + 20
        if sections:
            for idx, (draw_fn, h) in enumerate(sections):
                fill = theme["panel"] if idx % 2 == 0 else theme["panel_alt"]
                draw_fn(draw, (40, y, self.WIDTH - 40, y + h), fill)
                y += h + panel_gap
        else:
            empty_h = 160
            box = (40, y, self.WIDTH - 40, y + empty_h)
            draw.rounded_rectangle(box, 14, fill=theme["panel"], outline=theme["border"], width=1)
            font = self.font(26)
            msg = "\u6682\u65e0\u53ef\u7528\u8fdb\u5ea6\u6570\u636e"
            draw.text(
                (self.WIDTH // 2, y + empty_h // 2),
                msg, font=font, fill=theme["muted"], anchor="mm",
            )
            y += empty_h + panel_gap

        # Footer
        footer = f"{data.fetched_at}  \u00b7  v{data.plugin_version}  \u00b7  BlaBlaLink"
        self._text(draw, (40, y + 10), footer, 20, theme["muted"], width=800)

        path = self.output_dir / f"profile-{uuid.uuid4().hex}.png"
        canvas = canvas.convert("RGB") if canvas.mode != "RGB" else canvas
        canvas.save(path, "PNG", optimize=True)
        return str(path)

    def _collect_sections(self, data):
        sections = []
        if data.area_id or data.normal_campaign or data.hard_campaign or data.commander_level is not None or data.team_combat is not None:
            sections.append(self._basic_info_section(data))
        if data.synchro_level is not None or data.outpost_battle_level is not None or data.infra_core_level or data.tactic_academy_class or data.tactic_academy_lesson or data.jukebox_count or data.recycle_room_summary or data.memorial_summary:
            sections.append(self._outpost_section(data))
        if data.character_count > 0:
            sections.append(self._roster_stats_section(data))
        extra = self._extra_items(data)
        if extra:
            sections.append(self._extra_section(extra))
        return sections

    def _basic_info_section(self, data):
        def draw_section(draw, box, fill):
            self._section_panel(draw, box, "BASIC INFO / \u57fa\u672c\u4fe1\u606f", fill=fill)
            x, y = box[0] + 30, box[1] + 55
            items = []
            if data.area_id:
                items.append(("\u533a\u670d ID", data.area_id))
            if data.commander_level is not None:
                items.append(("\u6307\u6325\u5b98\u7b49\u7ea7", str(data.commander_level)))
            if data.team_combat is not None:
                items.append(("\u90e8\u961f\u603b\u6218\u529b", f"{data.team_combat:,}"))
            if data.normal_campaign:
                items.append(("\u666e\u901a\u4e3b\u7ebf", data.normal_campaign))
            if data.hard_campaign:
                items.append(("\u56f0\u96be\u4e3b\u7ebf", data.hard_campaign))
            for idx, (label, value) in enumerate(items):
                col_x = x + (idx % 3) * 370
                col_y = y + (idx // 3) * 70
                self._text(draw, (col_x, col_y), label, 18, PROFILE_THEME["muted"])
                self._text(draw, (col_x, col_y + 28), value, 28, PROFILE_THEME["text"], width=340, bold=True)

        item_count = sum(1 for v in [
            data.area_id, data.commander_level is not None, data.team_combat is not None,
            data.normal_campaign, data.hard_campaign,
        ] if v)
        rows = (item_count + 2) // 3
        height = 55 + rows * 70 + 20
        return draw_section, height

    def _outpost_section(self, data):
        def draw_section(draw, box, fill):
            self._section_panel(draw, box, "OUTPOST / \u524d\u54e8\u57fa\u5730", fill=fill)
            x, y = box[0] + 30, box[1] + 55
            items = []
            if data.synchro_level is not None:
                items.append(("\u540c\u6b65\u5668\u7b49\u7ea7", self._number(data.synchro_level)))
            if data.outpost_battle_level is not None:
                items.append(("\u524d\u54e8\u6218\u6597\u7b49\u7ea7", self._number(data.outpost_battle_level)))
            if data.infra_core_level:
                items.append(("\u57fa\u7840\u6838\u5fc3\u7b49\u7ea7", data.infra_core_level))
            if data.tactic_academy_class:
                items.append(("\u6218\u672f\u5b66\u9662\u73ed\u7ea7", data.tactic_academy_class))
            if data.tactic_academy_lesson:
                items.append(("\u6218\u672f\u5b66\u9662\u8bfe\u7a0b", data.tactic_academy_lesson))
            if data.jukebox_count:
                items.append(("\u70b9\u5531\u673a\u6536\u96c6", data.jukebox_count))
            if data.recycle_room_summary:
                items.append(("\u56de\u6536\u5ba4\u7814\u7a76", data.recycle_room_summary))
            if data.memorial_summary:
                items.append(("\u6536\u85cf\u8bb0\u5f55", data.memorial_summary))
            for idx, (label, value) in enumerate(items):
                col_x = x + (idx % 3) * 370
                col_y = y + (idx // 3) * 70
                self._text(draw, (col_x, col_y), label, 18, PROFILE_THEME["muted"])
                self._text(draw, (col_x, col_y + 28), value, 28, PROFILE_THEME["secondary"], width=340, bold=True)

        item_count = sum(1 for v in [
            data.synchro_level is not None, data.outpost_battle_level is not None,
            data.infra_core_level, data.tactic_academy_class, data.tactic_academy_lesson,
            data.jukebox_count, data.recycle_room_summary, data.memorial_summary,
        ] if v)
        rows = (item_count + 2) // 3
        height = 55 + rows * 70 + 20
        return draw_section, height

    def _roster_stats_section(self, data):
        def draw_section(draw, box, fill):
            self._section_panel(draw, box, "ROSTER / \u59ae\u59ec\u7edf\u8ba1", fill=fill)
            x, y = box[0] + 30, box[1] + 55
            items = [
                ("\u89d2\u8272\u6570\u91cf", str(data.character_count)),
                ("\u6700\u9ad8\u7b49\u7ea7", f"Lv.{data.max_level}"),
                ("\u6700\u9ad8\u5355\u4f53\u6218\u529b", f"{data.max_combat:,}"),
            ]
            if data.character_costume_count is not None:
                items.append(("\u65f6\u88c5\u6570\u91cf", str(data.character_costume_count)))
            for idx, (label, value) in enumerate(items):
                col_x = x + (idx % 3) * 370
                col_y = y + (idx // 3) * 70
                self._text(draw, (col_x, col_y), label, 18, PROFILE_THEME["muted"])
                self._text(draw, (col_x, col_y + 28), value, 36, PROFILE_THEME["primary"], width=340, bold=True)

        item_count = 3 + (1 if data.character_costume_count is not None else 0)
        rows = (item_count + 2) // 3
        height = 55 + rows * 70 + 20
        return draw_section, height

    @staticmethod
    def _extra_items(data) -> list[tuple[str, str]]:
        items: list[tuple[str, str]] = []
        if data.icon_id:
            items.append(("\u5934\u50cf ID", str(data.icon_id)))
        if data.created_at:
            items.append(("\u6ce8\u518c\u65f6\u95f4", str(data.created_at)))
        if data.progress_tribe_tower:
            items.append(("\u90e8\u843d\u5854\u8fdb\u5ea6", str(data.progress_tribe_tower)))
        if data.sim_room_overclock_score:
            items.append(("\u6a21\u62df\u5ba4\u8d85\u9891\u5206\u6570", str(data.sim_room_overclock_score)))
        return items

    def _extra_section(self, items: list[tuple[str, str]]):
        def draw_section(draw, box, fill):
            self._section_panel(draw, box, "MORE / \u66f4\u591a\u6570\u636e", fill=fill)
            x, y = box[0] + 30, box[1] + 55
            for idx, (label, value) in enumerate(items):
                col_x = x + (idx % 3) * 370
                col_y = y + (idx // 3) * 70
                self._text(draw, (col_x, col_y), label, 18, PROFILE_THEME["muted"])
                self._text(draw, (col_x, col_y + 28), value, 28, PROFILE_THEME["text"], width=340, bold=True)

        rows = (len(items) + 2) // 3
        height = 55 + rows * 70 + 20
        return draw_section, height
