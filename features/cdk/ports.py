# SPDX-License-Identifier: GPL-3.0-or-later
"""CDK 用例依赖的账号与运行记录端口。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol


class CdkAccountReader(Protocol):
    """读取当前用户绑定账号的最小端口。"""

    def get_account(
        self, qq_id: str, with_cookie: bool = True
    ) -> Mapping[str, Any] | None:
        """返回绑定账号及写入接口凭据。"""


class CdkCommandStore(Protocol):
    """CDK 命令处理凭据失效所需的能力。"""

    def mark_cookie_invalid(self, qq_id: str) -> None:
        """标记绑定凭据失效。"""


class CdkRunStore(Protocol):
    """CDK 写入流程所需的原子运行记录能力。"""

    def get_run(self, run_key: str) -> Mapping[str, Any] | None:
        """读取一条运行记录。"""

    def list_runs(self, *, action: str | None = None) -> Sequence[Mapping[str, Any]]:
        """按通用 action 字段列出运行记录，不解释业务 key。"""

    def claim_run(
        self, run_key: str, qq_id: str, action: str, *, initial_status: str
    ) -> bool:
        """原子创建运行记录。"""

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
        """原子迁移 CDK 运行记录，状态条件由调用方提供。"""

    def finish_run(self, run_key: str, status: str, detail: str = "") -> None:
        """保存调用方计算出的终态。"""
