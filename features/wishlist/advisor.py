# SPDX-License-Identifier: GPL-3.0-or-later
"""愿望单推荐（16）。

按《胜利女神：NIKKE》普通招募愿望单规则实现：
- 仅限已明确核验可进入普通招募愿望单的 SSR 入选（fail-closed：未知准入状态不得默认加入）；
- 自动排除 SR、R、ABNORMAL 联动（collab）、限定（limited）、尚未进普池的新角色（new_not_yet_ordinary）与免费/解放角色（free_welfare）；
- 按三大常规企业（极乐净土 / 米西利斯 / 泰特拉）与朝圣者/超限独立池（Over-Spec 并入 Pilgrim 组）分 4 组、每组最多 5 席；
- 160 级壁垒统计已拥有且达到 3 星突破（LB3）的 SSR 角色；
- 手工角色池支持接入 CharacterDirectoryResolver 解析简繁英别名。
"""

from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

STRATEGIES: dict[str, str] = {
    "collection": "收集",
    "balanced": "均衡",
    "investment": "养成",
}
STRATEGY_ALIASES = {
    "收集": "collection", "collection": "collection",
    "均衡": "balanced", "balanced": "balanced",
    "养成": "investment", "investment": "investment", "投资": "investment",
}
BURST_ORDER = {"Step1": 1, "Step2": 2, "Step3": 3, "AllStep": 0}
BURST_LABELS = {"Step1": "B1", "Step2": "B2", "Step3": "B3", "AllStep": "全阶"}
MANUFACTURER_SLOTS = 5
MANUFACTURER_LABELS: dict[str, str] = {
    "ELYSION": "极乐净土",
    "MISSILIS": "米西利斯",
    "TETRA": "泰特拉",
    "PILGRIM": "朝圣者 / 超限",
    "UNSPECIFIED": "其他企业",
}
MANUFACTURER_ORDER: dict[str, int] = {
    "ELYSION": 0,
    "MISSILIS": 1,
    "TETRA": 2,
    "PILGRIM": 3,
    "UNSPECIFIED": 4,
}
POOL_STATUSES = frozenset(
    {
        "ordinary_recruit",
        "pilgrim_overspec",
        "limited",
        "collab",
        "new_not_yet_ordinary",
        "free_welfare",
        "unknown",
    }
)
ADMITTED_POOL_STATUSES = frozenset({"ordinary_recruit", "pilgrim_overspec"})
STANDARD_GROUPS = frozenset({"ELYSION", "MISSILIS", "TETRA"})
VALID_WISHLIST_GROUPS = frozenset({"ELYSION", "MISSILIS", "TETRA", "PILGRIM", "NONE", ""})
# 通过 160 级壁垒需要 5 名 3 星 SSR；SR/R 与未验证条目不计入 160 壁垒进度。
WALL_REQUIRED = 5
POOL_COVERAGE_NOTE = (
    "仅推荐可进普通招募池的 SSR（含朝圣者/超限），已自动排除限定、联动、免费/解放及 SR/R 角色。"
)


class WishlistError(ValueError):
    """策略、角色输入或准入表不合法。"""


@dataclass(frozen=True, slots=True)
class PoolEligibilityEntry:
    name_code: str
    pool_status: str
    wishlist_group: str = ""
    note: str = ""


def parse_pool_eligibility(payload: Mapping[str, Any]) -> dict[str, PoolEligibilityEntry]:
    """解析并严格校验愿望单卡池准入表（schema_version=1）。"""
    if not isinstance(payload, Mapping) or payload.get("schema_version") != 1:
        raise WishlistError("愿望单准入表 schema_version 必须为 1")
    checked_at = str(payload.get("checked_at") or "").strip()
    if not checked_at:
        raise WishlistError("愿望单准入表缺少 checked_at")
    raw_entries = payload.get("entries")
    if not isinstance(raw_entries, (Mapping, list)) or not raw_entries:
        raise WishlistError("愿望单准入表 entries 必须是非空对象或列表")

    parsed: dict[str, PoolEligibilityEntry] = {}
    items = (
        [(str(k), v) for k, v in raw_entries.items()]
        if isinstance(raw_entries, Mapping)
        else [(str(row.get("name_code") or ""), row) for row in raw_entries if isinstance(row, Mapping)]
    )
    for code, entry in items:
        key = str(code).strip()
        if not key or not isinstance(entry, Mapping):
            raise WishlistError("愿望单准入表条目缺少有效的 name_code")
        status = str(entry.get("pool_status") or "").strip().casefold()
        if status not in POOL_STATUSES:
            raise WishlistError(f"愿望单准入表包含未知 pool_status：{status}（code={key}）")
        group = str(entry.get("wishlist_group") or "").strip().upper()
        if group not in VALID_WISHLIST_GROUPS:
            raise WishlistError(f"愿望单准入表包含无效 wishlist_group：{group}（code={key}）")
        note = str(entry.get("note") or "").strip()
        parsed[key] = PoolEligibilityEntry(
            name_code=key,
            pool_status=status,
            wishlist_group=group,
            note=note,
        )
    if not parsed:
        raise WishlistError("愿望单准入表为空")
    return parsed


def load_pool_eligibility(path: str | Path) -> dict[str, PoolEligibilityEntry]:
    """从 JSON 文件读取并校验愿望单卡池准入表。"""
    target = Path(path)
    if not target.is_file():
        raise WishlistError(f"未找到愿望单准入表：{target.name}")
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise WishlistError(f"愿望单准入表无法解析：{target.name}") from exc
    return parse_pool_eligibility(payload)


def normalize_strategy(value: Any) -> str:
    key = str(value or "").strip().casefold()
    strategy = STRATEGY_ALIASES.get(key)
    if strategy is None:
        raise WishlistError(
            f"未知策略：{value}（可用：收集、均衡、养成）"
        )
    return strategy


def _norm(value: Any) -> str:
    return unicodedata.normalize("NFKC", str(value or "")).casefold().strip()


def _code(row: Mapping[str, Any]) -> str:
    for key in ("name_code", "resource_id", "character_key"):
        value = row.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def _name(row: Mapping[str, Any]) -> str:
    for key in ("name_zh_cn", "name_zh_tw", "name_cn", "name_en"):
        value = str(row.get(key) or "").strip()
        if value:
            return value
    return _code(row) or "未知妮姬"


def _rarity(row: Mapping[str, Any]) -> str:
    return str(row.get("rare") or "").strip().upper()


def _corporation(row: Mapping[str, Any]) -> str:
    raw = str(row.get("corporation") or row.get("corp") or "").strip().upper()
    if raw in {"OVER_SPEC", "OVERSPEC"}:
        return "PILGRIM"
    if raw in {"ELYSION", "MISSILIS", "TETRA", "PILGRIM", "ABNORMAL"}:
        return raw
    return "UNSPECIFIED"


def _limit_break(row: Mapping[str, Any]) -> int:
    raw = row.get("limit_break", row.get("grade", 0))
    if isinstance(raw, bool):
        return 0
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return 0
    return max(0, min(4, value))


def _burst(row: Mapping[str, Any]) -> str:
    burst = str(row.get("burst") or "")
    return burst if burst in BURST_ORDER else ""


def _code_sort_key(code: str) -> tuple[int, int, str]:
    return (0, int(code), "") if code.isdigit() else (1, 0, code)


def _resolve_pool_status(
    code: str,
    row: Mapping[str, Any],
    eligibility: Mapping[str, PoolEligibilityEntry | str | Mapping[str, Any]] | None,
) -> tuple[str, str]:
    """解析卡池准入状态与所属愿望单栏位；缺失或无法识别一律返回 unknown（fail-closed）。"""
    entry = eligibility.get(code) if eligibility is not None else None
    if isinstance(entry, PoolEligibilityEntry):
        return entry.pool_status, entry.wishlist_group
    if isinstance(entry, str):
        status = entry.strip().casefold()
        return (status if status in POOL_STATUSES else "unknown"), ""
    if isinstance(entry, Mapping):
        status = str(entry.get("pool_status") or "").strip().casefold()
        group = str(entry.get("wishlist_group") or "").strip().upper()
        return (status if status in POOL_STATUSES else "unknown"), (
            group if group in VALID_WISHLIST_GROUPS else ""
        )
    if eligibility is not None:
        return "unknown", ""

    inline_status = str(row.get("pool_status") or "").strip().casefold()
    inline_group = str(row.get("wishlist_group") or "").strip().upper()
    return (inline_status if inline_status in POOL_STATUSES else "unknown"), (
        inline_group if inline_group in VALID_WISHLIST_GROUPS else ""
    )


@dataclass(frozen=True, slots=True)
class OwnedCharacter:
    name_code: str
    name: str
    burst: str = ""
    limit_break: int = 0
    level: int | None = None


@dataclass(frozen=True, slots=True)
class Candidate:
    name_code: str
    name: str
    burst: str
    element: str
    rarity: str
    owned: bool
    limit_break: int
    score: int
    reasons: tuple[str, ...]
    corporation: str = "UNSPECIFIED"
    pool_status: str = "unknown"

    @property
    def group(self) -> str:
        return MANUFACTURER_LABELS.get(self.corporation, MANUFACTURER_LABELS["UNSPECIFIED"])


@dataclass(frozen=True, slots=True)
class WishlistResult:
    strategy: str
    strategy_label: str
    candidates: tuple[Candidate, ...]
    wall_reached: bool
    wall_progress: str
    missing_roles: tuple[str, ...]
    exclusions: tuple[str, ...]
    coverage_note: str = POOL_COVERAGE_NOTE
    abnormal_excluded_count: int = 0
    non_ssr_excluded_count: int = 0
    limited_excluded_count: int = 0
    welfare_excluded_count: int = 0
    unknown_excluded_count: int = 0

    def groups(self) -> dict[str, tuple[Candidate, ...]]:
        """按愿望单企业/朝圣分组返回候选，保持组内与组间确定性顺序。"""
        grouped: dict[str, list[Candidate]] = {}
        for candidate in self.candidates:
            grouped.setdefault(candidate.corporation, []).append(candidate)
        return {
            MANUFACTURER_LABELS.get(corp, MANUFACTURER_LABELS["UNSPECIFIED"]): tuple(grouped[corp])
            for corp in sorted(grouped, key=lambda c: (MANUFACTURER_ORDER.get(c, 99), c))
        }


def parse_owned(
    items: Iterable[str] | str | None,
    *,
    rows: Sequence[Mapping[str, Any]] = (),
    resolver: Any = None,
) -> tuple[OwnedCharacter, ...]:
    """解析手工角色池：``名称``、``名称:3``、``名称(3星)``，支持别名解析与重复合并。"""
    if items is None:
        return ()
    if isinstance(items, str):
        raw = [part for part in _split_owned(items)]
    else:
        raw = [str(item) for item in items]

    dict_rows = [dict(r) for r in rows if isinstance(r, Mapping)] if (resolver is not None and rows) else []
    result: dict[str, OwnedCharacter] = {}
    for item in raw:
        text = item.strip()
        if not text:
            continue
        limit_break = 0
        for pattern in (":", "："):
            if pattern in text:
                name, _, tail = text.rpartition(pattern)
                tail = tail.strip().rstrip("星")
                if tail.isdigit():
                    text, limit_break = name.strip(), max(0, min(4, int(tail)))
                break
        if text.endswith(")") and "(" in text:
            name, _, tail = text.rpartition("(")
            tail = tail.rstrip(")").rstrip("星")
            if tail.isdigit():
                text, limit_break = name.strip(), max(0, min(4, int(tail)))

        resolved_code = ""
        resolved_name = text
        if dict_rows and resolver is not None:
            matches = resolver.find(dict_rows, text)
            if len(matches) == 1:
                resolved_code = _code(matches[0])
                resolved_name = _name(matches[0])

        key = resolved_code or _norm(resolved_name)
        if not key:
            continue
        current = result.get(key)
        if current is None or limit_break > current.limit_break:
            result[key] = OwnedCharacter(
                name_code=resolved_code, name=resolved_name, limit_break=limit_break
            )
    return tuple(result.values())


def _split_owned(text: str) -> list[str]:
    normalized = unicodedata.normalize("NFKC", text)
    for separator in ("，", "、", "/", "\n", ";"):
        normalized = normalized.replace(separator, ",")
    return [part for part in normalized.split(",") if part.strip()]


def _index_rows(rows: Sequence[Mapping[str, Any]]) -> tuple[dict[str, Mapping[str, Any]], dict[str, str]]:
    by_code: dict[str, Mapping[str, Any]] = {}
    name_to_code: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        code = _code(row)
        if not code:
            continue
        by_code[code] = row
        for field in ("name_zh_cn", "name_zh_tw", "name_cn", "name_en"):
            normed = _norm(row.get(field))
            if normed and normed not in name_to_code:
                name_to_code[normed] = code
    return by_code, name_to_code


def recommend(
    rows: Sequence[Mapping[str, Any]],
    owned: Iterable[OwnedCharacter | Mapping[str, Any]] = (),
    strategy: str = "balanced",
    *,
    exclusions: Iterable[str] = (),
    limit: int = 20,
    eligibility: Mapping[str, PoolEligibilityEntry | str | Mapping[str, Any]] | None = None,
) -> WishlistResult:
    """按 NIKKE 普通招募愿望单规则（fail-closed 准入、纯 SSR、企业 5 席）给出推荐。"""
    selected = normalize_strategy(strategy)
    if not 1 <= limit <= 30:
        raise WishlistError("候选数量上限必须在 1–30")
    if not isinstance(rows, Sequence) or not rows:
        raise WishlistError("缺少角色元数据，无法生成愿望单")

    by_code, name_to_code = _index_rows(rows)
    owned_by_code: dict[str, OwnedCharacter] = {}
    unmatched_owned: list[str] = []

    for item in owned:
        if isinstance(item, OwnedCharacter):
            character = item
        elif isinstance(item, Mapping):
            character = OwnedCharacter(
                name_code=str(item.get("name_code") or ""),
                name=_name(item),
                burst=_burst(item),
                limit_break=_limit_break(item),
                level=item.get("level") if isinstance(item.get("level"), int) else None,
            )
        else:
            raise WishlistError("已拥有角色必须是 OwnedCharacter 或映射")
        code = character.name_code.strip()
        if not code or code not in by_code:
            code = name_to_code.get(_norm(character.name), "")
        if code and code in by_code:
            merged = OwnedCharacter(
                name_code=code,
                name=character.name or _name(by_code[code]),
                burst=character.burst or _burst(by_code[code]),
                limit_break=character.limit_break,
                level=character.level,
            )
            prev = owned_by_code.get(code)
            if prev is None or merged.limit_break > prev.limit_break:
                owned_by_code[code] = merged
        else:
            unmatched_owned.append(character.name or character.name_code)

    resolved: list[tuple[OwnedCharacter, Mapping[str, Any]]] = [
        (char, by_code[code]) for code, char in owned_by_code.items()
    ]
    # 160 壁垒仅计入 3 星（LB3）SSR；SR/R 最高 2 星绝不计入破壁。
    three_star_ssr = sum(
        1 for char, row in resolved if _rarity(row) == "SSR" and char.limit_break >= 3
    )
    wall_reached = three_star_ssr >= WALL_REQUIRED
    wall_progress = f"{three_star_ssr}/{WALL_REQUIRED} 名 3 星 SSR"

    owned_bursts = {_burst(row) for _, row in resolved if _burst(row)}
    missing_roles = tuple(
        label
        for burst, label in (("Step1", "B1"), ("Step2", "B2"), ("Step3", "B3"))
        if burst not in owned_bursts
    )

    excluded = {_norm(item) for item in exclusions if str(item).strip()}
    abnormal_excluded = 0
    non_ssr_excluded = 0
    limited_excluded = 0
    welfare_excluded = 0
    unknown_excluded = 0
    scored: list[Candidate] = []

    for row in rows:
        if not isinstance(row, Mapping):
            continue
        code = _code(row)
        name = _name(row)
        if not code or not name:
            continue
        if _norm(code) in excluded or _norm(name) in excluded:
            continue
        rarity = _rarity(row)
        if rarity != "SSR":
            non_ssr_excluded += 1
            continue
        raw_corp = _corporation(row)
        pool_status, wishlist_group = _resolve_pool_status(code, row, eligibility)
        if raw_corp == "ABNORMAL" or pool_status == "collab":
            abnormal_excluded += 1
            continue
        if pool_status in {"limited", "new_not_yet_ordinary"}:
            limited_excluded += 1
            continue
        if pool_status == "free_welfare":
            welfare_excluded += 1
            continue
        if pool_status not in ADMITTED_POOL_STATUSES:
            unknown_excluded += 1
            continue

        if pool_status == "pilgrim_overspec" or wishlist_group == "PILGRIM":
            corp = "PILGRIM"
        else:
            corp = wishlist_group if wishlist_group in STANDARD_GROUPS else raw_corp
            if corp not in STANDARD_GROUPS:
                unknown_excluded += 1
                continue

        burst = _burst(row)
        if not burst:
            continue

        character = owned_by_code.get(code)
        is_owned = character is not None
        limit_break = character.limit_break if character else 0
        score = 40
        reasons: list[str] = []

        if corp == "PILGRIM":
            reasons.append("朝圣/超限抽中率低，建议常驻占格")

        if not wall_reached:
            if selected == "collection":
                if not is_owned and burst in {"Step1", "Step2"}:
                    score += 12
                    reasons.append("补 B1/B2 功能位")
            elif selected == "balanced":
                if is_owned and 1 <= limit_break < 3:
                    score += 42 if limit_break == 2 else 30
                    reasons.append(f"破 160 优先：{limit_break} 星补到 3 星")
                elif not is_owned and burst in {"Step1", "Step2"}:
                    score += 10
                    reasons.append("补 B1/B2 功能位")
            else:
                if is_owned and limit_break < 3:
                    score += 44 if limit_break == 2 else (36 if limit_break == 1 else 28)
                    reasons.append("破 160 优先：冲既有 SSR 3 星")
                elif not is_owned and burst in {"Step1", "Step2"}:
                    score += 8
                    reasons.append("补 B1/B2 功能位")

        if not is_owned:
            score += 25 if selected in {"collection", "balanced"} else 6
            reasons.append("尚未拥有")
        else:
            reasons.append(f"已有 {limit_break} 星" if limit_break else "已有 0 星")
            if selected == "investment" and limit_break < 3:
                score += 16
                reasons.append("可继续升星提上限")
            if limit_break >= 3:
                score -= 18
                reasons.append("已满 3 星，后续可换下")

        if burst == "Step1" and "B1" in missing_roles:
            score += 15
            reasons.append("缺 B1 位可补")
        elif burst == "Step2" and "B2" in missing_roles:
            score += 15
            reasons.append("缺 B2 位可补")
        elif burst == "Step3" and "B3" in missing_roles:
            score += 10
            reasons.append("缺 B3 输出可补")

        scored.append(
            Candidate(
                name_code=code,
                name=name,
                burst=burst,
                element=str(row.get("element") or "未知"),
                rarity=rarity,
                owned=is_owned,
                limit_break=limit_break,
                score=score,
                reasons=tuple(reasons),
                corporation=corp,
                pool_status=pool_status,
            )
        )

    # 先按分数、自然数字 code、名称排序，再对每个企业池严格限选至多 5 席。
    scored.sort(key=lambda item: (-item.score, _code_sort_key(item.name_code), item.name))
    per_corp_counts: dict[str, int] = {}
    selected_candidates: list[Candidate] = []
    for candidate in scored:
        count = per_corp_counts.get(candidate.corporation, 0)
        if count >= MANUFACTURER_SLOTS:
            continue
        per_corp_counts[candidate.corporation] = count + 1
        selected_candidates.append(candidate)
        if len(selected_candidates) >= limit:
            break

    return WishlistResult(
        strategy=selected,
        strategy_label=STRATEGIES[selected],
        candidates=tuple(selected_candidates),
        wall_reached=wall_reached,
        wall_progress=wall_progress,
        missing_roles=missing_roles,
        exclusions=tuple(unmatched_owned),
        abnormal_excluded_count=abnormal_excluded,
        non_ssr_excluded_count=non_ssr_excluded,
        limited_excluded_count=limited_excluded,
        welfare_excluded_count=welfare_excluded,
        unknown_excluded_count=unknown_excluded,
    )


def render_wishlist(result: WishlistResult) -> str:
    """渲染清晰易读的普通招募愿望单推荐。"""
    lines = [
        f"【普通招募愿望单 · {result.strategy_label}方案】",
        f"160 突破进度：{'已破壁！' if result.wall_reached else '未突破'}（{result.wall_progress}）",
    ]
    if result.missing_roles:
        lines.append("当前缺位：" + "、".join(result.missing_roles))
    if result.exclusions:
        lines.append("未识别角色：" + "、".join(dict.fromkeys(result.exclusions)))
    if not result.candidates:
        lines.append("暂无可推荐的常驻 SSR 候选，请检查排除条件或角色名单。")
    for group, candidates in result.groups().items():
        lines.extend(("", f"【{group}（{len(candidates)}/{MANUFACTURER_SLOTS}）】"))
        for candidate in candidates:
            reason_text = "；".join(candidate.reasons) if candidate.reasons else ""
            lines.append(
                f"• {candidate.name}（{BURST_LABELS.get(candidate.burst, '?')} · {candidate.element}）"
                + (f" — {reason_text}" if reason_text else "")
            )
    lines.extend(("", "💡 " + result.coverage_note))
    return "\n".join(lines)


__all__ = [
    "ADMITTED_POOL_STATUSES",
    "BURST_LABELS",
    "Candidate",
    "MANUFACTURER_LABELS",
    "MANUFACTURER_ORDER",
    "MANUFACTURER_SLOTS",
    "OwnedCharacter",
    "POOL_COVERAGE_NOTE",
    "POOL_STATUSES",
    "PoolEligibilityEntry",
    "STRATEGIES",
    "WALL_REQUIRED",
    "WishlistError",
    "WishlistResult",
    "load_pool_eligibility",
    "normalize_strategy",
    "parse_owned",
    "parse_pool_eligibility",
    "recommend",
    "render_wishlist",
]
