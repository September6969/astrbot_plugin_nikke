"""仅保留已知结构的突袭证据转换，不读取账号、不发起网络请求。"""
from fractions import Fraction
from typing import Any


def semantic_sanitize(value: Any) -> Any:
    """保留同人关系和伤害比例；伪值不能作为真实数值或身份映射证据。"""
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
    maximum = max(damages, default=0)

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
            return [convert(child, key) for child in item]
        if key == "total_damage" and str(item).isdigit():
            # 同一正比例变换保留逐刀及聚合的相等/大小关系，以分数避免浮点误差。
            return str(Fraction(int(item), maximum or 1) * 1_000_000)
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
