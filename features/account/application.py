# SPDX-License-Identifier: GPL-3.0-or-later
"""账号绑定、状态和偏好设置用例。"""

from __future__ import annotations

import secrets
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Protocol


class AccountStorePort(Protocol):
    """账号命令需要的最小持久化能力。"""

    def create_bind_session(self, token: str, qq_id: str, ttl: int = 600) -> None:
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
        """持久化插件设置。"""

    def list_accounts(self, with_cookie: bool = True) -> Sequence[Mapping[str, Any]]:
        """列出账号；管理员健康检查只读非敏感字段。"""


class AccountApplication:
    """封装账号命令和管理命令的存储用例。"""

    BIND_SESSION_TTL_SECONDS = 600

    def __init__(
        self,
        store: AccountStorePort,
        *,
        token_factory: Callable[[int], str] = secrets.token_urlsafe,
    ) -> None:
        self._store = store
        self._token_factory = token_factory

    def create_binding_url(self, qq_id: str, public_base_url: str) -> str:
        """创建一次性绑定会话并返回不泄漏给其他层的公开链接。"""
        token = self._token_factory(36)
        self._store.create_bind_session(
            token, str(qq_id), self.BIND_SESSION_TTL_SECONDS
        )
        return f"{public_base_url.rstrip('/')}/bind/{token}"

    def unbind(self, qq_id: str) -> bool:
        """解除用户自己的账号绑定。"""
        return self._store.delete_account(str(qq_id))

    def account_status(self, qq_id: str) -> Mapping[str, Any] | None:
        """读取展示状态所需的非凭据账号字段。"""
        return self._store.get_account(str(qq_id), with_cookie=False)

    def set_daily_summary(self, qq_id: str, enabled: bool) -> bool:
        """保存账号每日汇总偏好。"""
        return self._store.set_push(str(qq_id), bool(enabled))

    def set_setting(self, key: str, value: Any) -> None:
        """保存受管理命令授权后的单项配置。"""
        self._store.set_setting(key, value)

    def account_count(self) -> int:
        """只读取账号条数，不解密或返回 Cookie。"""
        return len(self._store.list_accounts(with_cookie=False))
