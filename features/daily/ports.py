# SPDX-License-Identifier: GPL-3.0-or-later
"""Daily 用例按消费者划分的持久化端口。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol


class DailyAccountReader(Protocol):
    """读取签到账号所需的能力。"""

    def get_account(
        self, qq_id: str, with_cookie: bool = True
    ) -> Mapping[str, Any] | None:
        """读取绑定账号及签到凭据。"""


class DailyCommandStore(Protocol):
    """Daily 命令的偏好、摘要与凭据失效端口。"""

    def set_auto_daily(self, qq_id: str, enabled: bool) -> bool:
        """保存账号所有者显式开启的自动签到偏好。"""

    def get_setting(self, key: str, default: Any = None) -> Any:
        """读取 Daily 命令拥有的摘要设置或结果。"""

    def mark_cookie_invalid(self, qq_id: str) -> None:
        """标记绑定凭据失效。"""


class DailyStore(Protocol):
    """Daily runner 所需的最小账号、运行记录与结果端口。"""

    def get_run(self, run_key: str) -> Mapping[str, Any] | None:
        """读取一条签到运行记录。"""

    def claim_run(
        self, run_key: str, qq_id: str, action: str, *, initial_status: str
    ) -> bool:
        """在签到读取/写入前原子创建执行意图。"""

    def transition_run(
        self,
        run_key: str,
        *,
        from_statuses: set[str],
        to_status: str,
        detail: str = "",
        stale_after: int | None = None,
        refresh_created_at: bool = False,
    ) -> bool:
        """原子迁移 Daily 运行记录，状态条件由调用方提供。"""

    def finish_run(self, run_key: str, status: str, detail: str = "") -> None:
        """保存 Daily 用例计算出的终态。"""

    def mark_cookie_invalid(self, qq_id: str) -> None:
        """标记绑定凭据失效。"""

    def list_accounts(
        self,
        push_only: bool = False,
        with_cookie: bool = True,
        auto_daily_only: bool = False,
    ) -> Sequence[Mapping[str, Any]]:
        """读取符合任务范围的账号。"""

    def set_setting(self, key: str, value: Any) -> None:
        """保存 Daily feature 自己拥有的持久结果。"""


class DailyGateway(Protocol):
    """Daily 用例所需的账号只读与签到能力。"""

    async def get_profile(self, account: Mapping[str, Any]) -> Mapping[str, Any]:
        """读取账号资料以验证会话。"""

    async def get_daily_signin(self, account: Mapping[str, Any]) -> Mapping[str, Any]:
        """只读查询当天签到状态。"""

    async def perform_daily_signin(self, account: Mapping[str, Any]) -> str:
        """执行一次受状态保护的签到写操作。"""
