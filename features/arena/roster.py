"""只读角色名单端口，复用网关的账号隔离缓存。"""

from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Protocol

from .identity import ArenaDirectory
from .models import FAVORITE_MANUAL, FAVORITE_OFFICIAL, ArenaRosterSnapshot


class AccountReader(Protocol):
    def get_account(self, qq_id: str) -> Mapping[str, Any] | None: ...


class RosterGateway(Protocol):
    async def get_roster(self, account: Mapping[str, Any],
                         include_details: bool = True) -> list[dict[str, Any]]: ...


class CachedDetailReader(Protocol):
    """可选端口：只读取网关已缓存的角色详情，不得发起网络请求。"""

    def cached_character_details(self, account: Mapping[str, Any]) -> Mapping[str, Mapping[str, Any]]: ...


class ArenaRosterProvider:
    def __init__(self, accounts: AccountReader, gateway: RosterGateway, directory: ArenaDirectory):
        self.accounts = accounts
        self.gateway = gateway
        self.directory = directory

    async def owned(self, actor_id: str) -> ArenaRosterSnapshot:
        now = datetime.now(timezone.utc).isoformat()
        missing = ("skills", "treasures", "cubes", "overload")
        account = self.accounts.get_account(str(actor_id))
        if not account:
            return ArenaRosterSnapshot(frozenset(), "unbound", 0, now, missing)
        if not account.get("cookie_valid", True):
            return ArenaRosterSnapshot(frozenset(), "expired", 0, now, missing)
        # 异常由应用层转为公共错误，取消信号继续向上传播。
        rows = await self.gateway.get_roster(account, include_details=False)
        if not isinstance(rows, list):
            raise ValueError("角色名单响应格式无效。")
        keys: set[str] = set()
        unmapped = 0
        for row in rows:
            if not isinstance(row, dict):
                unmapped += 1
                continue
            key = self.directory.by_code.get(str(row.get("name_code", "")))
            if key:
                keys.add(key)
            else:
                unmapped += 1
        snapshot = ArenaRosterSnapshot(frozenset(keys), "partial" if unmapped else "available",
                                       unmapped, now, missing)
        return classify_favorites(snapshot, self._cached_details(account), self.directory)

    def _cached_details(self, account: Mapping[str, Any]) -> Mapping[str, Mapping[str, Any]]:
        reader = getattr(self.gateway, "cached_character_details", None)
        if not callable(reader):
            return {}
        try:
            details = reader(account)
        except Exception:
            # 缓存读取失败只意味着没有官方确认，绝不阻断基础名单。
            return {}
        return details if isinstance(details, Mapping) else {}


def classify_favorites(snapshot: ArenaRosterSnapshot, details: Mapping[str, Mapping[str, Any]],
                       directory: ArenaDirectory) -> ArenaRosterSnapshot:
    """按官方详情区分珍藏：装备专属珍藏才确认，缺详情只记为基础名单推测。"""
    confirmed, unconfirmed, absent = [], [], []
    for base, variant in sorted(directory.variant_of.items()):
        if base not in snapshot.keys:
            continue
        detail = details.get(directory.characters[base].name_code)
        if not isinstance(detail, Mapping):
            unconfirmed.append(variant)
        elif directory.treasure_items.get(str(detail.get("favorite_item_tid") or "").strip()) == variant:
            confirmed.append(variant)
        else:
            absent.append(variant)
    return replace(snapshot, keys=snapshot.keys | frozenset(confirmed),
                   favorites=tuple((key, FAVORITE_OFFICIAL) for key in confirmed),
                   favorite_unconfirmed=tuple(unconfirmed), favorite_absent=tuple(absent))


def apply_favorite_marks(snapshot: ArenaRosterSnapshot, marks: Iterable[str],
                         directory: ArenaDirectory) -> ArenaRosterSnapshot:
    """把用户本次声明的珍藏并入可用范围，只接受基础名单已持有且官方未否定的角色。"""
    added, notes = [], []
    official = {key for key, _source in snapshot.favorites}
    for key in marks:
        name = directory.characters[key].name
        if key in official:
            continue
        if key in snapshot.favorite_absent:
            notes.append(f"{name}：官方详情显示未装备专属珍藏，手动标记未生效。")
        elif key in snapshot.favorite_unconfirmed:
            added.append(key)
        else:
            notes.append(f"{name}：本体不在已绑定角色名单内，手动标记未生效。")
    if not added and not notes:
        return snapshot
    return replace(
        snapshot, keys=snapshot.keys | frozenset(added),
        favorites=snapshot.favorites + tuple((key, FAVORITE_MANUAL) for key in added),
        favorite_unconfirmed=tuple(key for key in snapshot.favorite_unconfirmed if key not in added),
        notes=snapshot.notes + tuple(notes),
    )
