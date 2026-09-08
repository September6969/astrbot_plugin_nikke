# SPDX-License-Identifier: GPL-3.0-or-later
"""正式 Spine backend 编排与受控后台预渲染队列。

遵循 contracts/assets_spine.md 契约：
1. Spine 通过依赖注入接入，具体 runtime 由部署环境负责选择和授权，非出卡前置阻塞项；
2. 预渲染仅在受控后台队列异步执行，用户出卡绝不同步阻塞等待；
3. 严格匹配 major.minor 版本，未知版本标记 SPINE_VERSION_UNKNOWN，严禁盲猜默认 runtime；
4. 队列支持 per-key 去重、队列长度限制（默认最大20）、1~2 worker；
5. 插件关闭时支持优雅取消并回收。
"""

from __future__ import annotations

import logging
import math
import re
import queue
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Mapping, Protocol, Sequence

from urllib.parse import urlparse

import httpx

from PIL import Image

from .log_privacy import safe_exception_message, sanitize_log_text

logger = logging.getLogger("nikke.spine")


SPINE_VERSION_UNKNOWN = "SPINE_VERSION_UNKNOWN"


class SpineRenderError(RuntimeError):
    """Spine bundle 或 runtime 渲染失败。"""


@dataclass(frozen=True, slots=True)
class SpineBundle:
    """一个可供 runtime 消费的完整 Spine bundle。"""

    skeleton: Path
    atlas: Path
    textures: tuple[Path, ...]

    @classmethod
    def from_mapping(cls, paths: Mapping[str, object]) -> "SpineBundle":
        skeleton_value = paths.get("skel") or paths.get("skeleton")
        atlas_value = paths.get("atlas")
        texture_value = paths.get("png") or paths.get("texture") or paths.get("textures")
        if not isinstance(skeleton_value, (str, Path)) or not isinstance(atlas_value, (str, Path)):
            raise SpineRenderError("Spine bundle 缺少 skeleton 或 atlas")
        if isinstance(texture_value, (str, Path)):
            textures = (Path(texture_value),)
        elif isinstance(texture_value, Sequence) and not isinstance(texture_value, (str, bytes, bytearray)):
            if not all(isinstance(item, (str, Path)) for item in texture_value):
                raise SpineRenderError("Spine bundle 纹理页路径类型无效")
            textures = tuple(Path(item) for item in texture_value)
        else:
            textures = ()
        if not textures:
            raise SpineRenderError("Spine bundle 缺少纹理页")
        return cls(Path(skeleton_value), Path(atlas_value), textures)

    def all_files(self) -> tuple[Path, ...]:
        return (self.skeleton, self.atlas, *self.textures)


class SpineRuntimeBackend(Protocol):
    """正式 runtime 的最小适配合同；具体官方 runtime 由部署环境注入。"""

    version: str

    def render(
        self,
        bundle: SpineBundle,
        *,
        animation: str,
        skin: str | None = None,
    ) -> Image.Image:
        """加载 skeleton/atlas/texture 并返回透明 RGBA 图像。"""


class SpineBundleFetcher:
    """下载并缓存已允许的 Nikke-DB Spine bundle，不携带账号上下文。"""

    ALLOWED_HOST = "raw.githubusercontent.com"
    ALLOWED_PREFIX = "/Nikke-db/Nikke-db.github.io/main/l2d/"
    MAX_SKELETON_BYTES = 16 * 1024 * 1024
    MAX_ATLAS_BYTES = 4 * 1024 * 1024
    MAX_TEXTURE_BYTES = 12 * 1024 * 1024
    MAX_TOTAL_BYTES = 32 * 1024 * 1024

    def __init__(self, cache_dir: str | Path, *, timeout_seconds: float = 5.0):
        self.cache_dir = Path(cache_dir)
        self.timeout_seconds = timeout_seconds

    @classmethod
    def _validate_url(cls, url: object) -> str:
        if not isinstance(url, str):
            raise SpineRenderError("Spine bundle URL 类型无效")
        parsed = urlparse(url)
        if (
            parsed.scheme != "https"
            or parsed.hostname != cls.ALLOWED_HOST
            or not parsed.path.startswith(cls.ALLOWED_PREFIX)
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise SpineRenderError("Spine bundle URL 不在允许的公开资源范围")
        return url

    @staticmethod
    def _safe_key(cache_key: str) -> str:
        if not isinstance(cache_key, str) or not re.fullmatch(r"[a-zA-Z0-9_.-]{1,240}", cache_key):
            raise SpineRenderError("Spine cache key 含有非法路径字符")
        return cache_key

    @classmethod
    def _limit_for(cls, name: str) -> int:
        if name == "skel":
            return cls.MAX_SKELETON_BYTES
        if name == "atlas":
            return cls.MAX_ATLAS_BYTES
        if name == "png":
            return cls.MAX_TEXTURE_BYTES
        raise SpineRenderError(f"Spine bundle 文件类型不支持: {name}")

    def _target(self, cache_key: str, name: str, url: str) -> Path:
        suffix = Path(urlparse(url).path).suffix.lower()
        if suffix not in {".skel", ".json", ".atlas", ".png", ".webp"}:
            raise SpineRenderError("Spine bundle 文件后缀不受支持")
        target = self.cache_dir / self._safe_key(cache_key) / f"{name}{suffix}"
        root = self.cache_dir.resolve()
        if not target.resolve().is_relative_to(root):
            raise SpineRenderError("Spine bundle 缓存路径越界")
        return target

    def _valid_cached(self, path: Path, limit: int) -> bool:
        try:
            return path.is_file() and 0 < path.stat().st_size <= limit
        except OSError:
            return False

    def fetch(
        self,
        urls: Mapping[str, str],
        cache_key: str,
        *,
        budget_seconds: float | None = None,
    ) -> SpineBundle:
        started = time.monotonic()
        targets: dict[str, Path] = {}
        total_bytes = 0
        for name in ("skel", "atlas", "png"):
            url = self._validate_url(urls.get(name))
            target = self._target(cache_key, name, url)
            targets[name] = target
            if self._valid_cached(target, self._limit_for(name)):
                total_bytes += target.stat().st_size
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            limit = self._limit_for(name)
            content = bytearray()
            try:
                with httpx.stream("GET", url, timeout=self.timeout_seconds, follow_redirects=False) as response:
                    response.raise_for_status()
                    for chunk in response.iter_bytes():
                        content.extend(chunk)
                        if len(content) > limit or total_bytes + len(content) > self.MAX_TOTAL_BYTES:
                            raise SpineRenderError("Spine bundle 下载超过大小预算")
                        if budget_seconds is not None and time.monotonic() - started > budget_seconds:
                            raise SpineRenderError("Spine bundle 下载超过总预算")
            except (httpx.HTTPError, OSError) as exc:
                raise SpineRenderError(f"Spine bundle 下载失败: {type(exc).__name__}") from exc
            temporary = target.with_name(f".{target.name}.{threading.get_ident()}.tmp")
            try:
                temporary.write_bytes(bytes(content))
                temporary.replace(target)
            finally:
                temporary.unlink(missing_ok=True)
            total_bytes += len(content)
        return SpineBundle(targets["skel"], targets["atlas"], (targets["png"],))


@dataclass(slots=True)
class SpineJob:
    cache_key: str
    character_id: str
    runtime_version: str | float | None
    callback: Callable[[Image.Image | None], None] | None = None
    bundle: SpineBundle | None = None
    bundle_urls: Mapping[str, str] | None = None
    animation: str = "aim"
    skin: str | None = None
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
        if not isinstance(self.animation, str) or not self.animation.strip() or not re.fullmatch(r"[a-zA-Z0-9_.-]+", self.animation):
            raise ValueError("Spine animation 标识无效")
        if self.skin is not None and (not isinstance(self.skin, str) or not re.fullmatch(r"[a-zA-Z0-9_.-]+", self.skin)):
            raise ValueError("Spine skin 标识无效")
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
    """正式 Spine backend 的安全编排层。

    runtime 通过依赖注入提供；本模块负责 bundle、版本、预算、RGBA 输出、
    裁切、缓存和队列，不猜测或偷偷安装具体商业 runtime。
    """

    RENDERER_VERSION = "2.0"
    CROP_PADDING = 60
    MAX_PIXELS = 20_000_000

    def __init__(
        self,
        cache_dir: str | Path,
        *,
        runtime: SpineRuntimeBackend | None = None,
        fetcher: SpineBundleFetcher | None = None,
        max_workers: int = 1,
        max_queue_size: int = 20,
    ):
        self.cache_dir = Path(cache_dir)
        self.prerender_dir = self.cache_dir / "portraits"
        self.prerender_dir.mkdir(parents=True, exist_ok=True)
        self.runtime = runtime
        self.fetcher = fetcher or SpineBundleFetcher(self.cache_dir / "spine-bundles")
        self.queue = SpineTaskQueue(max_workers=max_workers, max_queue_size=max_queue_size)

    def start(self) -> None:
        """启动受控后台队列；不会同步等待或补发旧卡。"""
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
        from .scripts.inspect_spine_bundle import inspect

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

    def is_available(self, version: str | float | None = None) -> bool:
        """只有明确注入且版本兼容的 runtime 才算可用。"""
        if self.runtime is None:
            return False
        runtime_version = self._major_minor(getattr(self.runtime, "version", None))
        if runtime_version is None:
            return False
        return version is None or runtime_version == self._major_minor(version)

    @staticmethod
    def _major_minor(version: str | float | int | None) -> str | None:
        if isinstance(version, bool) or version is None:
            return None
        text = str(version).strip()
        match = re.fullmatch(r"(\d+)\.(\d+)(?:\.\d+)?", text)
        return f"{match.group(1)}.{match.group(2)}" if match else None

    def cached_portrait(self, cache_key: str) -> Image.Image | None:
        """读取并校验版本化 Spine PNG；损坏缓存不会阻断 FB fallback。"""
        path = self.prerender_dir / f"{SpineBundleFetcher._safe_key(cache_key)}.png"
        try:
            with Image.open(path) as image:
                if image.width * image.height > self.MAX_PIXELS:
                    return None
                image.load()
                return image.convert("RGBA")
        except (OSError, ValueError, Image.DecompressionBombError):
            return None

    def enqueue(self, job: SpineJob) -> bool:
        """按 key 去重并启动后台预渲染；不可用 runtime 时直接返回 False。"""
        if not self.is_available(job.runtime_version):
            return False
        self.start()
        return self.queue.enqueue(job)

    def _normalize_output(self, image: Image.Image) -> Image.Image:
        if not isinstance(image, Image.Image):
            raise SpineRenderError("Spine runtime 未返回 Pillow 图像")
        rgba = image.convert("RGBA")
        if rgba.width <= 0 or rgba.height <= 0 or rgba.width * rgba.height > self.MAX_PIXELS:
            raise SpineRenderError("Spine 输出尺寸无效或超限")
        bounds = rgba.getbbox()
        if bounds is None:
            raise SpineRenderError("Spine 输出没有可见像素")
        left, top, right, bottom = bounds
        return rgba.crop(
            (
                max(0, left - self.CROP_PADDING),
                max(0, top - self.CROP_PADDING),
                min(rgba.width, right + self.CROP_PADDING),
                min(rgba.height, bottom + self.CROP_PADDING),
            )
        )

    def render_full_body(
        self,
        bundle_paths: SpineBundle | Mapping[str, object],
        version: str | float | None,
        *,
        animation: str = "aim",
        skin: str | None = None,
    ) -> Image.Image | None:
        """严格匹配 runtime 并返回裁切后的透明 RGBA PNG 内容。

        没有明确 runtime、版本不匹配、bundle 不完整或渲染失败时返回 None，
        由 AssetManager 继续使用 FB/placeholder fallback。
        """
        expected_version = self._major_minor(version)
        if expected_version is None or version == SPINE_VERSION_UNKNOWN:
            logger.warning("Spine 版本未知，严禁猜测默认 runtime，返回 None")
            return None
        if self.runtime is None or not self.is_available(expected_version):
            logger.debug("当前环境没有版本匹配的 Spine runtime，跳过实时预渲染")
            return None

        try:
            bundle = bundle_paths if isinstance(bundle_paths, SpineBundle) else SpineBundle.from_mapping(bundle_paths)
            if not all(path.is_file() for path in bundle.all_files()):
                raise SpineRenderError("Spine bundle 文件不完整")
            from .scripts.inspect_spine_bundle import inspect

            inspection = inspect(bundle.atlas, bundle.skeleton, expected_version)
            # 二进制 skeleton 的版本无法由无 runtime 预检查确认；未知版本不能猜测
            # 4.1/4.2，只有明确得到 VERSION_MATCH 才允许调用实际 runtime。
            if inspection.get("status") != "VERSION_MATCH":
                raise SpineRenderError(f"Spine bundle 预检查失败: {inspection.get('status')}")
            if int(inspection.get("missing_pages", 0)) != 0:
                raise SpineRenderError("Spine bundle 缺少纹理页")
            result = self.runtime.render(bundle, animation=animation, skin=skin)
            return self._normalize_output(result)
        except (OSError, ValueError, TypeError, SpineRenderError) as exc:
            logger.warning("Spine render fallback: %s", safe_exception_message(exc))
            return None
        except Exception as exc:
            # 第三方 runtime 不能穿透后台任务线程或破坏角色卡主链。
            logger.warning("Spine runtime adapter fallback: %s", safe_exception_message(exc))
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

        bundle = job.bundle
        if bundle is None and job.bundle_urls:
            try:
                bundle = self.fetcher.fetch(job.bundle_urls, job.cache_key, budget_seconds=job.budget_seconds)
            except SpineRenderError as exc:
                logger.warning("Spine bundle fallback [%s]: %s", sanitize_log_text(job.cache_key, max_length=120), exc)
        result = self.render_full_body(bundle, job.runtime_version, animation=job.animation, skin=job.skin) if bundle else None
        if result is not None:
            output_path = self.prerender_dir / f"{job.cache_key}.png"
            try:
                temporary = output_path.with_name(f".{output_path.name}.{threading.get_ident()}.tmp")
                result.save(temporary, format="PNG")
                temporary.replace(output_path)
            except OSError as exc:
                logger.error("保存 Spine 预渲染缓存失败: %s", safe_exception_message(exc))
            finally:
                temporary.unlink(missing_ok=True)

        if job.callback:
            job.callback(result)
