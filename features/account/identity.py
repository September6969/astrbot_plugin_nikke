"""完整游戏身份，不为缺失字段猜测平台或使用聊天账号替代。"""

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class AccountIdentity:
    platform: str
    area_id: str
    game_uid: str


def canonical_account_identity(account: Mapping[str, Any]) -> AccountIdentity | None:
    """平台忽略大小写，其余字段去首尾空白；整数转十进制文本。"""
    def component(value: Any) -> str:
        if isinstance(value, bool) or not isinstance(value, (str, int)):
            return ""
        return str(value).strip()

    platform = component(account.get("platform")).casefold()
    area = component(account.get("area_id"))
    uid = component(account.get("game_uid")) or component(account.get("uid"))
    return AccountIdentity(platform, area, uid) if platform and area and uid else None
