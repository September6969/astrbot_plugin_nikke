# SPDX-License-Identifier: GPL-3.0-or-later
"""可取消的延迟处理中反馈任务管理器。

遵循 contracts/daily_voice_feedback.md：
1. 业务在 delay 阈值内完成时立即 cancel delayed task 并 suppress CancelledError；
2. 保证不会发生“卡片已渲染发送，延迟提示却晚到”的尴尬体验；
3. 追踪 handle 状态：delayed_task, message_id, sent_at, finished；
4. 支持在插件关闭时安全回收所有进行中的延迟任务。
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

logger = logging.getLogger("nikke.feedback")


@dataclass(eq=False)
class FeedbackHandle:
    delayed_task: asyncio.Task | None = None
    message_id: str | None = None
    sent_at: float | None = None
    finished: bool = False
    cancelled: bool = False

    async def cancel(self) -> None:
        self.finished = True
        self.cancelled = True
        if self.delayed_task and not self.delayed_task.done():
            self.delayed_task.cancel()
            try:
                await self.delayed_task
            except asyncio.CancelledError:
                pass


class DelayedFeedbackManager:
    def __init__(self, default_delay: float = 1.5):
        self.default_delay = default_delay
        self._active_handles: set[FeedbackHandle] = set()

    def start_delayed_feedback(
        self,
        sender: Callable[[], Awaitable[Any]],
        delay: float | None = None,
    ) -> FeedbackHandle:
        """启动一个延迟发送“正在处理”消息的后台任务。"""
        effective_delay = delay if delay is not None else self.default_delay
        handle = FeedbackHandle()
        self._active_handles.add(handle)

        async def _runner():
            try:
                await asyncio.sleep(effective_delay)
                if not handle.finished and not handle.cancelled:
                    handle.sent_at = time.monotonic()
                    sent_result = await sender()
                    if sent_result and hasattr(sent_result, "message_id"):
                        handle.message_id = str(sent_result.message_id)
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                logger.warning("延迟处理提示发送异常: %s", exc)
            finally:
                self._active_handles.discard(handle)

        handle.delayed_task = asyncio.create_task(_runner())
        return handle

    async def close(self) -> None:
        """插件关闭时取消并等待全部延迟任务。"""
        current = list(self._active_handles)
        for handle in current:
            await handle.cancel()
        self._active_handles.clear()

