"""将正式练度总表 DTO 转成安全、限额的 T2I 展示数据。"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
import math
from time import perf_counter
from typing import Any
import unicodedata

from astrbot_plugin_nikke.features.character.roster_ranking import (
    order_roster_entries,
    roster_number,
)

from ..t2i_assets import T2IAssetResolver


def display_roster_number(value: Any, *, grouped: bool = False) -> str:
    """区分未返回、无效输入和数值零。"""
    if value is None:
        return "未返回"
    number = roster_number(value)
    if number is None:
        return "无法识别"
    return f"{number:,}" if grouped else str(number)


def display_roster_skill(value: Any) -> str:
    """为三项技能保留未知语义，同时控制固定比较列的宽度。"""
    if value is None:
        return "—"
    number = roster_number(value)
    return "?" if number is None else str(number)


# 词条面板的确定性高度模型；必须与 roster.html 的尺寸保持同步。
OPTION_PANEL_MARGIN_TOP = 14
OPTION_PANEL_PADDING = 14
OPTION_TITLE_HEIGHT = 30
OPTION_ROW_LINE_HEIGHT = 32
OPTION_ROW_GAP = 6
OPTION_GRID_MARGIN_TOP = 6
OPTION_SAFETY_PAD = 12
# 20px 字体下约 1088px 内容宽对应的全角等效容量，留出安全余量。
OPTION_LINE_CAPACITY_UNITS = 46.0
# 固定总表高度模型的全局安全余量，避免长名折行估计偏小时溢出。
ROSTER_CANVAS_SAFETY = 16


def _text_units(text: str) -> float:
    """按中日韩显示宽度估算文本占用的全角等效宽度。"""
    return sum(
        0.42 if char.isspace() else
        1.0 if unicodedata.east_asian_width(char) in {"W", "F"} else 0.55
        for char in text
    )


def _roster_name_lines(name: str, show_code: bool) -> int:
    text = f"{name} #{'0000' if show_code else ''}" if show_code else name
    return max(1, math.ceil(_text_units(text) / 9))


def _option_row_lines(text: str) -> int:
    return max(1, math.ceil(_text_units(text) / OPTION_LINE_CAPACITY_UNITS))


def _option_payload(summary: Any) -> dict[str, Any] | None:
    """把领域词条摘要投影为可安全展示的结构；未知状态不得伪装成零。"""
    status = getattr(summary, "status", None)
    if not isinstance(status, str) or not status:
        return None
    rows = []
    for row in (getattr(summary, "rows", ()) or ())[:3]:
        if not isinstance(row, Mapping):
            continue
        label = str(row.get("label", "") or "")
        value = str(row.get("value", "") or "")
        tier = str(row.get("tier", "") or "")
        note = str(row.get("note", "") or "")
        rows.append(
            {
                "label": label,
                "value": value,
                "tier": tier,
                "semantic": row.get("semantic", "neutral"),
                "note": note,
                "lines": _option_row_lines(f"{label} {value} {tier} {note}"),
            }
        )
    raw_total = getattr(summary, "total", 0)
    total = raw_total if isinstance(raw_total, int) and not isinstance(raw_total, bool) else 0
    complete = bool(getattr(summary, "complete", False))
    return {
        "status": status,
        "rows": rows,
        "total": total,
        "complete": complete,
        "label": "词条合计" if complete else "已知词条合计",
        "message": str(getattr(summary, "message", "") or ""),
        "has_rows": bool(rows),
    }


def _option_panel_extra_height(options: Mapping[str, Any]) -> int:
    """按词条面板的行数与折行估算额外行高，保证不裁切、不溢出。"""
    rows = options.get("rows") or []
    if rows:
        body = sum(
            max(1, int(row.get("lines", 1))) * OPTION_ROW_LINE_HEIGHT
            for row in rows
        )
        body += OPTION_ROW_GAP * max(0, len(rows) - 1) + OPTION_GRID_MARGIN_TOP
    else:
        body = OPTION_ROW_LINE_HEIGHT
    return (
        OPTION_PANEL_MARGIN_TOP
        + 2 * OPTION_PANEL_PADDING
        + OPTION_TITLE_HEIGHT
        + body
        + OPTION_SAFETY_PAD
    )


def project_roster_rows(
    characters: Any,
    name_map: Any,
    master_resolver: Any = None,
    option_summaries: Any = None,
) -> tuple[list[dict[str, Any]], int, str]:
    """共享排序、身份和数值投影，供 T2I 与文本回退复用同一顺序来源。"""
    entries = tuple(characters or ())
    names = name_map if isinstance(name_map, Mapping) else {}
    summaries = option_summaries if isinstance(option_summaries, Mapping) else {}
    selected = order_roster_entries(entries)[:20]
    identities = []
    resolve = getattr(master_resolver, "resolve_name_code", None)
    for item in selected:
        raw_code = item.get("name_code")
        code = "" if raw_code is None or isinstance(raw_code, bool) else str(raw_code).strip()
        directory_name = str(names.get(code, "")).strip() if code else ""
        canonical = resolve(code) if code and callable(resolve) else None
        if directory_name == "身份待核验":
            name, canonical = "身份待核验", None
        elif canonical is not None:
            name = directory_name or canonical.name_cn or canonical.name_zh_tw or canonical.name_en
        else:
            name = directory_name or "未知妮姬"
        identities.append((name or "未知妮姬", code, canonical))

    duplicate_names = Counter(
        name for name, _, canonical in identities if canonical is not None
    )
    rows = []
    for rank, (item, (name, code, canonical)) in enumerate(
        zip(selected, identities), start=1
    ):
        show_code = bool(code and (canonical is None or duplicate_names[name] > 1))
        row = {
            "rank": rank,
            "name": name,
            "name_code": code,
            "show_code": show_code,
            "identity_verified": canonical is not None,
            "identity_note": "" if canonical is not None else "身份待核验 · 未使用角色头像",
            "avatar_placeholder": "妮" if canonical is not None else "?",
            "level": display_roster_number(item.get("lv")),
            "combat": display_roster_number(item.get("combat"), grouped=True),
            "skills": "/".join(
                display_roster_skill(item.get(key))
                for key in ("skill1_lv", "skill2_lv", "ulti_skill_lv")
            ),
            "grade": f"突破 {display_roster_number(item.get('grade'))}",
            "core": (
                f"核心 +{display_roster_number(item.get('core'))}"
                if item.get("core") is not None
                and display_roster_number(item.get("core")) != "无法识别"
                else f"核心 {display_roster_number(item.get('core'))}"
            ),
            "top_three": rank <= 3,
            "options": (
                _option_payload(summaries.get(code))
                if code
                else None
            ),
            "_canonical": canonical,
        }
        lines = _roster_name_lines(name, show_code)
        row_height = max(
            100,
            24 + lines * 30 + (20 if canonical is None else 0),
        )
        if row["options"] is not None:
            row_height += _option_panel_extra_height(row["options"])
        row["row_height"] = row_height
        rows.append(row)

    total_count = len(entries)
    shown_count = len(rows)
    if total_count > 20:
        range_label = f"显示 Top {shown_count} / 共 {total_count} 名"
    elif total_count == 0:
        range_label = "共 0 名"
    else:
        range_label = f"共 {total_count} 名 · 全部显示"
    return rows, total_count, range_label


class RosterT2IPayloadBuilder:
    """只从总表 DTO、静态角色主表和本地 SI 头像构建页面。"""

    MAX_AVATAR_DATA_BYTES = 384 * 1024
    AVATAR_SIZE = (72, 72)

    def __init__(self, assets: Any = None, resolver: T2IAssetResolver | None = None):
        self.assets = assets
        self.resolver = resolver or T2IAssetResolver()

    def build(self, data: Any) -> dict[str, Any]:
        started = perf_counter()
        characters = tuple(getattr(data, "characters", ()) or ())
        records, total_count, range_label = project_roster_rows(
            characters,
            getattr(data, "name_map", {}),
            getattr(self.assets, "character_master", None),
            getattr(data, "option_summaries", {}),
        )
        rows: list[dict[str, Any]] = []
        lookup_count = 0
        fallback_count = 0
        embedded_bytes = 0
        for record in records:
            avatar_data_uri = None
            avatar_note = ""
            canonical = record["_canonical"]
            if canonical is not None and self.assets is not None:
                lookup_count += 1
                try:
                    image, is_fallback = self.assets.get_lineup_portrait_by_resource_id(
                        canonical.resource_id
                    )
                    if is_fallback:
                        fallback_count += 1
                        avatar_note = "头像暂不可用"
                    candidate_uri = (
                        self.resolver.encode(image, self.AVATAR_SIZE)
                        if image is not None and not is_fallback
                        else None
                    )
                    if candidate_uri and embedded_bytes + len(candidate_uri) <= self.MAX_AVATAR_DATA_BYTES:
                        avatar_data_uri = candidate_uri
                        embedded_bytes += len(candidate_uri)
                    elif image is None:
                        avatar_note = "头像暂不可用"
                    elif candidate_uri:
                        avatar_note = "头像超过页面资源预算"
                except Exception:
                    fallback_count += 1
                    avatar_note = "头像暂不可用"
            elif canonical is not None:
                avatar_note = "头像暂不可用"
            rows.append(
                {
                    key: value
                    for key, value in record.items()
                    if key != "_canonical"
                }
                | {"avatar_data_uri": avatar_data_uri, "avatar_note": avatar_note}
            )
            if avatar_note and record["_canonical"] is not None:
                rows[-1]["row_height"] = max(rows[-1]["row_height"], 100 + 20)

        height = (
            440
            if not rows
            else 360 + sum(row["row_height"] + 8 for row in rows) + ROSTER_CANVAS_SAFETY
        )
        shown_count = len(rows)
        return {
            "canvas": {"width": 1200, "height": height},
            "commander": str(getattr(data, "commander_name", "") or "指挥官"),
            "total_count": total_count,
            "shown_count": shown_count,
            "range_label": range_label,
            "rows": rows,
            "diagnostics": {
                "avatar_lookup_count": lookup_count,
                "avatar_fallback_count": fallback_count,
                "embedded_avatar_bytes": embedded_bytes,
                "build_ms": round((perf_counter() - started) * 1000, 3),
            },
        }
