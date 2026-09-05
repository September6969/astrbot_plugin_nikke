# SPDX-License-Identifier: GPL-3.0-or-later
"""Spine Spike 验证与受控后台预渲染队列。

遵循 contracts/assets_spine.md 契约：
1. Spine 属于工程可行性验证项，非出卡前置阻塞项；
2. 预渲染仅在受控后台队列异步执行，用户出卡绝不同步阻塞等待；
3. 严格匹配 major.minor 版本，未知版本标记 SPINE_VERSION_UNKNOWN，严禁盲猜默认 runtime；
4. 队列支持 per-key 去重、队列长度限制（默认最大20）、1~2 worker；
5. 插件关闭时支持优雅取消并回收。
"""

from __future__ import annotations

import logging
import queue
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from PIL import Image

logger = logging.getLogger("nikke.spine")


SPINE_VERSION_UNKNOWN = "SPINE_VERSION_UNKNOWN"


@dataclass(slots=True)
class SpineJob:
    cache_key: str
    character_id: str
    runtime_version: str | float | None
    callback: Callable[[Image.Image | None], None] | None = None


class SpineTaskQueue:
    """受控后台预渲染任务队列。"""

    def __init__(self, max_workers: int = 2, max_queue_size: int = 20):
        self.max_workers = max_workers
        self.max_queue_size = max_queue_size
        self._queue: queue.Queue[SpineJob | None] = queue.Queue(maxsize=max_queue_size)
        self._pending_keys: set[str] = set()
        self._lock = threading.Lock()
        self._workers: list[threading.Thread] = []
        self._stopping = False
        self._started = False

    def start(self, runner: Callable[[SpineJob], None]) -> None:
        with self._lock:
            if self._started:
                return
            self._started = True
            self._stopping = False
            for i in range(self.max_workers):
                worker = threading.Thread(
                    target=self._worker_loop,
                    args=(runner,),
                    name=f"nikke-spine-worker-{i}",
                    daemon=True,
                )
                self._workers.append(worker)
                worker.start()

    def enqueue(self, job: SpineJob) -> bool:
        with self._lock:
            if self._stopping:
                return False
            if job.cache_key in self._pending_keys:
                # Per-key 去重
                return False
            if self._queue.qsize() >= self.max_queue_size:
                logger.warning("Spine 预渲染队列已满 (%d)，丢弃任务: %s", self.max_queue_size, job.cache_key)
                return False
            self._pending_keys.add(job.cache_key)

        try:
            self._queue.put_nowait(job)
            return True
        except queue.Full:
            with self._lock:
                self._pending_keys.discard(job.cache_key)
            return False

    def _worker_loop(self, runner: Callable[[SpineJob], None]) -> None:
        while True:
            try:
                job = self._queue.get(timeout=1.0)
            except queue.Empty:
                if self._stopping:
                    break
                continue

            if job is None:
                self._queue.task_done()
                break

            try:
                runner(job)
            except Exception as exc:
                logger.error("Spine 预渲染任务执行异常 [%s]: %s", job.cache_key, exc)
            finally:
                with self._lock:
                    self._pending_keys.discard(job.cache_key)
                self._queue.task_done()

    def stop(self, wait: bool = True) -> None:
        with self._lock:
            if not self._started or self._stopping:
                return
            self._stopping = True

        for _ in self._workers:
            try:
                self._queue.put_nowait(None)
            except queue.Full:
                pass

        if wait:
            for worker in self._workers:
                worker.join(timeout=2.0)
        self._workers.clear()
        with self._lock:
            self._pending_keys.clear()
            self._started = False


class SpinePreRenderer:
    """Spine 预渲染器 Spike。

    负责环境探测、版本约束核验、无头渲染环境评估与渲染降级。
    """

    def __init__(self, cache_dir: str | Path):
        self.cache_dir = Path(cache_dir)
        self.prerender_dir = self.cache_dir / "portraits"
        self.prerender_dir.mkdir(parents=True, exist_ok=True)
        self.queue = SpineTaskQueue(max_workers=1, max_queue_size=20)
        self._available: bool | None = None

    def is_available(self) -> bool:
        """探测当前运行环境是否存在可用的 Spine runtime。"""
        if self._available is not None:
            return self._available
        # Spike 阶段探测：检查 spine 绑定库
        try:
            import spine  # type: ignore # noqa: F401
            self._available = True
        except ImportError:
            self._available = False
        return self._available

    def render_full_body(
        self, bundle_paths: dict[str, Path], version: str | float | None
    ) -> Image.Image | None:
        """根据导出的 major.minor 严格匹配 runtime。
        若版本未知或 runtime 缺失，返回 None 触发上层降级，严禁猜测。
        """
        if version is None or version == SPINE_VERSION_UNKNOWN:
            logger.warning("Spine 版本未知，严禁猜测默认 runtime，返回 None")
            return None

        if not self.is_available():
            logger.debug("当前环境未安装 Spine 原生 runtime，跳过实时预渲染")
            return None

        # 预留给 Spine runtime 接入（待 Spike 库选型通过后补齐）
        return None

    def handle_job(self, job: SpineJob) -> None:
        """队列工作线程执行回调。"""
        if job.runtime_version is None or job.runtime_version == SPINE_VERSION_UNKNOWN:
            logger.info("Spine 任务 [%s] 版本未知，标记跳过", job.cache_key)
            if job.callback:
                job.callback(None)
            return

        result = self.render_full_body({}, job.runtime_version)
        if result is not None:
            # 自动裁切人物 bounds + 60px 透明 padding
            bounds = result.getbbox()
            if bounds:
                left, top, right, bottom = bounds
                width, height = result.size
                crop_box = (
                    max(0, left - 60),
                    max(0, top - 60),
                    min(width, right + 60),
                    min(height, bottom + 60),
                )
                cropped = result.crop(crop_box)
            else:
                cropped = result

            output_path = self.prerender_dir / f"{job.cache_key}.png"
            try:
                cropped.save(output_path, format="PNG")
            except OSError as exc:
                logger.error("保存 Spine 预渲染缓存失败: %s", exc)

        if job.callback:
            job.callback(result)

