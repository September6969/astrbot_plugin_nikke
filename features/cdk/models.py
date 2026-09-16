# SPDX-License-Identifier: GPL-3.0-or-later
"""CDK 兑换数据模型。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class CdkRedeemResult:
    code: str
    success: bool
    message: str | None = None
    is_unknown: bool = False
    is_rate_limited: bool = False
    terminal: bool = True


@dataclass(slots=True)
class CdkBatchResult:
    results: list[CdkRedeemResult] = field(default_factory=list)
    stopped_by_rate_limit: bool = False
    stopped_by_cookie: bool = False

