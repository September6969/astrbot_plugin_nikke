# SPDX-License-Identifier: GPL-3.0-or-later
"""延迟反馈 provider，复用唯一运行时任务所有者。"""

from __future__ import annotations

from ..feedback import DelayedFeedbackManager
from ..lifecycle.coordinator import RuntimeCoordinator


def create_feedback_manager(
    coordinator: RuntimeCoordinator,
) -> DelayedFeedbackManager:
    """让延迟反馈任务归属 RuntimeCoordinator 并由其统一取消。"""
    return DelayedFeedbackManager(1.5, task_factory=coordinator.create_task)
