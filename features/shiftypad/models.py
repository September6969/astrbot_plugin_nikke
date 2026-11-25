# SPDX-License-Identifier: GPL-3.0-or-later
"""ShiftyPad 只读导入的领域模型。

数字游戏 UID 与 ShiftyPad 使用的长账号标识（OpenID/编码 UID）不是同一种 ID。
本模块不猜测两者之间的转换；无法从受支持来源解析时返回明确的 unresolved/fallback。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping

SERVER_ALIASES = {
    "global": "global", "国际": "global", "国际服": "global", "亚服": "global",
    "asia": "global", "asia服务器": "global",
    "jp": "jp", "日服": "jp", "japan": "jp",
    "kr": "kr", "韩服": "kr", "korea": "kr",
    "na": "na", "美服": "na", "北美": "na", "北美服": "na", "north america": "na",
    "sea": "sea", "东南亚": "sea", "东南亚服": "sea", "southeast asia": "sea",
    "cn": "cn", "国服": "cn", "china": "cn",
}
SERVER_LABELS = {
    "global": "国际服", "jp": "日服", "kr": "韩服", "na": "北美服",
    "sea": "东南亚服", "cn": "国服",
}


class ShiftypadInputError(ValueError):
    """用户输入的 UID、区服或公开链接不合法。"""


class ShiftypadPrivateError(RuntimeError):
    """上游明确表示该档案未公开或公开开关已关闭。"""

    code = "SHIFTYPAD_PRIVATE"


class ShiftypadUpstreamError(RuntimeError):
    """上游不可用或返回合同不完整。"""

    code = "SHIFTYPAD_UPSTREAM"


@dataclass(frozen=True, slots=True)
class ShiftypadIdentity:
    """一次只读导入使用的公开身份。"""

    openid: str
    uid: str = ""
    server: str = ""
    area_id: str = ""
    source: str = "public_reference"
    source_url: str = ""

    def public_dict(self) -> dict[str, Any]:
        return {
            "uid": self.uid,
            "server": SERVER_LABELS.get(self.server, self.server),
            "area_id": self.area_id,
            "source": self.source,
            "source_url": self.source_url,
        }


@dataclass(frozen=True, slots=True)
class ShiftypadCharacter:
    name_code: str
    level: int | None = None
    grade: int | None = None
    combat: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name_code": self.name_code,
            "level": self.level,
            "grade": self.grade,
            "combat": self.combat,
        }


@dataclass(frozen=True, slots=True)
class ShiftypadProfile:
    """公开档案的最小只读快照；不含 Cookie、Token 或私有字段。"""

    identity: ShiftypadIdentity
    nickname: str
    level: int | None = None
    team_combat: int | None = None
    nikke_count: int | None = None
    synchro_level: int | None = None
    normal_stage: str = ""
    hard_stage: str = ""
    visibility: str = "unknown"
    characters: tuple[ShiftypadCharacter, ...] = ()
    fetched_at: str = ""
    source_url: str = ""
    contract: str = "official_public_profile"

    @property
    def content_hash(self) -> str:
        payload = {
            "identity": self.identity.public_dict(),
            "nickname": self.nickname,
            "level": self.level,
            "team_combat": self.team_combat,
            "nikke_count": self.nikke_count,
            "synchro_level": self.synchro_level,
            "normal_stage": self.normal_stage,
            "hard_stage": self.hard_stage,
            "visibility": self.visibility,
            "characters": [item.to_dict() for item in self.characters],
        }
        encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def to_dict(self, *, include_identity: bool = True) -> dict[str, Any]:
        data: dict[str, Any] = {
            "nickname": self.nickname,
            "level": self.level,
            "team_combat": self.team_combat,
            "nikke_count": self.nikke_count,
            "synchro_level": self.synchro_level,
            "normal_stage": self.normal_stage,
            "hard_stage": self.hard_stage,
            "visibility": self.visibility,
            "characters": [item.to_dict() for item in self.characters],
            "fetched_at": self.fetched_at,
            "source_url": self.source_url,
            "contract": self.contract,
        }
        if include_identity:
            data["identity"] = self.identity.public_dict()
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ShiftypadProfile":
        if not isinstance(data, Mapping):
            raise ValueError("快照必须是对象")
        identity_data = data.get("identity") if isinstance(data.get("identity"), Mapping) else {}
        characters_raw = data.get("characters")
        characters = tuple(
            ShiftypadCharacter(
                name_code=str(item.get("name_code") or ""),
                level=item.get("level") if isinstance(item.get("level"), int) else None,
                grade=item.get("grade") if isinstance(item.get("grade"), int) else None,
                combat=item.get("combat") if isinstance(item.get("combat"), int) else None,
            )
            for item in characters_raw or ()
            if isinstance(item, Mapping) and str(item.get("name_code") or "").strip()
        )
        return cls(
            identity=ShiftypadIdentity(
                openid=str(identity_data.get("openid") or ""),
                uid=str(identity_data.get("uid") or ""),
                server=str(identity_data.get("server") or ""),
                area_id=str(identity_data.get("area_id") or ""),
                source=str(identity_data.get("source") or "public_reference"),
                source_url=str(identity_data.get("source_url") or ""),
            ),
            nickname=str(data.get("nickname") or "未知"),
            level=data.get("level") if isinstance(data.get("level"), int) else None,
            team_combat=data.get("team_combat") if isinstance(data.get("team_combat"), int) else None,
            nikke_count=data.get("nikke_count") if isinstance(data.get("nikke_count"), int) else None,
            synchro_level=data.get("synchro_level") if isinstance(data.get("synchro_level"), int) else None,
            normal_stage=str(data.get("normal_stage") or ""),
            hard_stage=str(data.get("hard_stage") or ""),
            visibility=str(data.get("visibility") or "unknown"),
            characters=characters,
            fetched_at=str(data.get("fetched_at") or ""),
            source_url=str(data.get("source_url") or ""),
            contract=str(data.get("contract") or "official_public_profile"),
        )


@dataclass(frozen=True, slots=True)
class Resolution:
    status: str
    identity: ShiftypadIdentity | None = None
    reason: str = ""
    fallback_url: str = "https://www.blablalink.com/shiftyspad/home"
    uid_standalone: bool = False


@dataclass(frozen=True, slots=True)
class ReadonlyBinding:
    actor_id: str
    profile: ShiftypadProfile
    bound_at: str
    last_sync_at: str
    last_error: str = ""
    stale: bool = False
    sync_count: int = 1

    def public_dict(self) -> dict[str, Any]:
        data = self.profile.to_dict()
        data.update(
            {
                "bound_at": self.bound_at,
                "last_sync_at": self.last_sync_at,
                "last_error": self.last_error,
                "stale": self.stale,
                "sync_count": self.sync_count,
            }
        )
        return data

    def to_dict(self) -> dict[str, Any]:
        data = self.public_dict()
        data["identity"] = {
            "openid": self.profile.identity.openid,
            "uid": self.profile.identity.uid,
            "server": self.profile.identity.server,
            "area_id": self.profile.identity.area_id,
            "source": self.profile.identity.source,
            "source_url": self.profile.identity.source_url,
        }
        return data

    @classmethod
    def from_dict(cls, actor_id: str, data: Mapping[str, Any]) -> "ReadonlyBinding":
        identity = data.get("identity") if isinstance(data.get("identity"), Mapping) else {}
        merged = dict(data)
        merged["identity"] = identity
        profile = ShiftypadProfile.from_dict(merged)
        return cls(
            actor_id=actor_id,
            profile=profile,
            bound_at=str(data.get("bound_at") or ""),
            last_sync_at=str(data.get("last_sync_at") or ""),
            last_error=str(data.get("last_error") or ""),
            stale=bool(data.get("stale")),
            sync_count=int(data.get("sync_count") or 1),
        )


__all__ = [
    "SERVER_ALIASES",
    "SERVER_LABELS",
    "ReadonlyBinding",
    "Resolution",
    "ShiftypadCharacter",
    "ShiftypadIdentity",
    "ShiftypadInputError",
    "ShiftypadPrivateError",
    "ShiftypadProfile",
    "ShiftypadUpstreamError",
]
