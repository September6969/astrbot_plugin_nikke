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
MIT_COMMUNITY_OPTION_WEIGHTS: dict[str, float] = {
    "优越代码伤害增加": 10.0,
    "攻击力增加": 10.0,
    "暴击伤害增加": 10.0,
    "防御力增加": 10.0,
    "最大装弹数增加": 12.0,
    "命中率增加": 12.0,
    "蓄力伤害增加": 12.0,
    "蓄力速度增加": 12.0,
    "暴击率增加": 12.0,
}
BUILTIN_OVERLOAD_PRESETS: dict[str, tuple[tuple[str, ...], str]] = {
    "输出": (("优越代码伤害增加", "攻击力增加", "最大装弹数增加"), "通用输出（优越+攻击+装弹）"),
    "通用输出": (("优越代码伤害增加", "攻击力增加", "最大装弹数增加"), "通用输出（优越+攻击+装弹）"),
    "dps": (("优越代码伤害增加", "攻击力增加", "最大装弹数增加"), "通用输出（优越+攻击+装弹）"),
    "蓄力": (("优越代码伤害增加", "攻击力增加", "蓄力速度增加", "蓄力伤害增加"), "蓄力/狙击输出（优越+攻击+蓄速+蓄伤）"),
    "狙击": (("优越代码伤害增加", "攻击力增加", "蓄力速度增加", "蓄力伤害增加"), "蓄力/狙击输出（优越+攻击+蓄速+蓄伤）"),
    "sr": (("优越代码伤害增加", "攻击力增加", "蓄力速度增加", "蓄力伤害增加"), "蓄力/狙击输出（优越+攻击+蓄速+蓄伤）"),
    "rl": (("优越代码伤害增加", "攻击力增加", "蓄力速度增加", "蓄力伤害增加"), "蓄力/狙击输出（优越+攻击+蓄速+蓄伤）"),
    "机枪": (("优越代码伤害增加", "攻击力增加", "最大装弹数增加"), "机枪/弹匣（优越+攻击+装弹）"),
    "弹匣": (("优越代码伤害增加", "攻击力增加", "最大装弹数增加"), "机枪/弹匣（优越+攻击+装弹）"),
    "mg": (("优越代码伤害增加", "攻击力增加", "最大装弹数增加"), "机枪/弹匣（优越+攻击+装弹）"),
    "辅助": (("攻击力增加", "最大装弹数增加", "优越代码伤害增加"), "通用辅助（攻击+装弹+优越）"),
    "support": (("攻击力增加", "最大装弹数增加", "优越代码伤害增加"), "通用辅助（攻击+装弹+优越）"),
    "暴击": (("优越代码伤害增加", "攻击力增加", "暴击率增加", "暴击伤害增加"), "暴击流派（优越+攻击+暴击+爆伤）"),
    "crit": (("优越代码伤害增加", "攻击力增加", "暴击率增加", "暴击伤害增加"), "暴击流派（优越+攻击+暴击+爆伤）"),
}


def resolve_preset_targets(preset: str) -> tuple[tuple[str, ...], str]:
    """解析内置通用定位预设；显式标注非角色专属推荐。"""
    key = unicodedata.normalize("NFKC", str(preset or "")).casefold().strip()
    if key not in BUILTIN_OVERLOAD_PRESETS:
        raise OverloadAdviceError(
            "未知预设定位："
            + str(preset or "(空)")
            + "（可用：通用输出 / 蓄力 / 机枪 / 辅助 / 暴击）"
        )
    targets, desc = BUILTIN_OVERLOAD_PRESETS[key]
    return targets, f"内置通用定位预设 · {desc}（非角色专属推荐表，请结合角色机制微调）"


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
    seed: int | None
    modules_spent: int = 0


@dataclass(frozen=True, slots=True)
class Advice:
    options: tuple[OptionAdvice, ...]
    targets: tuple[str, ...]
    target_counts: tuple[tuple[str, int], ...] = ()
    matched_counts: tuple[tuple[str, int], ...] = ()
    flex_count: int = 0
    lock_warnings: tuple[str, ...] = ()
    recommendation_source: str = ""
    probability: str | None = None
    probability_note: str = PROBABILITY_NOTE
    simulation: SimulationResult | None = None
    avoid_targets: tuple[str, ...] = ()
    character_note: str = ""

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
    avoid_targets: Sequence[str] = (),
    character_note: str = "",
) -> Advice:
    """给出保留 / 锁定 / 重洗建议；无可靠概率表时不显示概率。"""
    normalized_targets = tuple(dict.fromkeys(normalize_label(item) for item in targets))
    normalized_avoid = tuple(dict.fromkeys(normalize_label(item) for item in avoid_targets if normalize_label(item)))
    slot_groups: dict[str, list[OverloadOption]] = {}
    for option in options:
        slot_groups.setdefault(option.slot, []).append(option)

    advices: list[OptionAdvice] = []
    lock_warnings: list[str] = []
    matched_map: dict[str, int] = {label: 0 for label in normalized_targets}

    for option in options:
        if option.label in normalized_avoid:
            action = "重洗"
            lock = False
            reasons = ("该角色机制建议避免此词条（可能稀释技能触发或负收益）", f"{option.tier} 阶")
            if option.locked:
                lock_warnings.append(f"{option.slot_label} #{option.position} 含建议避免词条「{option.label}」，请解锁后重洗")
        elif option.label in normalized_targets:
            matched_map[option.label] = matched_map.get(option.label, 0) + 1
            action = "保留"
            lock = True
            reasons = ("命中目标词条", f"{option.tier} 阶")
            if option.tier <= 5:
                reasons = reasons + ("阶级偏低（≤5/15 阶），锁定会增加后续洗词条模块消耗，非毕业可暂缓锁定",)
                lock_warnings.append(
                    f"{option.slot_label} #{option.position} {option.label} 仅 {option.tier}/15 阶，建议评估后再锁"
                )
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

    for slot, items in slot_groups.items():
        slot_label = SLOTS[slot]
        explicit_locked = sum(1 for item in items if item.locked)
        has_reroll = any(item.label not in normalized_targets and not item.locked for item in items)
        if explicit_locked >= len(POSITIONS) and any(item.label not in normalized_targets for item in items):
            lock_warnings.append(f"{slot_label} 已锁定全部 3 条词条，需先解锁后才可重洗")
        elif explicit_locked > 0 and has_reroll:
            cost = 1 + explicit_locked
            lock_warnings.append(f"{slot_label} 当前已锁 {explicit_locked} 条，每次重洗将消耗 {cost} 个定制模块")

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
        matched_counts=tuple((label, matched_map[label]) for label in normalized_targets),
        flex_count=flex_count,
        lock_warnings=tuple(dict.fromkeys(lock_warnings)),
        recommendation_source=recommendation_label,
        probability=probability,
        probability_note=note,
        avoid_targets=normalized_avoid,
        character_note=str(character_note or "").strip(),
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
    seed: int | None = None,
    distribution: Mapping[str, float] | None = None,
) -> SimulationResult:
    """配置化洗词条模拟：锁定词条永不改变，未锁同部位词条随重洗一起刷新并累计定制模块消耗。

    生产环境默认使用 ``seed=None``（系统随机），仅离线复现测试传入确定性整数种子。
    """
    if isinstance(attempts, bool) or not isinstance(attempts, int) or not 1 <= attempts <= 10_000:
        raise OverloadAdviceError("模拟次数必须是 1–10000 的整数")
    if seed is not None and (isinstance(seed, bool) or not isinstance(seed, int)):
        raise OverloadAdviceError("随机种子必须是整数")
    normalized_targets = set(normalize_label(item) for item in targets)
    if not normalized_targets:
        raise OverloadAdviceError("模拟需要目标词条")

    rand_note = "随机来源：系统随机（非固定种子）" if seed is None else f"随机来源：固定复现种子 {seed}"
    if distribution is None:
        labels = list(KNOWN_LABELS)
        weights = [MIT_COMMUNITY_OPTION_WEIGHTS.get(lbl, 10.0) for lbl in labels]
        assumption = f"配置化假设：MIT nikke-calculator 公开权重模型（10%/12%，非官方公布概率）；{rand_note}。"
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
        assumption = f"配置化假设：按调用方提供的分布重洗；{rand_note}；非官方概率。"

    def satisfied(values: Sequence[OverloadOption]) -> bool:
        return all(option.label in normalized_targets or option.locked for option in values)

    rng: random.Random = random.Random(seed) if seed is not None else random.SystemRandom()
    current = list(options)
    failures = 0
    modules_spent = 0
    slot_order = tuple(dict.fromkeys(option.slot for option in current))
    for attempt in range(1, attempts + 1):
        if satisfied(current):
            return SimulationResult(
                attempts=attempt - 1,
                success=True,
                final=tuple(current),
                failures=failures,
                assumption=assumption,
                seed=seed,
                modules_spent=modules_spent,
            )
        target_slot = None
        for slot in slot_order:
            slot_items = [o for o in current if o.slot == slot]
            if any((not o.locked) and (o.label not in normalized_targets) for o in slot_items):
                target_slot = slot
                break
        if target_slot is None:
            continue
        locked_in_slot = sum(1 for o in current if o.slot == target_slot and o.locked)
        modules_spent += 1 + locked_in_slot
        slot_hit = True
        for index, option in enumerate(current):
            if option.slot != target_slot or option.locked:
                continue
            drawn = rng.choices(labels, weights=weights, k=1)[0]
            current[index] = replace(option, label=drawn)
            if drawn not in normalized_targets:
                slot_hit = False
        if not slot_hit:
            failures += 1
    return SimulationResult(
        attempts=attempts,
        success=satisfied(current),
        final=tuple(current),
        failures=failures,
        assumption=assumption,
        seed=seed,
        modules_spent=modules_spent,
    )


@dataclass(frozen=True, slots=True)
class CharacterTargets:
    """公开角色专属目标：词条类别、目标行数、避坑词条与来源。"""

    targets: tuple[str, ...]
    counts: tuple[tuple[str, int], ...]
    flex_count: int
    source_url: str
    checked_at: str
    avoid: tuple[str, ...] = ()
    note: str = ""


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
        raw_avoid = value.get("avoid") or ()
        avoid = tuple(
            dict.fromkeys(normalize_label(item) for item in raw_avoid if normalize_label(item) in KNOWN_LABELS)
        ) if isinstance(raw_avoid, list) else ()
        result[str(name)] = CharacterTargets(
            targets=tuple(label for label, _ in counts),
            counts=tuple(counts),
            flex_count=flex,
            source_url=entry_source,
            checked_at=str(value.get("checked_at") or checked_at),
            avoid=avoid,
            note=str(value.get("note") or "").strip(),
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
    if advice.character_note:
        lines.append("机制提示：" + advice.character_note)
    if advice.avoid_targets:
        lines.append("建议避免：" + "、".join(advice.avoid_targets))
    if advice.target_counts:
        counts = "、".join(f"{label} {count}" for label, count in advice.target_counts)
        if advice.flex_count:
            counts += f"、灵活 {advice.flex_count}（未指定类别）"
        lines.append("目标数量：" + counts + "（按公开推荐行数，不表示优先级）")
    if advice.matched_counts:
        target_map = dict(advice.target_counts)
        progress = "、".join(
            f"{label} {held}/{target_map[label]} 条"
            if label in target_map
            else f"{label} {held} 条"
            for label, held in advice.matched_counts
        )
        lines.append("当前四件套命中汇总：" + progress)
    if advice.lock_warnings:
        lines.extend(f"锁定与模块提醒：{warning}" for warning in advice.lock_warnings)
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
        seed_text = f"（种子 {sim.seed}）" if sim.seed is not None else "（系统随机）"
        lines.append(
            f"模拟：{sim.attempts} 次重洗后{state}{seed_text}；未成功次数 {sim.failures} · 消耗定制模块约 {sim.modules_spent} 个"
        )
        lines.append(sim.assumption)
    return "\n".join(lines)


def render_character_recommendation(character_name: str, selected: CharacterTargets) -> str:
    """无现成 T10 词条输入时，输出角色专属超限词条推荐与避坑指南。"""
    lines = [
        f"【超限词条推荐】{character_name}",
        f"数据来源：{selected.source_url}（核验 {selected.checked_at}）",
    ]
    counts = "、".join(f"{label} ×{count}" for label, count in selected.counts)
    if selected.flex_count:
        counts += f"、自选/灵活 ×{selected.flex_count}"
    lines.append("推荐四件套词条目标：" + (counts or "、".join(selected.targets)))
    if selected.avoid:
        lines.append("⚠ 建议避免词条：" + "、".join(selected.avoid))
    if selected.note:
        lines.append("机制说明：" + selected.note)
    lines.append("")
    lines.append(f"提示：绑定账号后发送 /妮姬 洗词条 推荐:{character_name} 账号 即可直接对比实装装备。")
    return "\n".join(lines)


__all__ = [
    "Advice",
    "BUILTIN_OVERLOAD_PRESETS",
    "KNOWN_LABELS",
    "MIT_COMMUNITY_OPTION_WEIGHTS",
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
    "render_character_recommendation",
    "resolve_preset_targets",
    "simulate",
]
