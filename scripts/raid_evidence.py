"""仅保留已知结构的突袭证据转换，不读取账号、不发起网络请求。"""
from typing import Any


def semantic_sanitize(value: Any) -> Any:
    """只保留序关系，禁止发布伤害数值或精确比例。"""
    identities: dict[str, str] = {}
    damages: list[int] = []

    def collect(item):
        if isinstance(item, dict):
            damage = item.get("total_damage")
            if isinstance(damage, (str, int)) and str(damage).isdigit():
                damages.append(int(damage))
            for child in item.values():
                collect(child)
        elif isinstance(item, list):
            for child in item:
                collect(child)

    collect(value)
    ordered_damage = sorted(set(damages), reverse=True)

    def convert(item, key=""):
        if isinstance(item, dict):
            result = {str(k): convert(v, str(k)) for k, v in item.items()}
            if item.get("openid"):
                token = identities.setdefault(str(item["openid"]), f"user_{len(identities)+1:02d}")
                result["openid"] = token
                if "nickname" in item:
                    result["nickname"] = token.replace("user_", "member_")
            return result
        if isinstance(item, list):
            totals = {}
            for row in item:
                if isinstance(row, dict) and row.get("openid") and str(row.get("total_damage", "")).isdigit():
                    who = str(row["openid"])
                    totals[who] = totals.get(who, 0) + int(row["total_damage"])
            ordered_totals = sorted(set(totals.values()), reverse=True)
            result = []
            for row in item:
                converted = convert(row, key)
                if isinstance(row, dict) and str(row.get("openid")) in totals:
                    converted["participant_total_order"] = ordered_totals.index(totals[str(row["openid"])]) + 1
                result.append(converted)
            return result
        if key == "total_damage" and str(item).isdigit():
            # 明确的顺序标签不是可送入 Builder 的数值。
            return f"ordinal_{ordered_damage.index(int(item)) + 1}"
        if key in {"slot", "day", "level", "difficulty", "step"} and type(item) is int:
            return item
        if key == "is_final_hit" and type(item) is bool:
            return item
        if key in {"tid", "boss_id", "costume_id"} and item is not None:
            return identities.setdefault(f"{key}:{item}", f"asset_{len(identities)+1:02d}")
        if item is None:
            return None
        if isinstance(item, str):
            return "[已脱敏]" if item else ""
        if type(item) is bool:
            return False
        return 0

    return convert(value)
