# SPDX-License-Identifier: GPL-3.0-or-later
"""超限洗词条助手（14）。

输入现有超限词条与用户目标（或导入的角色推荐表），给出保留 / 锁定 / 重洗建议；
锁定词条在模拟中永不改变。仓库没有可再分发的官方概率表，因此默认不显示概率，
模拟只使用调用方显式提供的配置化假设，并明确标注为估算而非官方数据。
"""

from __future__ import annotations

import json
import random
import unicodedata
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import urlparse

SLOTS: dict[str, str] = {
    "head": "头部",
    "torso": "躯干",
    "arm": "手臂",
    "leg": "腿部",
}
POSITIONS = (1, 2, 3)
_MAX_TIER = 15
# 已核验 OL 分组（assets/data/overload_tiers.json）的中文标签；同时接受繁中写法。
LABEL_ALIASES: dict[str, str] = {
    "优越代码伤害增加": "优越代码伤害增加",
    "優越代碼傷害增加": "优越代码伤害增加",
    "命中率增加": "命中率增加",
    "最大装弹数增加": "最大装弹数增加",
    "最大裝彈數增加": "最大装弹数增加",
    "攻击力增加": "攻击力增加",
    "攻擊力增加": "攻击力增加",
    "蓄力伤害增加": "蓄力伤害增加",
    "蓄力傷害增加": "蓄力伤害增加",
    "蓄力速度增加": "蓄力速度增加",
    "暴击率增加": "暴击率增加",
    "暴擊率增加": "暴击率增加",
    "暴击伤害增加": "暴击伤害增加",
    "暴擊傷害增加": "暴击伤害增加",
    "防御力增加": "防御力增加",
    "防禦力增加": "防御力增加",
}
KNOWN_LABELS = tuple(dict.fromkeys(LABEL_ALIASES.values()))
PROBABILITY_NOTE = "官方未提供可核验的洗词条概率表，因此不显示概率。"


class OverloadAdviceError(ValueError):
    """词条输入、目标或推荐表不合法。"""


def normalize_label(value: Any) -> str:
    """把繁中/简中标签归一到已核验词条名；未知标签原样返回。"""
    text = unicodedata.normalize("NFKC", str(value or "")).strip().strip("【】[] ")
    return LABEL_ALIASES.get(text, text)


@dataclass(frozen=True, slots=True)
class OverloadOption:
    slot: str
    position: int
    label: str
    tier: int
    locked: bool = False

    @property
    def slot_label(self) -> str:
        return SLOTS[self.slot]


@dataclass(frozen=True, slots=True)
class OptionAdvice:
    option: OverloadOption
    action: str
    lock: bool
    reasons: tuple[str, ...]

    @property
    def key(self) -> tuple[str, int]:
        return self.option.slot, self.option.position


@dataclass(frozen=True, slots=True)
class SimulationResult:
    attempts: int
    success: bool
    final: tuple[OverloadOption, ...]
    failures: int
    assumption: str
    seed: int


@dataclass(frozen=True, slots=True)
class Advice:
    options: tuple[OptionAdvice, ...]
    targets: tuple[str, ...]
    target_counts: tuple[tuple[str, int], ...] = ()
    flex_count: int = 0
    recommendation_source: str = ""
    probability: str | None = None
    probability_note: str = PROBABILITY_NOTE
    simulation: SimulationResult | None = None

    @property
    def keep(self) -> tuple[OptionAdvice, ...]:
        return tuple(item for item in self.options if item.action == "保留")

    @property
    def reroll(self) -> tuple[OptionAdvice, ...]:
        return tuple(item for item in self.options if item.action == "重洗")


def _require_slot(value: Any) -> str:
    text = str(value or "").strip().casefold()
    if text in SLOTS:
        return text
    raise OverloadAdviceError(f"未知装备位：{value!r}（可用：{ '、'.join(SLOTS) }）")


def _require_position(value: Any) -> int:
    if isinstance(value, bool):
        raise OverloadAdviceError("词条位置必须是 1–3")
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise OverloadAdviceError("词条位置必须是 1–3") from exc
    if parsed not in POSITIONS:
        raise OverloadAdviceError("词条位置必须是 1–3")
    return parsed


def _require_tier(value: Any) -> int:
    if isinstance(value, bool):
        raise OverloadAdviceError("词条阶级必须是 1–15 的整数")
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise OverloadAdviceError("词条阶级必须是 1–15 的整数") from exc
    if not 1 <= parsed <= _MAX_TIER:
        raise OverloadAdviceError(f"词条阶级超出 1–15：{parsed}")
    return parsed


def parse_options(raw: Iterable[Mapping[str, Any]]) -> tuple[OverloadOption, ...]:
    """校验并解析词条列表；同一仓位重复出现直接失败，不静默覆盖。"""
    options: list[OverloadOption] = []
    seen: set[tuple[str, int]] = set()
    for index, item in enumerate(raw):
        if not isinstance(item, Mapping):
            raise OverloadAdviceError(f"词条[{index}] 必须是对象")
        slot = _require_slot(item.get("slot"))
        position = _require_position(item.get("position"))
        label = normalize_label(item.get("label"))
        if not label:
            raise OverloadAdviceError(f"词条[{index}] 缺少词条名")
        if (slot, position) in seen:
            raise OverloadAdviceError(f"{SLOTS[slot]} 第 {position} 条词条重复，请只保留一条")
        seen.add((slot, position))
        options.append(
            OverloadOption(
                slot=slot,
                position=position,
                label=label,
                tier=_require_tier(item.get("tier")),
                locked=bool(item.get("locked", False)),
            )
        )
    if not options:
        raise OverloadAdviceError("至少需要一条现有超限词条")
    return tuple(sorted(options, key=lambda item: (list(SLOTS).index(item.slot), item.position)))


def parse_targets(values: Iterable[Any] | str) -> tuple[str, ...]:
    """解析目标词条；未知标签显式报错并列出可用标签。"""
    if isinstance(values, str):
        raw = [part for part in values.replace("，", ",").replace("、", ",").split(",")]
    else:
        raw = list(values)
    targets: list[str] = []
    for value in raw:
        label = normalize_label(value)
        if not label:
            continue
        if label not in KNOWN_LABELS:
            raise OverloadAdviceError(
                f"未知目标词条：{label}（可用：{'、'.join(KNOWN_LABELS)}）"
            )
        if label not in targets:
            targets.append(label)
    if not targets:
        raise OverloadAdviceError("请至少提供一个目标词条")
    return tuple(targets)


def advise(
    options: Sequence[OverloadOption],
    targets: Sequence[str],
    *,
    recommendation_label: str = "",
    probability_table: Mapping[str, Any] | None = None,
    target_counts: Mapping[str, Any] | None = None,
    flex_count: int = 0,
) -> Advice:
    """给出保留 / 锁定 / 重洗建议；无可靠概率表时不显示概率。"""
    normalized_targets = tuple(dict.fromkeys(normalize_label(item) for item in targets))
    advices: list[OptionAdvice] = []
    for option in options:
        if option.label in normalized_targets:
            action = "保留"
            lock = True
            reasons = ("命中目标词条", f"{option.tier} 阶")
        elif option.tier >= _MAX_TIER:
            action = "重洗"
            lock = False
            reasons = ("满级但非目标词条，追求目标仍需重洗",)
        else:
            action = "重洗"
            lock = False
            reasons = (f"{option.tier} 阶未达目标",)
        if option.locked and action == "重洗":
            reasons = reasons + ("当前已锁定；如需重洗请先解锁",)
        advices.append(OptionAdvice(option=option, action=action, lock=lock, reasons=reasons))

    normalized_counts: list[tuple[str, int]] = []
    for raw_label, raw_count in (target_counts or {}).items():
        label = normalize_label(raw_label)
        if label not in normalized_targets:
            continue
        if isinstance(raw_count, bool) or not isinstance(raw_count, int) or not 1 <= raw_count <= 4:
            raise OverloadAdviceError(f"目标数量必须是 1–4 的整数：{label}")
        normalized_counts.append((label, raw_count))
    if isinstance(flex_count, bool) or not isinstance(flex_count, int) or not 0 <= flex_count <= 4:
        raise OverloadAdviceError("灵活目标数量必须是 0–4")
    probability, note = _probability_text(probability_table, normalized_targets)
    return Advice(
        options=tuple(advices),
        targets=normalized_targets,
        target_counts=tuple(normalized_counts),
        flex_count=flex_count,
        recommendation_source=recommendation_label,
        probability=probability,
        probability_note=note,
    )


def _probability_text(
    table: Mapping[str, Any] | None, targets: Sequence[str]
) -> tuple[str | None, str]:
    """只有带来源的概率表才展示；字段形状必须可验证。"""
    if not table:
        return None, PROBABILITY_NOTE
    source = str(table.get("source_url") or "").strip()
    checked_at = str(table.get("checked_at") or "").strip()
    rates = table.get("rates")
    parsed_url = urlparse(source)
    if (
        parsed_url.scheme != "https"
        or not parsed_url.netloc
        or not checked_at
        or not isinstance(rates, Mapping)
    ):
        return None, "概率表缺少 HTTPS 来源、核验日期或 rates 字段，按缺失处理。"
    parts: list[str] = []
    for label in targets:
        value = rates.get(label)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None, f"概率表未覆盖目标词条 {label}，按缺失处理。"
        parts.append(f"{label} {value:g}%")
    return "；".join(parts) + f"（来源：{source}，核验 {checked_at}）", ""


def simulate(
    options: Sequence[OverloadOption],
    targets: Sequence[str],
    *,
    attempts: int = 100,
    seed: int = 0,
    distribution: Mapping[str, float] | None = None,
) -> SimulationResult:
    """可复现的配置化模拟：锁定词条永不改变。

    每次尝试按仓位顺序重洗第一条未命中目标且未锁定的词条；命中后停止。
    distribution 缺省时对已核验标签均匀取值，并明确记录为假设。
    """
    if isinstance(attempts, bool) or not isinstance(attempts, int) or not 1 <= attempts <= 10_000:
        raise OverloadAdviceError("模拟次数必须是 1–10000 的整数")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise OverloadAdviceError("随机种子必须是整数")
    normalized_targets = set(normalize_label(item) for item in targets)
    if not normalized_targets:
        raise OverloadAdviceError("模拟需要目标词条")

    if distribution is None:
        labels = list(KNOWN_LABELS)
        weights = [1.0] * len(labels)
        assumption = "配置化假设：已核验词条等概率；非官方概率。"
    else:
        if not isinstance(distribution, Mapping):
            raise OverloadAdviceError("分布必须是词条到权重的映射")
        labels = []
        weights = []
        for raw_label, raw_weight in distribution.items():
            label = normalize_label(raw_label)
            if label not in KNOWN_LABELS:
                raise OverloadAdviceError(f"分布包含未知词条：{label}")
            if isinstance(raw_weight, bool) or not isinstance(raw_weight, (int, float)) or raw_weight <= 0:
                raise OverloadAdviceError("分布权重必须是正数")
            labels.append(label)
            weights.append(float(raw_weight))
        if not labels:
            raise OverloadAdviceError("分布不能为空")
        assumption = "配置化假设：按调用方提供的分布重洗；非官方概率。"

    def satisfied(values: Sequence[OverloadOption]) -> bool:
        # 锁定词条无法改变，因此判定目标是否达成时必须排除它。
        return all(option.label in normalized_targets or option.locked for option in values)

    rng = random.Random(seed)
    current = list(options)
    failures = 0
    for attempt in range(1, attempts + 1):
        if satisfied(current):
            return SimulationResult(
                attempts=attempt - 1,
                success=True,
                final=tuple(current),
                failures=failures,
                assumption=assumption,
                seed=seed,
            )
        for index, option in enumerate(current):
            if option.locked or option.label in normalized_targets:
                continue
            drawn = rng.choices(labels, weights=weights, k=1)[0]
            current[index] = replace(option, label=drawn)
            failures += 0 if drawn in normalized_targets else 1
            break
    return SimulationResult(
        attempts=attempts,
        success=satisfied(current),
        final=tuple(current),
        failures=failures,
        assumption=assumption,
        seed=seed,
    )


@dataclass(frozen=True, slots=True)
class CharacterTargets:
    """公开角色专属目标：词条类别、目标行数、来源。"""

    targets: tuple[str, ...]
    counts: tuple[tuple[str, int], ...]
    flex_count: int
    source_url: str
    checked_at: str


def load_default_line_counts(path: str | Path) -> dict[str, int]:
    """读取公开默认目标结构的行数；只作默认目标展示，不冒充角色专属。"""
    target = Path(path)
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise OverloadAdviceError("默认目标结构无法读取") from exc
    raw = payload.get("default_line_counts") if isinstance(payload, Mapping) else None
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        raise OverloadAdviceError("default_line_counts 必须是映射")
    labels = {"element_bonus": "优越代码伤害增加", "atk_pct": "攻击力增加", "max_ammo_pct": "最大装弹数增加"}
    result = {}
    for key, value in raw.items():
        if key not in labels or isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 4:
            raise OverloadAdviceError("默认目标行数无效")
        result[labels[key]] = value
    return result


def load_character_targets(path: str | Path) -> dict[str, CharacterTargets]:
    """读取角色专属目标；兼容旧的纯标签数组，不复制攻略正文。"""
    target = Path(path)
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except OSError as exc:
        raise OverloadAdviceError(f"推荐表无法读取：{target.name}") from exc
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise OverloadAdviceError("推荐表不是合法 UTF-8 JSON") from exc
    if not isinstance(payload, Mapping) or payload.get("schema_version") != 1:
        raise OverloadAdviceError("推荐表 schema_version 必须为 1")
    source = str(payload.get("source_url") or "")
    checked_at = str(payload.get("checked_at") or "")
    parsed_source = urlparse(source)
    if parsed_source.scheme != "https" or not parsed_source.netloc or not checked_at:
        raise OverloadAdviceError("推荐表必须包含 HTTPS source_url 与 checked_at")
    rows = payload.get("recommendations")
    if not isinstance(rows, Mapping):
        raise OverloadAdviceError("推荐表 recommendations 必须是映射")
    result: dict[str, CharacterTargets] = {}
    for name, value in rows.items():
        if isinstance(value, list):
            labels = parse_targets(value)
            result[str(name)] = CharacterTargets(
                targets=labels,
                counts=tuple((label, 1) for label in labels),
                flex_count=0,
                source_url=source,
                checked_at=checked_at,
            )
            continue
        if not isinstance(value, Mapping):
            raise OverloadAdviceError(f"角色 {name} 的目标必须是数组或对象")
        raw_targets = value.get("targets")
        if not isinstance(raw_targets, list) or not raw_targets:
            raise OverloadAdviceError(f"角色 {name} 的 targets 必须是非空数组")
        counts: list[tuple[str, int]] = []
        for index, item in enumerate(raw_targets):
            if not isinstance(item, Mapping):
                raise OverloadAdviceError(f"角色 {name} targets[{index}] 必须是对象")
            label = normalize_label(item.get("label"))
            if label not in KNOWN_LABELS:
                raise OverloadAdviceError(f"角色 {name} 含未知词条：{label}")
            count = item.get("count")
            if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 4:
                raise OverloadAdviceError(f"角色 {name} 的 {label} 数量必须是 1–4")
            counts.append((label, count))
        flex = value.get("flex_count", 0)
        if isinstance(flex, bool) or not isinstance(flex, int) or not 0 <= flex <= 4:
            raise OverloadAdviceError(f"角色 {name} 的 flex_count 必须是 0–4")
        if sum(count for _, count in counts) + flex > 12:
            raise OverloadAdviceError(f"角色 {name} 的目标总数不能超过 12 行")
        entry_source = str(value.get("source_url") or source)
        parsed_entry = urlparse(entry_source)
        if parsed_entry.scheme != "https" or not parsed_entry.netloc:
            raise OverloadAdviceError(f"角色 {name} 的 source_url 必须是 HTTPS")
        result[str(name)] = CharacterTargets(
            targets=tuple(label for label, _ in counts),
            counts=tuple(counts),
            flex_count=flex,
            source_url=entry_source,
            checked_at=str(value.get("checked_at") or checked_at),
        )
    return result


def load_recommendations(path: str | Path) -> dict[str, tuple[str, ...]]:
    """导入角色推荐表；必须带来源与核验日期，缺失时由调用方显式提示。"""
    target = Path(path)
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except OSError as exc:
        raise OverloadAdviceError(f"推荐表无法读取：{target.name}") from exc
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise OverloadAdviceError("推荐表不是合法 UTF-8 JSON") from exc
    if not isinstance(payload, Mapping) or payload.get("schema_version") != 1:
        raise OverloadAdviceError("推荐表 schema_version 必须为 1")
    source = str(payload.get("source_url") or "")
    parsed = urlparse(source)
    if parsed.scheme != "https" or not parsed.netloc or not payload.get("checked_at"):
        raise OverloadAdviceError("推荐表必须包含 HTTPS source_url 与 checked_at")
    rows = payload.get("recommendations")
    if not isinstance(rows, Mapping):
        raise OverloadAdviceError("推荐表 recommendations 必须是映射")
    result: dict[str, tuple[str, ...]] = {}
    default_targets = payload.get("default_targets")
    if default_targets is not None:
        if not isinstance(default_targets, list) or not default_targets:
            raise OverloadAdviceError("default_targets 必须是非空数组")
        result["__default__"] = parse_targets(default_targets)
    for name, labels in rows.items():
        if isinstance(labels, Mapping):
            # 结构化角色目标由 load_character_targets 处理，这里保留旧接口兼容。
            continue
        if not isinstance(labels, list) or not labels:
            raise OverloadAdviceError(f"角色 {name} 的推荐词条必须是非空数组")
        result[str(name)] = parse_targets(labels)
    return result


def render_advice(advice: Advice) -> str:
    """渲染建议文本；概率缺失时明确说明。"""
    lines = ["【超限洗词条助手】目标：" + "、".join(advice.targets)]
    if advice.recommendation_source:
        lines.append("推荐来源：" + advice.recommendation_source)
    if advice.target_counts:
        counts = "、".join(f"{label} {count}" for label, count in advice.target_counts)
        if advice.flex_count:
            counts += f"、灵活 {advice.flex_count}（未指定类别）"
        lines.append("目标数量：" + counts + "（按公开推荐行数，不表示优先级）")
    locked = [item for item in advice.options if item.option.locked]
    if locked:
        lines.append("已锁定：" + "、".join(f"{item.option.slot_label}{item.option.position}" for item in locked))
    for item in advice.options:
        option = item.option
        action = item.action
        if option.locked and action == "重洗":
            action = "重洗（已锁定，需先解锁）"
        lines.append(
            f"· {option.slot_label} #{option.position} {option.label}（{option.tier} 阶）"
            f" → {action}" + (" · 建议锁定" if item.lock and not option.locked else "")
        )
        lines.append("  理由：" + "；".join(item.reasons))
    if advice.probability:
        lines.append("概率：" + advice.probability)
    else:
        lines.append("概率：" + advice.probability_note)
    if advice.simulation is not None:
        sim = advice.simulation
        state = "达成" if sim.success else "未达成"
        lines.append(
            f"模拟：{sim.attempts} 次重洗后{state}（种子 {sim.seed}）；未成功次数 {sim.failures}"
        )
        lines.append(sim.assumption)
    return "\n".join(lines)


__all__ = [
    "Advice",
    "KNOWN_LABELS",
    "OptionAdvice",
    "OverloadAdviceError",
    "OverloadOption",
    "PROBABILITY_NOTE",
    "SLOTS",
    "CharacterTargets",
    "SimulationResult",
    "advise",
    "load_character_targets",
    "load_default_line_counts",
    "load_recommendations",
    "normalize_label",
    "parse_options",
    "parse_targets",
    "render_advice",
    "simulate",
]
