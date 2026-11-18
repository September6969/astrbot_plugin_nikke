"""只读角色名单端口，复用网关的账号隔离缓存。"""

from datetime import datetime, timezone
from typing import Any, Mapping, Protocol

from .identity import ArenaDirectory
from .models import ArenaRosterSnapshot


class AccountReader(Protocol):
    def get_account(self, qq_id: str) -> Mapping[str, Any] | None: ...


class RosterGateway(Protocol):
    async def get_roster(self, account: Mapping[str, Any],
                         include_details: bool = True) -> list[dict[str, Any]]: ...


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
        return ArenaRosterSnapshot(frozenset(keys), "partial" if unmapped else "available",
                                   unmapped, now, missing)
