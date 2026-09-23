# SPDX-License-Identifier: GPL-3.0-or-later
"""账号绑定、状态和偏好设置用例。"""

from __future__ import annotations

import secrets
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from .ports import AccountStorePort
from .status import BIND_SESSION_PENDING


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
            token,
            str(qq_id),
            self.BIND_SESSION_TTL_SECONDS,
            status=BIND_SESSION_PENDING,
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
