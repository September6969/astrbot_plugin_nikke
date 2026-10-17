"""将正式练度总表 DTO 转成安全、限额的 T2I 展示数据。"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
import math
from time import perf_counter
from typing import Any
import unicodedata

from ..t2i_assets import T2IAssetResolver


def roster_number(value: Any) -> int | None:
    """只接受可验证的非负整数，保留真实的零值。"""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, str):
        raw = value.strip()
        if raw.isascii() and raw.isdecimal():
            return int(raw)
    return None


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


def _roster_name_lines(name: str, show_code: bool) -> int:
    text = f"{name} #{'0000' if show_code else ''}" if show_code else name
    units = sum(
        0.42 if char.isspace() else
        1.0 if unicodedata.east_asian_width(char) in {"W", "F"} else 0.55
        for char in text
    )
    return max(1, math.ceil(units / 12))


def project_roster_rows(
    characters: Any,
    name_map: Any,
    master_resolver: Any = None,
) -> tuple[list[dict[str, Any]], int, str]:
    """共享排序、身份和数值投影，供 T2I 与 Pillow 展示复用。"""
    entries = tuple(characters or ())
    names = name_map if isinstance(name_map, Mapping) else {}
    indexed = [
        (index, item if isinstance(item, Mapping) else {})
        for index, item in enumerate(entries)
    ]
    indexed.sort(
        key=lambda pair: (
            roster_number(pair[1].get("combat")) or 0,
            roster_number(pair[1].get("lv")) or 0,
        ),
        reverse=True,
    )
    selected = indexed[:20]
    identities = []
    resolve = getattr(master_resolver, "resolve_name_code", None)
    for _, item in selected:
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
    for rank, ((_, item), (name, code, canonical)) in enumerate(
        zip(selected, identities), start=1
    ):
        show_code = bool(code and (canonical is None or duplicate_names[name] > 1))
        rows.append(
            {
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
                "_canonical": canonical,
            }
        )
        lines = _roster_name_lines(name, show_code)
        rows[-1]["row_height"] = max(
            100,
            24 + lines * 30 + (20 if canonical is None else 0),
        )

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

        height = 440 if not rows else 360 + sum(row["row_height"] + 8 for row in rows)
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
