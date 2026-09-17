"""案例竖版卡的展示聚合；不改变原始属性及身份合同。"""
from collections import defaultdict
from functools import lru_cache
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json

VERSION = "replica-1600x2400-v1"
SHORT_NAMES = {"攻击力增加": "攻击", "防御力增加": "防御", "最大装弹数增加": "装弹",
               "蓄力速度增加": "蓄速", "优越代码伤害增加": "优越", "暴击率增加": "暴率",
               "暴击伤害增加": "暴伤", "命中率增加": "命中", "蓄力伤害增加": "蓄伤"}


def tier_of(option):
    return option.tier if type(option.tier) is int and 1 <= option.tier <= 15 else None


def fraction(option):
    # 保留接口的万分比精度；旧 DTO 可使用已有规范化数值。
    if type(option.raw_value) is int and option.unit == "percent":
        return abs(Decimal(option.raw_value)) / 10000
    return Decimal(str(option.value))


def rounded_gain(options, base, quantum):
    """同等级、同原值合并后逐项四舍五入；调用方保证同一效果组。"""
    buckets = defaultdict(Decimal)
    for index, option in enumerate(options):
        value = fraction(option)
        tier = tier_of(option)
        key = (tier if tier is not None else f"unknown-{index}", value)
        buckets[key] += value
    return sum(((base * value).quantize(quantum, rounding=ROUND_HALF_UP)
                for value in buckets.values()), Decimal(0))


def build_summary(data):
    groups = {}
    total, complete = 0, True
    for slot in ("head", "torso", "arm", "leg"):
        equipment = data.equipment.get(slot)
        if equipment is None or not equipment.equipped:
            continue
        for index, option in enumerate(equipment.options[:3]):
            if option.unit == "empty":
                continue
            tier = tier_of(option)
            total += tier or 0
            complete &= tier is not None
            # 原始功能类型是旧 DTO 的稳定回退；不使用翻译后的名称分组。
            key = option.effect_group_id or option.raw_type
            if not key or option.unit not in ("flat", "percent"):
                complete = False
                continue
            group = groups.setdefault((key, option.unit), {"key": key, "label": option.display_name.strip("【】"),
                                      "options": [], "tier_sum": 0, "complete": True})
            group["options"].append(option)
            group["tier_sum"] += tier or 0
            group["complete"] &= tier is not None
    rows = []
    for (key, unit), group in groups.items():
        options = group["options"]
        value = sum((fraction(option) for option in options), Decimal(0))
        label, note, extra = group["label"], "", ""
        # 没有来源证明的基础值不进入有效收益计算。
        trusted = bool(data.weapon_base_source)
        raw_types = {option.raw_type.casefold() for option in options}
        if "statchargetime" in raw_types:
            base = Decimal(str(data.base_charge_seconds or 0))
            if trusted and base.is_finite() and base > 0 and group["complete"]:
                value = rounded_gain(options, base, Decimal("0.01")) / base
            else:
                note = "纸面合计"
        elif "statammoload" in raw_types:
            if trusted and type(data.base_ammo) is int and data.base_ammo > 0 and group["complete"]:
                gain = rounded_gain(options, Decimal(data.base_ammo), Decimal("1"))
                extra = f" (+{gain})"
        formatted = f"{value * 100:.2f}%" if unit == "percent" else f"{value:g}"
        rows.append({"key": key, "label": label, "value": formatted + extra,
                     "tier": f"{group['tier_sum']}阶", "tier_sum": group["tier_sum"],
                     "complete": group["complete"], "note": note or ("已知部分" if not group["complete"] else "")})
    rows.sort(key=lambda row: (-row["tier_sum"], row["key"]))
    return {"rows": rows[:4], "total": total, "complete": complete}


def cache_identity(data):
    from dataclasses import asdict
    payload = {"template": VERSION, "data": asdict(data)}
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def art_style(data, portrait):
    from astrbot_plugin_nikke.features.character.face_anchor import framing
    return framing(data, portrait)["style"]


def replica_font():
    return _font_uri()


@lru_cache(maxsize=1)
def _font_uri():
    import base64
    from pathlib import Path
    cand = Path(__file__).resolve().parents[2] / "assets" / "fonts" / "ReplicaSans.otf"
    if not cand.is_file():
        cand = Path(__file__).resolve().parents[2] / "fonts" / "ReplicaSans.otf"
    if not cand.is_file():
        return None
    return "data:font/otf;base64," + base64.b64encode(cand.read_bytes()).decode("ascii")
