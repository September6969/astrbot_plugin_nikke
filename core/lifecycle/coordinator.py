# SPDX-License-Identifier: GPL-3.0-or-later
"""集中登记后台任务，并按依赖逆序关闭运行时资源。"""

from __future__ import annotations

import asyncio
import inspect
import logging
import concurrent.futures
import threading
import time
import math
from collections.abc import Awaitable, Callable, Coroutine
from typing import Any, cast

logger = logging.getLogger(__name__)


class RuntimeCoordinator:
    """插件实例级任务工厂与生命周期协调器。"""

    def __init__(
        self,
        *,
        task_factory: Callable[[Awaitable[Any]], asyncio.Task[Any]] | None = None,
        task_error_handler: Callable[[str, BaseException], None] | None = None,
        close_budget_seconds: float = 10.0,
        task_timeout_seconds: float = 2.0,
        cleanup_timeout_seconds: float = 2.0,
    ) -> None:
        self._task_factory = task_factory or self._default_task_factory
        self._task_error_handler = task_error_handler or self._log_task_error
        self._tasks: set[asyncio.Task[Any]] = set()
        self._cleanup_actions: list[tuple[str, Callable[[], Any]]] = []
        self._completed_cleanup: set[str] = set()
        self._state = "NEW"
        self._closing = False
        self._closed = False
        self._start_task: asyncio.Task[Any] | None = None
        self._close_lock = asyncio.Lock()
        for value in (close_budget_seconds, task_timeout_seconds, cleanup_timeout_seconds):
            if not math.isfinite(value) or value <= 0:
                raise ValueError("关闭预算必须是有限正数")
        self.close_budget_seconds = close_budget_seconds
        self.task_timeout_seconds = task_timeout_seconds
        self.cleanup_timeout_seconds = cleanup_timeout_seconds
        self._cleanup_tasks: dict[str, asyncio.Task[Any]] = {}
        self._cleanup_threads: dict[str, concurrent.futures.Future[Any]] = {}

    @property
    def survivors(self) -> tuple[str, ...]:
        """仍在运行的对象不能被 timeout 冒充为已经终止。"""
        return tuple(sorted(
            [f"task:{id(task)}" for task in self._tasks if not task.done()]
            + [f"cleanup:{name}" for name, task in self._cleanup_tasks.items() if not task.done()]
            + [f"thread:{name}" for name, future in self._cleanup_threads.items() if not future.done()]
        ))

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

    def create_task(self, awaitable: Awaitable[Any]) -> asyncio.Task[Any] | None:
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
    ) -> asyncio.Task[Any]:
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
        """共享总预算内停止工作并逐资源隔离，未完成对象保留供重试。"""
        deadline = time.monotonic() + self.close_budget_seconds
        await asyncio.wait_for(self._close_lock.acquire(), timeout=self.close_budget_seconds)
        try:
            if self._closed:
                return
            self._closing = True
            self._state = "STOP_ACCEPTING_NEW_WORK"

            current = asyncio.current_task()
            active = [
                task for task in self._tasks
                if task is not current and not task.done()
            ]
            for active_task in active:
                active_task.cancel()
            failures: list[tuple[str, BaseException]] = []
            self._state = "CLOSING_TASKS"
            if active:
                _, pending = await asyncio.wait(active, timeout=min(
                    self.task_timeout_seconds, max(0.0, (deadline - time.monotonic()) / 2)))
                if pending:
                    failures.append(("tasks", TimeoutError("后台任务取消后仍未退出")))

            self._state = "CLEANING_RESOURCES"
            actions = [(name, callback) for name, callback in reversed(self._cleanup_actions)
                       if name not in self._completed_cleanup]
            for index, (name, callback) in enumerate(actions):
                if name in self._completed_cleanup:
                    continue
                try:
                    available = deadline - time.monotonic()
                    if available <= 0:
                        raise TimeoutError("总关闭预算耗尽")
                    task = self._cleanup_tasks.get(name)
                    if task is None or task.cancelled() or (task.done() and task.exception() is not None):
                        task = self._default_task_factory(self._invoke_cleanup(name, callback))
                        self._cleanup_tasks[name] = task
                        task.add_done_callback(self._observe_cleanup)
                    # 给后续独立资源留下机会，不让首个坏 cleanup 消耗全部预算。
                    budget = min(self.cleanup_timeout_seconds, available / (len(actions) - index))
                    done, _ = await asyncio.wait({task}, timeout=budget)
                    if not done:
                        if inspect.iscoroutinefunction(callback):
                            task.cancel()
                        raise TimeoutError(f"清理资源超时：{name}")
                    if task.cancelled():
                        raise RuntimeError(f"资源自行取消清理：{name}")
                    task.result()
                except Exception as exc:
                    failures.append((name, exc))
                else:
                    self._completed_cleanup.add(name)

            if failures:
                self._state = "DEGRADED"
                raise failures[0][1]
            self._closed = True
            self._state = "CLOSED"
        except asyncio.CancelledError:
            self._state = "DEGRADED"
            raise
        finally:
            self._close_lock.release()

    async def _invoke_cleanup(self, name: str, callback: Callable[[], Any]) -> None:
        if inspect.iscoroutinefunction(callback):
            result = callback()
        else:
            # 独立 daemon 线程不会冻结事件循环；超时后仍跟踪真实线程完成。
            future: concurrent.futures.Future[Any] = concurrent.futures.Future()
            self._cleanup_threads[name] = future
            def invoke() -> None:
                try:
                    future.set_result(callback())
                except BaseException as exc:
                    future.set_exception(exc)
            threading.Thread(target=invoke, name=f"nikke-cleanup-{name}", daemon=True).start()
            result = await asyncio.shield(asyncio.wrap_future(future))
        if inspect.isawaitable(result):
            await result

    @staticmethod
    def _observe_cleanup(task: asyncio.Task[Any]) -> None:
        # 关闭者可能已返回；保留任务以便重试，同时读取迟到异常避免静默遗失。
        if not task.cancelled():
            task.exception()

    def _on_task_done(self, task: asyncio.Task[Any]) -> None:
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
    def _default_task_factory(awaitable: Awaitable[Any]) -> asyncio.Task[Any]:
        return asyncio.create_task(cast(Coroutine[Any, Any, Any], awaitable))

    @staticmethod
    def _close_awaitable(awaitable: Awaitable[Any]) -> None:
        close = getattr(awaitable, "close", None)
        if callable(close):
            close()

    @staticmethod
    def _log_task_error(name: str, error: BaseException) -> None:
        logger.warning("后台任务 %s 失败：%s", name, type(error).__name__)
