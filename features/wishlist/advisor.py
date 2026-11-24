# SPDX-License-Identifier: GPL-3.0-or-later
"""愿望单推荐（16）。

复用仓库已核验的角色元数据（等级、企业、属性、爆裂阶段），按收集 / 均衡 / 养成
三种策略给出候选项与理由。仓库没有可核实的“卡池可入池”字段，因此只按显式排除表
过滤，并在结果中明确标注覆盖限制；160 壁垒按已拥有 3 星 SSR 数量判断。
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
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
# 通过 160 级壁垒需要 5 名 3 星 SSR；这是公开玩法常识规则，不是角色强度数据。
WALL_REQUIRED = 5
POOL_COVERAGE_NOTE = (
    "仓库角色元数据不含可靠的“可入池”字段：仅应用运营者提供的显式排除表，"
    "未覆盖的限时/联动角色可能仍在候选中；请按游戏内当期卡池确认。"
)


class WishlistError(ValueError):
    """策略或角色输入不合法。"""


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
    return str(row.get("rare") or "").upper()


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

    @property
    def group(self) -> str:
        return BURST_LABELS.get(self.burst, "未知")


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

    def groups(self) -> dict[str, tuple[Candidate, ...]]:
        """按招募分组（爆裂阶段）返回候选，保持组内确定性顺序。"""
        grouped: dict[str, list[Candidate]] = {}
        for candidate in self.candidates:
            grouped.setdefault(candidate.group, []).append(candidate)
        return {
            group: tuple(grouped[group])
            for group in sorted(grouped, key=lambda name: (BURST_ORDER.get(name, 9), name))
        }


def parse_owned(items: Iterable[str] | str | None) -> tuple[OwnedCharacter, ...]:
    """解析手工角色池：``名称``、``名称:3``、``名称(3星)``，逗号或顿号分隔。"""
    if items is None:
        return ()
    if isinstance(items, str):
        raw = [part for part in _split_owned(items)]
    else:
        raw = [str(item) for item in items]
    result: dict[str, OwnedCharacter] = {}
    for item in raw:
        text = item.strip()
        if not text:
            continue
        limit_break = 0
        for pattern, cast in ((":", int), ("：", int)):
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
        key = _norm(text)
        if not key:
            continue
        current = result.get(key)
        if current is None or limit_break > current.limit_break:
            result[key] = OwnedCharacter(name_code="", name=text, limit_break=limit_break)
    return tuple(result.values())


def _split_owned(text: str) -> list[str]:
    normalized = unicodedata.normalize("NFKC", text)
    for separator in ("，", "、", "/", "\n", ";"):
        normalized = normalized.replace(separator, ",")
    return [part for part in normalized.split(",") if part.strip()]


def recommend(
    rows: Sequence[Mapping[str, Any]],
    owned: Iterable[OwnedCharacter | Mapping[str, Any]] = (),
    strategy: str = "balanced",
    *,
    exclusions: Iterable[str] = (),
    limit: int = 9,
) -> WishlistResult:
    """按策略给出候选项与理由；排序完全确定（分数、代码、名称）。"""
    selected = normalize_strategy(strategy)
    if not 1 <= limit <= 30:
        raise WishlistError("候选数量上限必须在 1–30")
    if not isinstance(rows, Sequence) or not rows:
        raise WishlistError("缺少角色元数据，无法生成愿望单")

    owned_by_code: dict[str, OwnedCharacter] = {}
    owned_by_name: dict[str, OwnedCharacter] = {}
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
        if character.name_code:
            owned_by_code[character.name_code] = character
        if character.name:
            owned_by_name[_norm(character.name)] = character

    excluded = {_norm(item) for item in exclusions if str(item).strip()}
    owned_codes: set[str] = set()
    unmatched_owned: list[str] = []
    resolved: list[tuple[OwnedCharacter, Mapping[str, Any]]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        code = _code(row)
        character = owned_by_code.get(code) or owned_by_name.get(_norm(_name(row)))
        if character is not None:
            owned_codes.add(code)
            resolved.append((character, row))
    for character in list(owned_by_code.values()) + list(owned_by_name.values()):
        if character.name_code and character.name_code not in {_code(row) for row in rows}:
            unmatched_owned.append(character.name)
        elif not character.name_code and _norm(character.name) not in {_norm(_name(row)) for row in rows}:
            unmatched_owned.append(character.name)

    three_star = sum(1 for character, _ in resolved if character.limit_break >= 3)
    wall_reached = three_star >= WALL_REQUIRED
    wall_progress = f"{three_star}/{WALL_REQUIRED} 名 3 星 SSR"

    owned_bursts = {_burst(row) for character, row in resolved if _burst(row)}
    missing_roles = tuple(
        label for burst, label in (("Step1", "B1"), ("Step2", "B2"), ("Step3", "B3"))
        if burst not in owned_bursts
    )

    candidates: list[Candidate] = []
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
        burst = _burst(row)
        if rarity not in {"SSR", "SR", "R"} or not burst:
            # 缺少稳定稀有度/爆裂阶段时无法判断入池与配队价值，直接排除并计入覆盖限制。
            continue
        character = owned_by_code.get(code) or owned_by_name.get(_norm(name))
        is_owned = character is not None
        limit_break = character.limit_break if character else 0
        score = {"SSR": 30, "SR": 14, "R": 5}[rarity]
        reasons: list[str] = [f"{rarity} · {BURST_LABELS.get(burst, burst)}"]

        if not wall_reached:
            if selected == "collection":
                if not is_owned and burst in {"Step1", "Step2"}:
                    score += 12
                    reasons.append("160 壁垒未破：补 B1/B2 更容易组队")
            elif selected == "balanced":
                if is_owned and limit_break == 2:
                    score += 20
                    reasons.append("160 壁垒未破：2 星补到 3 星优先")
                elif not is_owned and burst in {"Step1", "Step2"}:
                    score += 12
                    reasons.append("160 壁垒未破：补 B1/B2 功能位")
            else:
                if is_owned and limit_break < 3:
                    score += 24
                    reasons.append("160 壁垒未破：优先完成突破")
                elif not is_owned and burst in {"Step1", "Step2"}:
                    score += 8
                    reasons.append("补足 B1/B2 以支撑养成队")
        else:
            reasons.append("已通过 160 壁垒：" + wall_progress)

        if not is_owned:
            score += 25 if selected in {"collection", "balanced"} else 8
            reasons.append("尚未拥有")
        else:
            reasons.append(f"已拥有（{limit_break} 星）" if limit_break else "已拥有")
            if selected == "investment" and limit_break < 3:
                score += 18
                reasons.append("可继续突破提升上限")
            if selected == "collection" and limit_break >= 3:
                score -= 10
                reasons.append("已 3 星，收集优先级降低")

        if burst == "Step1" and "B1" in missing_roles:
            score += 15
            reasons.append("缺少 B1，补位提升编队完整度")
        elif burst == "Step2" and "B2" in missing_roles:
            score += 15
            reasons.append("缺少 B2，补位提升编队完整度")
        elif burst == "Step3" and "B3" in missing_roles:
            score += 10
            reasons.append("缺少 B3 输出位")

        candidates.append(
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
            )
        )

    candidates.sort(key=lambda item: (-item.score, item.name_code, item.name))
    return WishlistResult(
        strategy=selected,
        strategy_label=STRATEGIES[selected],
        candidates=tuple(candidates[:limit]),
        wall_reached=wall_reached,
        wall_progress=wall_progress,
        missing_roles=missing_roles,
        exclusions=tuple(unmatched_owned),
    )


def render_wishlist(result: WishlistResult) -> str:
    """渲染愿望单；包含策略、壁垒进度、覆盖限制与候选理由。"""
    lines = [
        f"【愿望单推荐 · {result.strategy_label}】",
        f"160 壁垒：{'已通过' if result.wall_reached else '未通过'}（{result.wall_progress}）",
    ]
    if result.missing_roles:
        lines.append("缺少定位：" + "、".join(result.missing_roles))
    if result.exclusions:
        lines.append("未能匹配的已拥有角色：" + "、".join(dict.fromkeys(result.exclusions)))
    if not result.candidates:
        lines.append("没有可用候选；请补充角色池或检查排除表。")
    for group, candidates in result.groups().items():
        lines.extend(("", f"【{group}】"))
        for candidate in candidates:
            lines.append(
                f"· {candidate.name}（{candidate.rarity} · {candidate.element} · 评分 {candidate.score}）"
            )
            lines.append("  理由：" + "；".join(candidate.reasons))
    lines.extend(("", "覆盖限制：" + result.coverage_note))
    return "\n".join(lines)


__all__ = [
    "BURST_LABELS",
    "Candidate",
    "OwnedCharacter",
    "POOL_COVERAGE_NOTE",
    "STRATEGIES",
    "WALL_REQUIRED",
    "WishlistError",
    "WishlistResult",
    "normalize_strategy",
    "parse_owned",
    "recommend",
    "render_wishlist",
]
