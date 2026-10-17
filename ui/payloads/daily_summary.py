"""日常任务汇总图片与文本回退共用的结构化投影。"""

from __future__ import annotations

import math
import unicodedata

from astrbot_plugin_nikke.features.daily.models import DailyTaskStatus
from astrbot_plugin_nikke.features.daily.presentation import (
    DAILY_REWARD_STATUS_LABELS,
    DAILY_STATUS_PRESENTATION,
    daily_status_presentation,
    format_daily_summary_text,
)


class DailySummaryT2IPayloadBuilder:
    """按状态码生成有序分页，不从详情文案推断执行结果。"""

    PAGE_SIZE = 10
    MAX_PAGE_HEIGHT = 2200
    MAX_TEXT_CHARS = 3500
    CANVAS_WIDTH = 1200

    # 这些度量与 daily_summary.html 的 CSS 同步；页面高度仍按每条内容实测预算求和。
    ROOT_VERTICAL_PADDING = 54
    HEADER_HEIGHT_BUDGET = 124
    STATUS_AREA_HEIGHT = 48
    FOOTER_HEIGHT_BUDGET = 44
    LAYOUT_SAFETY_HEIGHT = 30
    ROW_VERTICAL_BOX = 38
    ROW_CONTENT_WIDTH = 1090
    ACCOUNT_COLUMN_WIDTH = 230
    BADGE_COLUMN_WIDTH = 170
    DETAIL_COLUMN_WIDTH = 662
    ACCOUNT_FONT_SIZE = 32
    ACCOUNT_LINE_HEIGHT = 1.2
    BADGE_FONT_SIZE = 28
    BADGE_LINE_HEIGHT = 1.15
    BADGE_VERTICAL_PADDING = 14
    DETAIL_FONT_SIZE = 28
    DETAIL_LINE_HEIGHT = 1.3
    REWARD_FONT_SIZE = 22
    REWARD_LINE_HEIGHT = 1.3
    REWARD_GAP = 4
    REWARD_GRID_ROW_GAP = 14
    REWARD_TOP_OVERLAP = 6
    ROW_MIN_TOTAL_HEIGHT = 124
    WIDTH_SAFETY_FACTOR = 1.1

    @classmethod
    def _project(cls, results):
        projected = []
        counts = {status: 0 for status in DailyTaskStatus}
        for index, result in enumerate(results, start=1):
            status, (label, tone) = daily_status_presentation(result.status)
            counts[status] += 1
            rewards = []
            for item in result.items:
                if not isinstance(item, dict):
                    continue
                raw_status = str(item.get("status") or item.get("state") or "unknown")
                state_label = DAILY_REWARD_STATUS_LABELS.get(raw_status, "状态未验证")
                name = str(item.get("name") or "日常项目")
                detail = str(item.get("detail") or "状态未验证")
                rewards.append(
                    {
                        "name": name,
                        "state_label": state_label,
                        "detail": detail,
                        "text": f"{name}：{state_label}（{detail}）",
                    }
                )
            projected.append(
                {
                    "result_index": index,
                    "account_name": str(result.account_name),
                    "status_code": status.value,
                    "status_label": label,
                    "status_tone": tone,
                    "detail": str(result.detail),
                    "rewards": rewards,
                }
            )
        status_counts = [
            {"code": status.value, "label": DAILY_STATUS_PRESENTATION[status][0], "count": count}
            for status, count in counts.items()
            if count
        ]
        return projected, status_counts

    @classmethod
    def _glyph_units(cls, char: str) -> float:
        if char == "\n" or unicodedata.combining(char):
            return 0.0
        if char == "\t":
            return 2.0
        if char.isspace():
            return 0.5
        if unicodedata.east_asian_width(char) in {"W", "F"}:
            return 1.0
        if unicodedata.category(char) == "Cf":
            return 0.0
        if ord(char) < 128:
            # 宽拉丁字形按保守上界计宽，避免长串 W 等字形低估换行数。
            if char in "MW@%&#mw":
                return 1.2
            if char.isalnum():
                if char in "ilI1|":
                    return 0.65
                return 0.95
            if char in ".,:;!'`()[]{}|":
                return 0.65
            return 0.85
        return 1.0

    @classmethod
    def _line_count(cls, text: str, width: int, font_size: int) -> int:
        capacity = width / font_size
        lines = 1
        current = 0.0
        for char in text:
            if char == "\n":
                lines += 1
                current = 0.0
                continue
            units = cls._glyph_units(char) * cls.WIDTH_SAFETY_FACTOR
            if current and current + units > capacity:
                lines += 1
                current = 0.0
            current += units
        return lines

    @classmethod
    def _split_by_lines(cls, text: str, width: int, font_size: int, max_lines: int):
        if not text:
            return [""]
        max_lines = max(2, max_lines)
        capacity = width / font_size
        parts = []
        current = []
        lines = 1
        line_units = 0.0
        for char in text:
            if char == "\n":
                if lines >= max_lines:
                    parts.append("".join(current))
                    current = [char]
                    lines = 2
                    line_units = 0.0
                else:
                    current.append(char)
                    lines += 1
                    line_units = 0.0
                continue
            units = cls._glyph_units(char) * cls.WIDTH_SAFETY_FACTOR
            if line_units and line_units + units > capacity:
                if lines >= max_lines:
                    parts.append("".join(current))
                    current = []
                    lines = 1
                    line_units = 0.0
                else:
                    lines += 1
                    line_units = 0.0
            current.append(char)
            line_units += units
        if current or not parts:
            parts.append("".join(current))
        return parts

    @classmethod
    def _row_height(cls, account_name: str, detail: str, rewards, *, continuation=False) -> int:
        account_lines = cls._line_count(
            account_name, cls.ACCOUNT_COLUMN_WIDTH, cls.ACCOUNT_FONT_SIZE
        )
        account_height = math.ceil(
            account_lines * cls.ACCOUNT_FONT_SIZE * cls.ACCOUNT_LINE_HEIGHT
        )
        badge_height = math.ceil(
            cls.BADGE_FONT_SIZE * cls.BADGE_LINE_HEIGHT + cls.BADGE_VERTICAL_PADDING
        )
        if continuation:
            badge_height += math.ceil(4 + 16 * 1.2)
        detail_height = math.ceil(
            cls._line_count(detail, cls.DETAIL_COLUMN_WIDTH, cls.DETAIL_FONT_SIZE)
            * cls.DETAIL_FONT_SIZE
            * cls.DETAIL_LINE_HEIGHT
        )
        first_grid_row = max(account_height, badge_height, detail_height)
        reward_height = 0
        for reward in rewards:
            reward_height += math.ceil(
                cls._line_count(
                    reward.get("render_text", reward["text"]),
                    cls.DETAIL_COLUMN_WIDTH,
                    cls.REWARD_FONT_SIZE,
                )
                * cls.REWARD_FONT_SIZE
                * cls.REWARD_LINE_HEIGHT
            )
        if rewards:
            reward_height += cls.REWARD_GAP * (len(rewards) - 1)
            reward_height += cls.REWARD_GRID_ROW_GAP - cls.REWARD_TOP_OVERLAP
        return max(
            cls.ROW_MIN_TOTAL_HEIGHT,
            cls.ROW_VERTICAL_BOX + first_grid_row + reward_height + 4,
        )

    @classmethod
    def _fragment_row(cls, row):
        max_row_height = cls.MAX_PAGE_HEIGHT - cls._static_height()
        account_height = max(
            math.ceil(
                cls._line_count(
                    row["account_name"], cls.ACCOUNT_COLUMN_WIDTH, cls.ACCOUNT_FONT_SIZE
                )
                * cls.ACCOUNT_FONT_SIZE
                * cls.ACCOUNT_LINE_HEIGHT
            ),
            math.ceil(cls.BADGE_FONT_SIZE * cls.BADGE_LINE_HEIGHT + cls.BADGE_VERTICAL_PADDING),
        )
        body_capacity = max_row_height - cls.ROW_VERTICAL_BOX - account_height - 12
        detail_line_limit = max(
            1,
            int(body_capacity // (cls.DETAIL_FONT_SIZE * cls.DETAIL_LINE_HEIGHT)),
        )
        reward_line_limit = max(
            1,
            int(body_capacity // (cls.REWARD_FONT_SIZE * cls.REWARD_LINE_HEIGHT)),
        )

        blocks = []
        for part in cls._split_by_lines(
            row["detail"],
            cls.DETAIL_COLUMN_WIDTH,
            cls.DETAIL_FONT_SIZE,
            detail_line_limit,
        ):
            blocks.append({"kind": "detail", "text": part})
        for reward_index, reward in enumerate(row["rewards"], start=1):
            parts = cls._split_by_lines(
                reward["text"],
                cls.DETAIL_COLUMN_WIDTH,
                cls.REWARD_FONT_SIZE,
                reward_line_limit,
            )
            for part_index, part in enumerate(parts, start=1):
                blocks.append(
                    {
                        "kind": "reward",
                        "text": part,
                        "render_text": f"奖励内容续页：{part}" if part_index > 1 else part,
                        "name": reward["name"],
                        "state_label": reward["state_label"],
                        "detail": reward["detail"],
                        "reward_index": reward_index,
                        "part_index": part_index,
                        "part_count": len(parts),
                        "continued": part_index > 1,
                    }
                )

        fragments = []
        current_detail_parts = []
        current_rewards = []

        def append_current():
            if not current_detail_parts and not current_rewards:
                return
            detail = "".join(current_detail_parts)
            fragment = {
                **row,
                "detail": detail,
                "rewards": [dict(item) for item in current_rewards],
                "_estimated_height": cls._row_height(
                    row["account_name"],
                    detail,
                    current_rewards,
                    continuation=bool(fragments),
                ),
            }
            fragments.append(fragment)
            current_detail_parts.clear()
            current_rewards.clear()

        for block in blocks:
            candidate_detail = "".join(current_detail_parts)
            candidate_rewards = current_rewards
            if block["kind"] == "detail":
                candidate_detail += block["text"]
            else:
                candidate_rewards = [*current_rewards, block]
            candidate_height = cls._row_height(
                row["account_name"],
                candidate_detail,
                candidate_rewards,
                continuation=bool(fragments),
            )
            if candidate_height > max_row_height and (current_detail_parts or current_rewards):
                append_current()
                candidate_detail = block["text"] if block["kind"] == "detail" else ""
                candidate_rewards = [block] if block["kind"] == "reward" else []
                candidate_height = cls._row_height(
                    row["account_name"],
                    candidate_detail,
                    candidate_rewards,
                    continuation=bool(fragments),
                )
            if candidate_height > max_row_height:
                raise ValueError("日常结果片段超过单页预算")
            if block["kind"] == "detail":
                current_detail_parts.append(block["text"])
            else:
                current_rewards.append(block)
        append_current()

        total_fragments = len(fragments)
        for index, fragment in enumerate(fragments, start=1):
            fragment["fragment_index"] = index
            fragment["fragment_count"] = total_fragments
            fragment["continuation_label"] = (
                f"结果续页 · 第 {index} / {total_fragments} 段"
                if total_fragments > 1
                else ""
            )
            fragment.pop("_estimated_height", None)
        return fragments

    @classmethod
    def _static_height(cls):
        return (
            cls.ROOT_VERTICAL_PADDING
            + cls.HEADER_HEIGHT_BUDGET
            + cls.STATUS_AREA_HEIGHT
            + cls.FOOTER_HEIGHT_BUDGET
            + cls.LAYOUT_SAFETY_HEIGHT
        )

    def build(self, results, *, scope="日常任务执行摘要"):
        rows, status_counts = self._project(results)
        total_count = len(rows)
        fragments = [fragment for row in rows for fragment in self._fragment_row(row)]
        pages = []
        current_rows = []
        current_height = self._static_height()

        def flush_page():
            nonlocal current_rows, current_height
            if not current_rows:
                return
            pages.append((current_rows, current_height))
            current_rows = []
            current_height = self._static_height()

        for fragment in fragments:
            row_height = self._row_height(
                fragment["account_name"],
                fragment["detail"],
                fragment["rewards"],
                continuation=bool(fragment["continuation_label"]),
            )
            if current_rows and (
                len(current_rows) >= self.PAGE_SIZE
                or current_height + row_height > self.MAX_PAGE_HEIGHT
            ):
                flush_page()
            current_rows.append(fragment)
            current_height += row_height
        flush_page()

        if not pages:
            pages = [([], self._static_height())]

        built_pages = []
        total_pages = len(pages)
        for page_number, (page_rows, estimated_height) in enumerate(pages, start=1):
            indices = [row["result_index"] for row in page_rows]
            if indices:
                start, end = min(indices), max(indices)
                range_label = f"第 {start}–{end} / 共 {total_count} 条"
            else:
                range_label = "暂无结果 / 共 0 条"
            page_height = min(
                self.MAX_PAGE_HEIGHT,
                max(430, math.ceil(estimated_height)),
            )
            built_pages.append(
                {
                    "canvas": {"width": self.CANVAS_WIDTH, "height": page_height},
                    "scope": str(scope),
                    "range_label": range_label,
                    "page_label": f"第 {page_number} / {total_pages} 页",
                    "total_count": total_count,
                    "shown_count": total_count,
                    "omitted_count": 0,
                    "status_counts": status_counts,
                    "rows": page_rows,
                    "footer": "执行结果摘要；未知结果保持待确认，不代表成功或失败",
                    "layout_estimate": {
                        "static_height": self._static_height(),
                        "rows_height": estimated_height - self._static_height(),
                    },
                }
            )

        return {
            "scope": str(scope),
            "total_count": total_count,
            "shown_count": total_count,
            "omitted_count": 0,
            "status_counts": status_counts,
            "pages": built_pages,
        }

    def format_text(self, results, *, scope="日常任务执行摘要"):
        """将相同结果 DTO 投影成有字符预算的有序文本块。"""
        return format_daily_summary_text(
            results,
            scope=scope,
            page_size=self.PAGE_SIZE,
            max_chars=self.MAX_TEXT_CHARS,
        )
