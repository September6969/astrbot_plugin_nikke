"""案例竖版卡的展示聚合；不改变原始属性及身份合同。"""
from collections import defaultdict
from functools import lru_cache
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json

VERSION = "replica-1600x2400-v2"
SHORT_NAMES = {
    # 简体官方全称
    "攻击力增加": "攻击", "防御力增加": "防御", "最大装弹数增加": "装弹",
    "蓄力速度增加": "蓄速", "优越代码伤害增加": "优越", "暴击率增加": "暴率",
    "暴击伤害增加": "暴伤", "命中率增加": "命中", "蓄力伤害增加": "蓄伤",
    # 繁体全称（兼容 overload_tiers.json 上游数据）
    "攻擊力增加": "攻击", "防禦力增加": "防御", "最大裝彈數增加": "装弹",
    "優越代碼傷害增加": "优越", "暴擊率增加": "暴率", "暴擊傷害增加": "暴伤",
    "蓄力傷害增加": "蓄伤",
    # 简称自身回退
    "攻击": "攻击", "攻擊": "攻击", "防御": "防御", "防禦": "防御",
    "装弹": "装弹", "裝彈": "装弹", "蓄速": "蓄速", "优越": "优越", "優越": "优越",
    "暴率": "暴率", "暴擊": "暴率", "暴伤": "暴伤", "暴傷": "暴伤",
    "命中": "命中", "蓄伤": "蓄伤", "蓄傷害": "蓄伤",
}

CANONICAL_LABELS = {
    "攻擊力增加": "攻击力增加",
    "防禦力增加": "防御力增加",
    "最大裝彈數增加": "最大装弹数增加",
    "蓄力速度增加": "蓄力速度增加",
    "優越代碼傷害增加": "优越代码伤害增加",
    "暴擊率增加": "暴击率增加",
    "暴擊傷害增加": "暴击伤害增加",
    "命中率增加": "命中率增加",
    "蓄力傷害增加": "蓄力伤害增加",
}


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
            raw_label = option.display_name.strip("【】")
            label = CANONICAL_LABELS.get(raw_label, raw_label)
            group = groups.setdefault((key, option.unit), {"key": key, "label": label,
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
        if key == "100600" or "statchargetime" in raw_types:
            base = Decimal(str(data.base_charge_seconds or 0))
            if trusted and base.is_finite() and base > 0 and group["complete"]:
                value = rounded_gain(options, base, Decimal("0.01")) / base
            else:
                note = "纸面合计"
        elif key == "100300" or "statammoload" in raw_types:
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


def art_style(data, portrait, *, summary_count=None, identity_resolver=None):
    from astrbot_plugin_nikke.features.character.face_anchor import framing
    return framing(
        data,
        portrait,
        summary_count=summary_count,
        identity_resolver=identity_resolver,
    )["style"]


def noto_font_700():
    return _load_font_data_uri("NotoSansSC-ReplicaSubset-700.woff2")


def noto_font_800():
    return _load_font_data_uri("NotoSansSC-ReplicaSubset-800.woff2")


def noto_font():
    """向后兼容：默认返回 800 ExtraBold WOFF2 子集。"""
    return noto_font_800() or noto_font_700()


def replica_font():
    return _load_font_data_uri("ReplicaSans.otf")


def barlow_font():
    return _load_font_data_uri("BarlowCondensed-Bold.ttf")


def barlow_semibold_font():
    return _load_font_data_uri("BarlowCondensed-SemiBold.ttf")


def rajdhani_font():
    return _load_font_data_uri("Rajdhani-Bold.ttf")


def rajdhani_semibold_font():
    return _load_font_data_uri("Rajdhani-SemiBold.ttf")


@lru_cache(maxsize=16)
def _load_font_data_uri(filename: str = "ReplicaSans.otf"):
    import base64
    from pathlib import Path
    plugin_root = Path(__file__).resolve().parents[2]
    path = plugin_root / "fonts" / filename
    if not path.is_file():
        path = plugin_root / "assets" / "fonts" / filename
    if not path.is_file():
        return None
    ext = path.suffix.lstrip(".").lower()
    mime_map = {
        "otf": "font/otf",
        "ttf": "font/ttf",
        "woff": "font/woff",
        "woff2": "font/woff2",
    }
    mime = mime_map.get(ext, "font/ttf")
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def _font_uri():
    return replica_font()
