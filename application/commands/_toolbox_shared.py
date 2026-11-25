# SPDX-License-Identifier: GPL-3.0-or-later
"""按领域拆分后的工具命令共享基础支持与异常边界。"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any

from ...core.privacy import safe_exception_message
from ...features.favorite_grid.grid import FavoriteGridError
from ...features.overload_advice.advisor import OverloadAdviceError
from ...features.solo_raid.plans import SoloRaidPlanError
from ...features.sync.calculator import SyncLevelInputError
from .contracts import CommandContext, CommandResult, TextReply


class ToolboxDomainHandler:
    """为按领域拆分的工具用例提供统一账号读取、错误映射与文本回复边界。"""

    def __init__(
        self,
        services: Any,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.services = services
        self._clock = clock or (lambda: datetime.now().astimezone())

    async def handle(self, context: CommandContext) -> CommandResult:
        feature = context.parameters.get("feature", "").strip()
        action = context.parameters.get("action", "")
        value = context.parameters.get("value", "")
        try:
            result = await self._route(context, feature, action, value)
        except (
            ValueError,
            OverloadAdviceError,
            SyncLevelInputError,
            FavoriteGridError,
            SoloRaidPlanError,
        ) as exc:
            return self._text(str(exc))
        except Exception as exc:
            return self._text(f"查询失败：{safe_exception_message(exc)}")
        if isinstance(result, CommandResult):
            return result
        return self._text(str(result))

    async def _route(
        self, context: CommandContext, feature: str, action: str, value: str
    ) -> CommandResult | str:
        handler = getattr(self, f"_{feature}", None)
        if handler is None:
            return "工具功能尚未就绪。"
        return await handler(context, action, value)

    def _account(self, context: CommandContext) -> Mapping[str, Any] | None:
        reader = getattr(self.services, "account_reader", None)
        if reader is None or not context.actor_id:
            return None
        account = reader.get_account(str(context.actor_id))
        return account if isinstance(account, Mapping) else None

    async def _load_profile(self, account: Mapping[str, Any]) -> Mapping[str, Any]:
        loader = getattr(self.services, "profile_loader", None)
        if loader is None:
            raise ValueError("账号资料读取尚未装配")
        profile = await loader(account)
        return profile if isinstance(profile, Mapping) else {}

    async def _load_roster(self, account: Mapping[str, Any]) -> list[Mapping[str, Any]]:
        loader = getattr(self.services, "roster_loader", None)
        if loader is None:
            raise ValueError("角色名单读取尚未装配")
        rows = await loader(account)
        if not isinstance(rows, list):
            raise ValueError("角色名单响应格式无效")
        return rows

    def _character_directory(self) -> dict[str, Mapping[str, Any]]:
        directory: dict[str, Mapping[str, Any]] = {}
        for row in getattr(self.services, "grid_rows", ()):
            if not isinstance(row, Mapping):
                continue
            code = str(row.get("name_code") or row.get("resource_id") or "").strip()
            if code:
                directory[code] = row
        return directory

    def _fresh_readonly_binding(self, context: CommandContext):
        readonly = getattr(self.services, "shiftypad_readonly", None)
        if readonly is None:
            return None
        fresh = getattr(readonly, "fresh_binding", None)
        if callable(fresh):
            return fresh(context.actor_id)
        return None

    @staticmethod
    def _text(text: str) -> CommandResult:
        return CommandResult((TextReply(text),))


__all__ = ["ToolboxDomainHandler"]
