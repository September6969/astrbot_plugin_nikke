# SPDX-License-Identifier: GPL-3.0-or-later
"""绑定 Web 协议依赖的最小存储端口。"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, Protocol


class BindingSessionStore(Protocol):
    """Web 绑定流程依赖的文件就绪与绑定会话存储能力。"""

    db_path: Path
    key_path: Path

    def create_bind_session(self, token: str, qq_id: str, ttl: int = 600) -> None:
        """创建一次性绑定会话。"""

    def get_bind_session(self, token: str) -> Mapping[str, Any] | None:
        """查询绑定会话状态。"""

    def fail_bind_session(self, token: str, error: str) -> None:
        """记录验证失败状态。"""

    def consume_bind_session(
        self,
        token: str,
        cookie: str,
        game_uid: str,
        game_openid: str,
        nickname: str,
        role_name: str,
        area_id: str,
        x_common_params: str = "",
        user_agent: str = "",
    ) -> str:
        """在同一事务中消费会话并持久化账号凭据。"""

    def get_account(
        self, qq_id: str, with_cookie: bool = True
    ) -> Mapping[str, Any] | None:
        """读取绑定用户状态；公开状态响应不读取凭据。"""
