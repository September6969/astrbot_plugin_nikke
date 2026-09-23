# SPDX-License-Identifier: GPL-3.0-or-later
"""集中登记后台任务，并按依赖逆序关闭运行时资源。"""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Awaitable, Callable
from typing import Any

logger = logging.getLogger(__name__)


class RuntimeCoordinator:
    """插件实例级任务工厂与生命周期协调器。"""

    def __init__(
        self,
        *,
        task_factory: Callable[[Awaitable[Any]], asyncio.Task] | None = None,
        task_error_handler: Callable[[str, BaseException], None] | None = None,
    ) -> None:
        self._task_factory = task_factory or asyncio.create_task
        self._task_error_handler = task_error_handler or self._log_task_error
        self._tasks: set[asyncio.Task] = set()
        self._cleanup_actions: list[tuple[str, Callable[[], Any]]] = []
        self._completed_cleanup: set[str] = set()
        self._state = "NEW"
        self._closing = False
        self._closed = False
        self._start_task: asyncio.Task | None = None
        self._close_lock = asyncio.Lock()

    @property
    def closing(self) -> bool:
        return self._closing or self._closed

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def state(self) -> str:
        return self._state

    @property
    def active_task_count(self) -> int:
        return sum(not task.done() for task in self._tasks)

    def register_cleanup(self, name: str, callback: Callable[[], Any]) -> None:
        """按资源创建/依赖顺序登记清理；close 以逆序执行。"""
        if self._start_task is not None or self.closing:
            raise RuntimeError("运行时启动后不能再登记清理资源")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("清理资源必须有名称")
        if any(existing == name for existing, _ in self._cleanup_actions):
            raise ValueError(f"重复登记运行时资源：{name}")
        self._cleanup_actions.append((name, callback))

    def create_task(self, awaitable: Awaitable[Any]) -> asyncio.Task | None:
        """创建并登记所有插件级后台任务。"""
        if not inspect.isawaitable(awaitable):
            raise TypeError("RuntimeCoordinator 只接受 awaitable")
        if self.closing:
            self._close_awaitable(awaitable)
            return None
        try:
            task = self._task_factory(awaitable)
        except BaseException:
            self._close_awaitable(awaitable)
            raise
        self._tasks.add(task)
        task.add_done_callback(self._on_task_done)
        return task

    def start(
        self,
        initialize: Callable[[], Awaitable[Any]],
        scheduler: Callable[[], Awaitable[Any]],
    ) -> asyncio.Task:
        """只启动一次初始化和 scheduler；重复调用返回同一个任务。"""
        if self._start_task is not None:
            return self._start_task
        if self.closing:
            raise RuntimeError("已关闭的运行时不能重新启动")

        async def run() -> None:
            self._state = "STARTING"
            try:
                await initialize()
                if self.closing:
                    return
                self._state = "RUNNING"
                await scheduler()
            except asyncio.CancelledError:
                raise
            except Exception:
                self._state = "FAILED"
                try:
                    await self.close()
                except Exception as cleanup_error:
                    self._task_error_handler("startup cleanup", cleanup_error)
                self._state = "FAILED"
                raise
            else:
                if not self.closing:
                    self._state = "STOPPED"

        task = self.create_task(run())
        if task is None:
            raise RuntimeError("运行时启动任务未能登记")
        self._start_task = task
        return task

    async def close(self) -> None:
        """先阻止新任务，再取消并等待任务，最后逆序关闭资源。"""
        async with self._close_lock:
            if self._closed:
                return
            self._closing = True
            self._state = "CLOSING"

            current = asyncio.current_task()
            active = [
                task for task in self._tasks
                if task is not current and not task.done()
            ]
            for task in active:
                task.cancel()
            if active:
                await asyncio.gather(*active, return_exceptions=True)

            failures: list[tuple[str, BaseException]] = []
            for name, callback in reversed(self._cleanup_actions):
                if name in self._completed_cleanup:
                    continue
                try:
                    result = callback()
                    if inspect.isawaitable(result):
                        await result
                except Exception as exc:
                    failures.append((name, exc))
                else:
                    self._completed_cleanup.add(name)

            if failures:
                self._state = "CLOSING"
                raise failures[0][1]
            self._closed = True
            self._state = "CLOSED"

    def _on_task_done(self, task: asyncio.Task) -> None:
        self._tasks.discard(task)
        if task.cancelled():
            return
        try:
            error = task.exception()
        except asyncio.CancelledError:
            return
        if error is not None:
            self._task_error_handler("background task", error)

    @staticmethod
    def _close_awaitable(awaitable: Awaitable[Any]) -> None:
        close = getattr(awaitable, "close", None)
        if callable(close):
            close()

    @staticmethod
    def _log_task_error(name: str, error: BaseException) -> None:
        logger.warning("后台任务 %s 失败：%s", name, type(error).__name__)
