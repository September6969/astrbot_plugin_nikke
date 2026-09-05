# SPDX-License-Identifier: GPL-3.0-or-later
"""公告、活动与推送数据合同模型。

遵循 contracts/announcements.md：
1. 内容实体不保存全局 pushed 状态；
2. 实体包含 content_id, body_hash, content_version, published_at, source_url；
3. 投递去重键：target_id + content_id + content_version + push_type；
4. Deadline 去重键：target_id + deadline_id + deadline_version + reminder_hour + push_type。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field


@dataclass(slots=True)
class AnnouncementRecord:
    content_id: str
    title: str
    body: str
    published_at: str
    source_url: str = ""
    content_version: int = 1
    category: str = "general"  # maintenance / event / update / notice
    deadline_at: str | None = None
    deadline_version: int = 1

    @property
    def body_hash(self) -> str:
        return hashlib.sha256(self.body.encode("utf-8")).hexdigest()

    def compute_push_key(self, target_id: str, push_type: str = "announcement") -> str:
        """计算公告投递去重键。"""
        return f"{target_id}:{self.content_id}:{self.content_version}:{push_type}"

    def compute_deadline_key(
        self,
        target_id: str,
        reminder_hour: int,
        push_type: str = "deadline",
    ) -> str:
        """计算截止时间提醒投递去重键。"""
        return (
            f"{target_id}:{self.content_id}:{self.deadline_version}:"
            f"{reminder_hour}:{push_type}"
        )

