# SPDX-License-Identifier: GPL-3.0-or-later
"""公开 UID 能力边界（26）。

上游没有受支持的公开 UID 资料接口，因此这里只提供**受限说明**：
UID 不能证明账号归属，也不会解锁私有权限或返回他人的角色库。已绑定用户仍走原有的
账号绑定链路读取自己的资料；手工输入仅作为本人下游展示的补充，不参与权限判断。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Protocol

UID_DISCLAIMER = (
    "UID 仅用于核对，无法查询其他人的私人资料，也不代表账号归属。"
)
PUBLIC_UID_REASON = (
    "官方没有提供按 UID 直接查玩家资料的接口。已绑定的指挥官请用 /妮姬 我的 或 /妮姬 查询 练度 查看自己的数据。"
)
_UID = re.compile(r"^[0-9]{6,12}$")


class UidInputError(ValueError):
    """UID 或手工资料输入不合法。"""


@dataclass(frozen=True, slots=True)
class PublicUidResult:
    uid: str
    status: str
    message: str
    own_uid_match: bool = False
    private_access: bool = False
    disclaimer: str = UID_DISCLAIMER


def lookup_public_uid(uid: Any, *, own_uid: str | None = None) -> PublicUidResult:
    """返回公开 UID 查询能力说明；不发起网络请求，不读取账号资料。"""
    text = str(uid or "").strip()
    if not _UID.fullmatch(text):
        raise UidInputError("UID 必须是 6–12 位数字")
    own = str(own_uid or "").strip()
    matches = bool(own) and own == text
    if matches:
        return PublicUidResult(
            uid=text,
            status="OWN_BOUND_UID",
            message=(
                "这个 UID 和你当前绑定的账号一致，请用 /妮姬 我的 查看个人资料（UID 本身不代表账号归属）。"
            ),
            own_uid_match=True,
        )
    return PublicUidResult(uid=text, status="UNSUPPORTED", message=PUBLIC_UID_REASON)


def render_public_uid(result: PublicUidResult) -> str:
    return "\n".join(
        (
            f"【UID 说明】{result.uid}",
            result.message,
            result.disclaimer,
        )
    )


class ManualProfileStorePort(Protocol):
    def get_setting(self, key: str, default: Any = None) -> Any: ...

    def set_setting(self, key: str, value: Any) -> None: ...


@dataclass(frozen=True, slots=True)
class ManualProfile:
    name: str
    level: int | None
    note: str
    updated_at: str
    verified: bool = False


class ManualProfileStore:
    """按用户隔离的本人手工资料；只用于下游展示，不参与任何权限判断。"""

    KEY_PREFIX = "manual_profile_v1:"

    def __init__(self, store: ManualProfileStorePort, clock=None) -> None:
        self._store = store
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def _key(self, actor_id: str) -> str:
        if not str(actor_id or "").strip():
            raise UidInputError("缺少用户标识，无法保存手工资料")
        return f"{self.KEY_PREFIX}{actor_id}"

    def save(self, actor_id: str, *, name: str, level: str | int | None = None, note: str = "") -> ManualProfile:
        name_text = str(name or "").strip()
        if not name_text or len(name_text) > 40:
            raise UidInputError("手工昵称需为 1–40 个字符")
        parsed_level: int | None = None
        if level not in (None, ""):
            text = str(level).strip()
            if not text.isascii() or not text.isdigit() or not 1 <= int(text) <= 999:
                raise UidInputError("手工等级需为 1–999 的整数")
            parsed_level = int(text)
        note_text = str(note or "").strip()
        if len(note_text) > 200:
            raise UidInputError("备注不能超过 200 个字符")
        current = self._clock()
        if current.tzinfo is None:
            raise UidInputError("时钟必须包含明确时区")
        record = {
            "name": name_text,
            "level": parsed_level,
            "note": note_text,
            "updated_at": current.astimezone(timezone.utc).isoformat(),
            "verified": False,
        }
        self._store.set_setting(self._key(actor_id), record)
        return ManualProfile(**record)

    def load(self, actor_id: str) -> ManualProfile | None:
        raw = self._store.get_setting(self._key(actor_id), None)
        if not isinstance(raw, Mapping):
            return None
        try:
            return ManualProfile(
                name=str(raw.get("name") or ""),
                level=raw.get("level") if isinstance(raw.get("level"), int) else None,
                note=str(raw.get("note") or ""),
                updated_at=str(raw.get("updated_at") or ""),
                verified=False,
            )
        except TypeError:
            return None

    def clear(self, actor_id: str) -> None:
        self._store.set_setting(self._key(actor_id), None)


def parse_manual_profile(text: str) -> tuple[str, str | None, str]:
    """解析 ``名称[,等级][,备注]``；缺失字段保持未知，不猜测。"""
    parts = [part.strip() for part in re.split(r"[,，、]", str(text or ""))]
    if not parts or not parts[0]:
        raise UidInputError("用法：/妮姬 我的妮姬 手工 <昵称>[,等级][,备注]")
    name = parts[0]
    level = parts[1] if len(parts) > 1 and parts[1] else None
    note = parts[2] if len(parts) > 2 else ""
    return name, level, note


__all__ = [
    "PUBLIC_UID_REASON",
    "UID_DISCLAIMER",
    "ManualProfile",
    "ManualProfileStore",
    "PublicUidResult",
    "UidInputError",
    "lookup_public_uid",
    "parse_manual_profile",
    "render_public_uid",
]
