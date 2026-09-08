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
import math
import queue
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Mapping

from PIL import Image

from ..log_privacy import safe_exception_message, sanitize_log_text

logger = logging.getLogger("nikke.spine")


SPINE_VERSION_UNKNOWN = "SPINE_VERSION_UNKNOWN"


@dataclass(slots=True)
class SpineJob:
    cache_key: str
    character_id: str
    runtime_version: str | float | None
    callback: Callable[[Image.Image | None], None] | None = None
    # 总预算从入队时开始计算，覆盖排队等待和后续运行时阶段。
    budget_seconds: float | None = None
    enqueued_at: float = field(default_factory=time.monotonic, init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.cache_key, str) or not self.cache_key.strip():
            raise ValueError("Spine cache_key 必须是非空文本")
        if any(char in self.cache_key for char in ("/", "\\", ":", "\x00")):
            raise ValueError("Spine cache_key 不能包含路径分隔符")
        if self.cache_key in {".", ".."}:
            raise ValueError("Spine cache_key 不能是路径占位符")
        if not isinstance(self.character_id, str) or not self.character_id.strip():
            raise ValueError("Spine character_id 必须是非空文本")
        if self.runtime_version is not None:
            if isinstance(self.runtime_version, bool):
                raise ValueError("Spine runtime_version 不能是布尔值")
            if isinstance(self.runtime_version, str) and not self.runtime_version.strip():
                raise ValueError("Spine runtime_version 不能是空白文本")
            if isinstance(self.runtime_version, (int, float)) and (
                not math.isfinite(float(self.runtime_version)) or self.runtime_version <= 0
            ):
                raise ValueError("Spine runtime_version 数值必须是正数")
            if not isinstance(self.runtime_version, (str, int, float)):
                raise ValueError("Spine runtime_version 类型无效")
        if self.budget_seconds is not None:
            if isinstance(self.budget_seconds, bool) or not isinstance(self.budget_seconds, (int, float)):
                raise ValueError("Spine 总预算必须是正数")
            if not math.isfinite(float(self.budget_seconds)) or self.budget_seconds <= 0:
                raise ValueError("Spine 总预算必须是正数")

    def is_expired(self, now: float | None = None) -> bool:
        """判断任务是否已在队列或执行前耗尽总预算。"""
        if self.budget_seconds is None:
            return False
        return (time.monotonic() if now is None else now) - self.enqueued_at >= self.budget_seconds


@dataclass(frozen=True, slots=True)
class SpineEvidenceReport:
    """把现场证据层与实际运行结果分开，避免预检查被误报为真实渲染。"""

    status: str
    resource_discovery: str
    bundle_integrity: str
    spine_version: str
    runtime_compatibility: str
    legal_test_asset: str
    linux_headless: str
    render_verified: str
    benchmark: str
    detail: str | None = None

    @classmethod
    def from_inspection(cls, inspection: Mapping[str, object]) -> "SpineEvidenceReport":
        status = str(inspection.get("status", "INSPECTION_FAILED"))
        observed_version = inspection.get("major_minor")
        return cls(
            status=status,
            resource_discovery="LOCAL_INPUT_ONLY",
            bundle_integrity="PASS" if status != "INSPECTION_FAILED" else "FAIL",
            spine_version=str(observed_version) if observed_version else SPINE_VERSION_UNKNOWN,
            runtime_compatibility="NOT_EXECUTED",
            legal_test_asset="NOT_VERIFIED",
            linux_headless="NOT_EXECUTED",
            render_verified="NOT_EXECUTED",
            benchmark="NOT_EXECUTED",
        )

    def as_dict(self) -> dict[str, str | None]:
        return {
            "status": self.status,
            "resource_discovery": self.resource_discovery,
            "bundle_integrity": self.bundle_integrity,
            "spine_version": self.spine_version,
            "runtime_compatibility": self.runtime_compatibility,
            "legal_test_asset": self.legal_test_asset,
            "linux_headless": self.linux_headless,
            "render_verified": self.render_verified,
            "benchmark": self.benchmark,
            "detail": self.detail,
        }


class SpineTaskQueue:
    """受控后台预渲染任务队列。"""

    def __init__(self, max_workers: int = 2, max_queue_size: int = 20):
        if isinstance(max_workers, bool) or not isinstance(max_workers, int):
            raise ValueError("Spine worker 数必须是整数")
        if max_workers < 1 or max_workers > 2:
            raise ValueError("Spine worker 数必须在 1 到 2 之间")
        if isinstance(max_queue_size, bool) or not isinstance(max_queue_size, int):
            raise ValueError("Spine 队列容量必须是整数")
        if max_queue_size < 1:
            raise ValueError("Spine 队列容量必须为正数")
        self.max_workers = max_workers
        self.max_queue_size = max_queue_size
        self._queue: queue.Queue[SpineJob] = queue.Queue(maxsize=max_queue_size)
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

    @property
    def is_running(self) -> bool:
        with self._lock:
            return self._started and not self._stopping

    @property
    def pending_count(self) -> int:
        with self._lock:
            return len(self._pending_keys)

    def wait_idle(self, timeout: float | None = None) -> bool:
        """等待当前任务完成；超时只返回 False，不改变队列状态。"""
        if timeout is None:
            self._queue.join()
            return True
        deadline = time.monotonic() + timeout
        while True:
            if self._queue.unfinished_tasks == 0:
                return True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            time.sleep(min(0.01, remaining))

    def enqueue(self, job: SpineJob) -> bool:
        with self._lock:
            if self._stopping:
                return False
            if job.cache_key in self._pending_keys:
                # Per-key 去重
                return False
            if self._queue.qsize() >= self.max_queue_size:
                logger.warning(
                    "Spine 预渲染队列已满 (%d)，丢弃任务: %s",
                    self.max_queue_size,
                    sanitize_log_text(job.cache_key, max_length=120),
                )
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
        try:
            while True:
                try:
                    job = self._queue.get(timeout=0.05)
                except queue.Empty:
                    if self._stopping:
                        break
                    continue

                if job is None:
                    self._queue.task_done()
                    break

                try:
                    if job.is_expired():
                        logger.warning(
                            "Spine 任务 [%s] 在队列中耗尽总预算",
                            sanitize_log_text(job.cache_key, max_length=120),
                        )
                        if job.callback:
                            job.callback(None)
                        continue
                    runner(job)
                except Exception as exc:
                    logger.error(
                        "Spine 预渲染任务执行异常 [%s]: %s",
                        sanitize_log_text(job.cache_key, max_length=120),
                        safe_exception_message(exc),
                    )
                finally:
                    with self._lock:
                        self._pending_keys.discard(job.cache_key)
                    self._queue.task_done()
        finally:
            current = threading.current_thread()
            with self._lock:
                self._workers = [worker for worker in self._workers if worker is not current]
                if not self._workers:
                    self._started = False
                    self._stopping = False

    def stop(self, wait: bool = True) -> None:
        with self._lock:
            if not self._started or self._stopping:
                return
            self._stopping = True
            workers = list(self._workers)
        # worker 会在队列排空后观察 _stopping 并退出；这样不会因队列已满而
        # 无法投递 sentinel，也不会遗留未完成的 queue.task_done()。
        if wait:
            for worker in workers:
                worker.join(timeout=2.0)


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

    def start(self) -> None:
        """仅供明确选择的实验/测试调用，不由生产出卡路径自动启动。"""
        self.queue.start(self.handle_job)

    def close(self, wait: bool = True) -> None:
        self.queue.stop(wait=wait)

    def inspect_bundle(
        self,
        atlas: str | Path,
        skeleton: str | Path,
        expected_version: str | None = None,
    ) -> SpineEvidenceReport:
        """执行本地无运行时预检查，并明确返回尚未获得的证据层。"""
        from ..scripts.inspect_spine_bundle import inspect

        try:
            result = inspect(Path(atlas), Path(skeleton), expected_version)
        except (OSError, ValueError, TypeError, AttributeError) as exc:
            return SpineEvidenceReport(
                status="INSPECTION_FAILED",
                resource_discovery="LOCAL_INPUT_ONLY",
                bundle_integrity="FAIL",
                spine_version="SPINE_VERSION_UNKNOWN",
                runtime_compatibility="NOT_EXECUTED",
                legal_test_asset="NOT_VERIFIED",
                linux_headless="NOT_EXECUTED",
                render_verified="NOT_EXECUTED",
                benchmark="NOT_EXECUTED",
                detail=str(exc),
            )
        return SpineEvidenceReport.from_inspection(result)

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
            logger.info(
                "Spine 任务 [%s] 版本未知，标记跳过",
                sanitize_log_text(job.cache_key, max_length=120),
            )
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
                logger.error("保存 Spine 预渲染缓存失败: %s", safe_exception_message(exc))

        if job.callback:
            job.callback(result)
