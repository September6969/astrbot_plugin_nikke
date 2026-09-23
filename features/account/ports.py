# SPDX-License-Identifier: GPL-3.0-or-later
"""账号用例依赖的持久化端口。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol


class AccountStorePort(Protocol):
    """账号应用所需的最小持久化能力。"""

    def create_bind_session(
        self, token: str, qq_id: str, ttl: int = 600, *, status: str
    ) -> None:
        """创建有时效的一次性绑定会话。"""

    def get_account(
        self, qq_id: str, with_cookie: bool = True
    ) -> Mapping[str, Any] | None:
        """读取指定账号；状态查询必须关闭 Cookie 返回。"""

    def delete_account(self, qq_id: str) -> bool:
        """解除指定 QQ 的账号绑定。"""

    def set_push(self, qq_id: str, enabled: bool) -> bool:
        """更新账号的每日汇总偏好。"""

    def set_setting(self, key: str, value: Any) -> None:
        """持久化管理用例授权后的单项配置。"""

    def list_accounts(self, with_cookie: bool = True) -> Sequence[Mapping[str, Any]]:
        """列出账号；管理检查只读取非敏感字段。"""
