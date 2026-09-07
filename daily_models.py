"""社区日常任务的结构化结果合同。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class DailyTaskStatus(str, Enum):
    """签到及未来日常任务共用的保守状态集合。"""

    SUCCESS = "success"
    ALREADY_DONE = "already_done"
    PENDING = "pending"
    FAILED = "failed"
    RATE_LIMITED = "rate_limited"
    COOKIE_EXPIRED = "cookie_expired"
    UNKNOWN_AFTER_ACTION = "unknown_after_action"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class DailyTaskResult:
    """一个账号的一次日常任务结果，不把未知结果降级为失败或成功。"""

    account_name: str
    status: DailyTaskStatus
    detail: str

    @property
    def run_status(self) -> str:
        """返回 action_runs 使用的保守状态，不伪造写操作成功。"""
        if self.status is DailyTaskStatus.UNKNOWN_AFTER_ACTION:
            return "unknown"
        if self.status is DailyTaskStatus.COOKIE_EXPIRED:
            return "expired"
        if self.status in {DailyTaskStatus.FAILED, DailyTaskStatus.RATE_LIMITED}:
            return "failed"
        return "success"

    def to_storage(self) -> dict[str, str]:
        """转换为可安全 JSON 序列化的汇总记录。"""
        return {
            "account_name": self.account_name,
            "status": self.status.value,
            "detail": self.detail,
        }

    @classmethod
    def from_storage(cls, payload: Any) -> "DailyTaskResult | None":
        """严格读取新格式；旧 tuple 或损坏记录不冒充成功。"""
        if not isinstance(payload, dict):
            return None
        try:
            status = DailyTaskStatus(str(payload.get("status", "")))
        except ValueError:
            return None
        account_name = payload.get("account_name")
        detail = payload.get("detail")
        if not isinstance(account_name, str) or not isinstance(detail, str):
            return None
        return cls(account_name=account_name, status=status, detail=detail)

    def summary_row(self) -> tuple[str, str]:
        """兼容现有图片汇总 renderer 的两列输入。"""
        return self.account_name, self.detail
