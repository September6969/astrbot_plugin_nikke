# SPDX-License-Identifier: GPL-3.0-or-later
"""Profile dashboard image renderer."""

from __future__ import annotations

import math
import uuid
from pathlib import Path

from PIL import Image, ImageDraw

from .profile_models import ProfileDashboardData
from .renderer import CardRenderer
from .card_theme import UI_COLORS


PROFILE_THEME = {
    **UI_COLORS,
    "header": UI_COLORS["background"],
    "panel_alt": UI_COLORS["raised"],
    "primary": UI_COLORS["accent"],
    "secondary": UI_COLORS["text"],
}


class ProfileCardRenderer(CardRenderer):
    WIDTH = 1200

    def _text(self, draw, xy, text, size, color, *, width=None, bold=False):
        text = str(text).replace("\n", " ")
        font = self.font(size, bold)
        while width and draw.textlength(text, font=font) > width and size > 18:
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
        while width and draw.textlength(text, font=font) > width and size > 18:
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

    @staticmethod
    def _storage_percent(value: float | None) -> float | None:
        """把 API 原始比例转换为安全百分数，避免 1322% 或负宽度。"""
        if value is None:
            return None
        try:
            raw = float(value)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(raw) or not 0 <= raw <= 1:
            return None
        # 保留两位小数，避免 0.059 这类二进制浮点尾差进入图片文本或进度条。
        return round(max(0.0, min(100.0, raw * 100)), 2)

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
        if data.area_id or data.commander_level is not None or data.team_combat is not None:
            sections.append(self._basic_info_section(data))
        if data.normal_campaign or data.hard_campaign:
            sections.append(self._campaign_section(data))
        if self._has_today(data):
            sections.append(self._today_section(data))
        if (
            data.outpost_available is not None
            or data.synchro_level is not None
            or data.outpost_battle_level is not None
            or data.infra_core_level
        ):
            sections.append(self._outpost_section(data))
        if (
            data.roster_available is not None
            or any(
                v is not None
                for v in [
                    data.character_count,
                    data.max_level,
                    data.max_combat,
                    data.character_costume_count,
                ]
            )
        ):
            sections.append(self._roster_stats_section(data))

        modern_order = bool(data.memorial_summary is not None or data.currencies is not None or self._has_today(data))
        if modern_order and data.recycle_room_researches is not None:
            sections.append(self._recycle_room_section(data))

        if data.memorial_summary is not None or (modern_order and data.memorial_counts is not None):
            sections.append(self._collection_section(data))
        else:
            collection_items = []
            if data.jukebox_count is not None:
                collection_items.append(("点唱机收集", data.jukebox_count))
            if data.memorial_counts is not None:
                collection_items.extend([
                    (f"收藏分类 {i+1}", self._number(item.count))
                    for i, item in enumerate(data.memorial_counts)
                ])
            if data.jukebox_count is not None or data.memorial_counts is not None:
                collection_title = "COLLECTION / 收藏"
                if data.memorial_partial:
                    collection_title += "（部分）"
                sections.append(self._structured_section(collection_title, collection_items))

        if data.currencies is not None:
            sections.append(self._resources_section(data))

        if not modern_order and data.recycle_room_researches is not None:
            sections.append(self._recycle_room_section(data))

        extra = self._extra_items(data)
        if extra:
            sections.append(self._extra_section(extra))
        return sections

    @staticmethod
    def _has_today(data: ProfileDashboardData) -> bool:
        return bool(
            data.daily_available is not None
            or data.storage_fullness is not None
            or any(
                value is not None
                for value in (
                    data.intercept_remaining,
                    data.rookie_arena_remaining,
                    data.special_arena_remaining,
                    data.counsel_remaining,
                    data.dispatch_completed,
                    data.dispatch_in_progress,
                    data.tower_daily_info,
                    data.sim_room_daily_record,
                    data.sim_room_overclock_subseason,
                    data.sim_room_overclock_season,
                )
            )
        )

    @staticmethod
    def _daily_value(value: int | None) -> str:
        return "—" if value is None else f"剩余 {value:,}"

    @staticmethod
    def _tower_value(data: ProfileDashboardData) -> str:
        if data.tower_daily_info is None:
            return "—"
        return f"{len(data.tower_daily_info)} 项" if data.tower_daily_info else "0 项"

    def _today_section(self, data: ProfileDashboardData):
        items = [
            ("拦截", self._daily_value(data.intercept_remaining)),
            ("新人竞技场", self._daily_value(data.rookie_arena_remaining)),
            ("特殊竞技场", self._daily_value(data.special_arena_remaining)),
            ("咨询", self._daily_value(data.counsel_remaining)),
            ("派遣完成", self._number(data.dispatch_completed)),
            ("派遣进行中", self._number(data.dispatch_in_progress)),
            ("无尽塔", self._tower_value(data)),
            (
                "模拟室",
                data.sim_room_daily_record.display_label
                if data.sim_room_daily_record is not None
                else "—",
            ),
            ("双周最高", data.sim_room_overclock_subseason or "—"),
            ("赛季最高", data.sim_room_overclock_season or "—"),
        ]
        if data.daily_available is False:
            items.insert(0, ("每日内容", "获取失败"))
        if data.daily_partial:
            items.append(("每日状态", "部分数据不可用"))

        visible = [item for item in items if item[1] != "—"]
        if not visible:
            visible = [("每日内容", "未提供")]
        storage_percent = self._storage_percent(data.storage_fullness)
        has_storage = data.storage_fullness is not None

        def draw_section(draw, box, fill):
            self._section_panel(draw, box, "TODAY / 今日状态", fill=fill)
            y = box[1] + 55
            if has_storage:
                if storage_percent is None:
                    percent_text = "—"
                else:
                    percent_text = f"{storage_percent:.2f}".rstrip("0").rstrip(".") + "%"
                self._text(draw, (box[0] + 30, y), "保管箱容量", 18, PROFILE_THEME["muted"])
                self._text_right(draw, (box[2] - 30, y), percent_text, 20, PROFILE_THEME["secondary"], width=160, bold=True)
                bar = (box[0] + 30, y + 30, box[2] - 30, y + 43)
                draw.rounded_rectangle(bar, 6, fill=PROFILE_THEME["border"])
                if storage_percent is not None:
                    fill_width = max(0, (bar[2] - bar[0]) * storage_percent / 100)
                    if fill_width > 0:
                        draw.rounded_rectangle(
                            (bar[0], bar[1], bar[0] + fill_width, bar[3]),
                            6,
                            fill=PROFILE_THEME["primary"],
                        )
                y += 65
            for idx, (label, value) in enumerate(visible):
                col = idx % 2
                row = idx // 2
                x = box[0] + 30 + col * 550
                item_y = y + row * 48
                self._text(draw, (x, item_y), label, 18, PROFILE_THEME["muted"], width=220)
                self._text_right(draw, (x + 510, item_y), value, 22, PROFILE_THEME["secondary"], width=280, bold=True)

        rows = (len(visible) + 1) // 2
        height = 75 + (65 if has_storage else 0) + rows * 48 + 20
        return draw_section, height

    def _collection_section(self, data: ProfileDashboardData):
        title = "COLLECTION / 遗失物品"
        if data.memorial_partial:
            title += "（部分）"
        items = [
            (item.display_name or "未知分类", self._number(item.count))
            for item in (data.memorial_summary or [])
        ]
        items = items[:4] or [("暂无记录", "—")]

        def draw_section(draw, box, fill):
            self._section_panel(draw, box, title, fill=fill)
            for idx, (label, value) in enumerate(items):
                x = box[0] + 30 + (idx % 4) * 275
                y = box[1] + 58
                self._text(draw, (x, y), label, 18, PROFILE_THEME["muted"], width=240)
                self._text(draw, (x, y + 32), value, 26, PROFILE_THEME["secondary"], width=240, bold=True)

        return draw_section, 150

    def _resources_section(self, data: ProfileDashboardData):
        title = "RESOURCES / 我的资源"
        if data.currencies_partial:
            title += "（部分）"
        items = [
            (item.display_name, item.compact_value if item.value is not None else "—")
            for item in (data.currencies or [])
        ][:8]
        if not items:
            items = [("暂无资源", "—")]

        def draw_section(draw, box, fill):
            self._section_panel(draw, box, title, fill=fill)
            for idx, (label, value) in enumerate(items):
                col = idx % 4
                row = idx // 4
                x = box[0] + 30 + col * 275
                y = box[1] + 55 + row * 70
                self._text(draw, (x, y), label, 17, PROFILE_THEME["muted"], width=245)
                self._text(draw, (x, y + 27), value, 25, PROFILE_THEME["text"], width=245, bold=True)

        rows = (len(items) + 3) // 4
        return draw_section, 55 + rows * 70 + 20

    def _structured_section(self, title, items):
        # 展示序号而非未确认的内部标识；限制单卡长度以适配 QQ。
        visible = items[:30] or [("暂无记录", "—")]
        if len(items) > 30:
            visible.append(("其余项目", f"{len(items)-30} 项"))
        def draw_section(draw, box, fill):
            self._section_panel(draw, box, title, fill=fill)
            for i, (label, value) in enumerate(visible):
                x, y = box[0] + 30, box[1] + 55 + i * 38
                self._text(draw, (x, y), label, 20, PROFILE_THEME["muted"], width=450)
                self._text(draw, (x + 480, y), value, 20, PROFILE_THEME["text"], width=520)
        return draw_section, 75 + len(visible) * 38

    def _recycle_room_section(self, data):
        title = "RECYCLE ROOM / 循环室"
        if data.research_partial:
            title += "（部分）"
        items = []
        for i, item in enumerate(data.recycle_room_researches or []):
            label = item.presentation_name or item.display_name or f"研究项目 {i+1}"
            level_str = f"Lv.{self._number(item.level)}"
            try:
                exp_val = int(item.exp) if item.exp is not None else 0
            except (ValueError, TypeError):
                exp_val = 0
            if exp_val > 0:
                val = f"{level_str} · EXP {self._number(item.exp)}"
            else:
                val = level_str
            items.append((label, val))

        visible = items[:18] or [("暂无记录", "—")]
        if len(items) > 18:
            visible.append(("其余项目", f"{len(items)-18} 项"))

        def draw_section(draw, box, fill):
            self._section_panel(draw, box, title, fill=fill)
            for idx, (label, value) in enumerate(visible):
                col = idx % 2
                row = idx // 2
                col_x = box[0] + 30 if col == 0 else box[0] + 580
                y = box[1] + 55 + row * 38
                self._text(draw, (col_x, y), label, 20, PROFILE_THEME["muted"], width=330)
                self._text(draw, (col_x + 340, y), value, 20, PROFILE_THEME["text"], width=180)

        rows = (len(visible) + 1) // 2
        height = 75 + rows * 38
        return draw_section, height

    def _campaign_section(self, data):
        def draw_section(draw, box, fill):
            self._section_panel(draw, box, "CAMPAIGN / 主线进度", fill=fill)
            x, y = box[0] + 30, box[1] + 55
            items = []
            if data.normal_campaign:
                items.append(("普通主线", data.normal_campaign))
            if data.hard_campaign:
                items.append(("困难主线", data.hard_campaign))
            for idx, (label, value) in enumerate(items):
                col_x = x + (idx % 3) * 370
                col_y = y + (idx // 3) * 70
                self._text(draw, (col_x, col_y), label, 18, PROFILE_THEME["muted"])
                self._text(draw, (col_x, col_y + 28), value, 28, PROFILE_THEME["secondary"], width=340, bold=True)

        item_count = sum(1 for value in [data.normal_campaign, data.hard_campaign] if value)
        rows = (item_count + 2) // 3
        return draw_section, 55 + rows * 70 + 20

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
            for idx, (label, value) in enumerate(items):
                col_x = x + (idx % 3) * 370
                col_y = y + (idx // 3) * 70
                self._text(draw, (col_x, col_y), label, 18, PROFILE_THEME["muted"])
                self._text(draw, (col_x, col_y + 28), value, 28, PROFILE_THEME["text"], width=340, bold=True)

        item_count = sum(
            1
            for value in [data.area_id, data.commander_level, data.team_combat]
            if value is not None and value != ""
        )
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
            if data.outpost_available is False:
                items.append(("前哨资料", "获取失败"))
            elif not items:
                items.append(("前哨资料", "未提供"))
            for idx, (label, value) in enumerate(items):
                col_x = x + (idx % 3) * 370
                col_y = y + (idx // 3) * 70
                self._text(draw, (col_x, col_y), label, 18, PROFILE_THEME["muted"])
                self._text(draw, (col_x, col_y + 28), value, 28, PROFILE_THEME["secondary"], width=340, bold=True)

        item_count = sum(
            1
            for value in [
                data.synchro_level,
                data.outpost_battle_level,
                data.infra_core_level,
            ]
            if value is not None and value != ""
        )
        if data.outpost_available is False or item_count == 0:
            item_count += 1
        rows = (item_count + 2) // 3
        height = 55 + rows * 70 + 20
        return draw_section, height

    def _roster_stats_section(self, data):
        def draw_section(draw, box, fill):
            self._section_panel(draw, box, "ROSTER / \u59ae\u59ec\u7edf\u8ba1", fill=fill)
            x, y = box[0] + 30, box[1] + 55
            items = []
            if data.character_count is not None:
                items.append(("\u89d2\u8272\u6570\u91cf", str(data.character_count)))
            if data.max_level is not None:
                items.append(("\u6700\u9ad8\u7b49\u7ea7", f"Lv.{data.max_level}"))
            if data.max_combat is not None:
                items.append(("\u6700\u9ad8\u5355\u4f53\u6218\u529b", f"{data.max_combat:,}"))
            if data.character_costume_count is not None:
                items.append(("\u65f6\u88c5\u6570\u91cf", str(data.character_costume_count)))
            if data.roster_available is False:
                items.append(("花名册状态", "获取失败"))
            elif data.roster_partial:
                items.append(("花名册状态", "部分数据不可用"))
            for idx, (label, value) in enumerate(items):
                col_x = x + (idx % 3) * 370
                col_y = y + (idx // 3) * 70
                self._text(draw, (col_x, col_y), label, 18, PROFILE_THEME["muted"])
                self._text(draw, (col_x, col_y + 28), value, 36, PROFILE_THEME["primary"], width=340, bold=True)

        item_count = sum(
            1
            for v in [
                data.character_count,
                data.max_level,
                data.max_combat,
                data.character_costume_count,
            ]
            if v is not None
        )
        if data.roster_available is False or data.roster_partial:
            item_count += 1
        if item_count == 0:
            item_count = 1
        rows = (item_count + 2) // 3
        height = 55 + rows * 70 + 20
        return draw_section, height

    @staticmethod
    def _extra_items(data) -> list[tuple[str, str]]:
        items: list[tuple[str, str]] = []
        if data.created_at:
            items.append(("注册时间", str(data.created_at)))
        if data.progress_tribe_tower:
            items.append(("无尽塔进度", str(data.progress_tribe_tower)))
        if data.sim_room_overclock_score and data.sim_room_overclock_subseason is None:
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
