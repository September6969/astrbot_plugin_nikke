# SPDX-License-Identifier: GPL-3.0-or-later
"""单人突袭伤害估算：调用 NikkeHub 明确采用的 MIT 开源引擎。

上游：https://github.com/Jgaram/nikke-calc
固定基线：``67835ca3033a95482749ea2db35a8ee2a0856a92``（2026-11-02，MIT）。
NikkeHub 在 https://nikkehub.com/zh-tw/about 说明其单人突袭估伤使用该引擎的修正版。

本模块**不内置引擎代码或游戏数据**：运营者需把该 commit 的本地检出放到
``data/nikke/nikke-calc``（或配置 ``solo_raid_engine_path``），并提供角色名称映射
``data/nikke/solo-raid-engine-names.json``。缺失时明确返回“无法估伤”，绝不使用猜测公式。

进程树生命周期保障范围：
- Linux / POSIX：以 ``start_new_session=True`` 创建独立进程组 ``pgid=proc.pid``；无论直接父进程是否
  先退出（即使 ``returncode`` 已非 ``None``），回收阶段一律先对整组发送 ``SIGTERM``，轮询确认
  进程组清空并在超时后升级 ``SIGKILL``（注意：若子进程自行再次 ``setsid()`` 脱离进程组，POSIX
  无 root 权限或非 subreaper 下无法继续追踪该孙进程）。
- Windows：为每次调用创建带 ``JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`` 的 Win32 Job Object 并将
  直接子进程加入其中（除非子进程以 ``CREATE_BREAKAWAY_FROM_JOB`` 逃逸），清理阶段调用
  ``TerminateJobObject``、查询 ``JobObjectBasicProcessIdList`` 确认无残留 PID 后关闭句柄，并
  在 Job 不可用时回退 ``taskkill /F /T``。
"""

from __future__ import annotations

import asyncio
import contextlib
import ctypes
import json
import os
import re
import signal
import subprocess
import sys
import time
import weakref
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import urlparse

ENGINE_REPO = "Jgaram/nikke-calc"
PINNED_COMMIT = "67835ca3033a95482749ea2db35a8ee2a0856a92"
ENGINE_SOURCE_URL = f"https://github.com/{ENGINE_REPO}/tree/{PINNED_COMMIT}"
ENGINE_PAGE_URL = "https://nikkehub.com/zh-tw/about"
LICENSE = "MIT"
MAX_OUTPUT_BYTES = 256 * 1024
DEFAULT_BATCH_TIMEOUT = 180.0
DEFAULT_CLEANUP_TIMEOUT = 3.0
DEFAULT_PIPE_DRAIN_TIMEOUT = 0.25

VERSION_TRUST_GIT_PINNED = "git_verified_pinned"
VERSION_TRUST_SELF_REPORTED = "self_reported_unverified"
VERSION_TRUST_UNVERIFIED = "unverified"
VERSION_TRUST_MISMATCH_OR_DIRTY = "mismatch_or_dirty"

_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_ENV_ALLOWLIST = (
    "PATH",
    "SYSTEMROOT",
    "WINDIR",
    "COMSPEC",
    "PATHEXT",
    "TEMP",
    "TMP",
    "TMPDIR",
    "HOME",
    "USERPROFILE",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
)
ELEMENT_CODES = {
    "燃烧": "작열", "风压": "풍압", "铁甲": "철갑", "电击": "전격", "水冷": "수냉",
    "Fire": "작열", "Wind": "풍압", "Iron": "철갑", "Electric": "전격", "Electronic": "전격", "Water": "수냉",
}


class EngineNameMappingError(ValueError):
    """角色名称映射文件不符合合同。"""


class _OutputLimitExceeded(RuntimeError):
    """外部引擎流输出超过允许上限。"""


@dataclass(frozen=True, slots=True)
class EngineTeamEstimate:
    index: int
    damage: int | None
    error: str = ""
    commit: str = ""
    dirty: bool | None = None
    cleanup_error: str = ""


@dataclass(frozen=True, slots=True)
class EngineEstimate:
    available: bool
    teams: tuple[EngineTeamEstimate, ...] = ()
    total: int | None = None
    commit: str = ""
    dirty: bool | None = None
    label: str = ""
    note: str = ""
    reason: str = ""
    version_trust: str = VERSION_TRUST_UNVERIFIED
    cleanup_failures: tuple[str, ...] = ()

    @property
    def version_ok(self) -> bool:
        """仅当由独立 .git 核验为固定 clean commit 时才返回 True；自报版本绝不视为 True。"""
        return self.version_trust == VERSION_TRUST_GIT_PINNED


@dataclass(slots=True, eq=False)
class _ManagedProcess:
    proc: asyncio.subprocess.Process
    pid: int
    pgid: int
    job_handle: int | None = None
    cleaned: bool = False
    cleanup_error: str = ""


def _minimal_env() -> dict[str, str]:
    """只向外部引擎传递最小运行环境变量，剥离插件密钥与凭据。"""
    env = {
        key: value
        for key in _ENV_ALLOWLIST
        if (value := os.environ.get(key)) is not None
    }
    env.update(
        {
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
            "PYTHONNOUSERSITE": "1",
        }
    )
    return env


def _win32_create_job_and_assign(pid: int) -> int | None:
    """Windows 下创建 KILL_ON_JOB_CLOSE Job Object 并绑定进程。"""
    if os.name != "nt" or pid <= 0:
        return None
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    class _IO_COUNTERS(ctypes.Structure):
        _fields_ = [(name, ctypes.c_uint64) for name in (
            "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
            "ReadTransferCount", "WriteTransferCount", "OtherTransferCount",
        )]

    class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _JOBOBJECT_BASIC_LIMIT_INFORMATION),
            ("IoInfo", _IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        return None
    info = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    info.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not kernel32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)):
        kernel32.CloseHandle(job)
        return None
    proc_handle = kernel32.OpenProcess(0x0100 | 0x0001 | 0x1000, False, pid)
    if not proc_handle:
        kernel32.CloseHandle(job)
        return None
    try:
        if not kernel32.AssignProcessToJobObject(job, proc_handle):
            kernel32.CloseHandle(job)
            return None
    finally:
        kernel32.CloseHandle(proc_handle)
    return int(job)


def _win32_job_pids(job_handle: int) -> list[int]:
    """查询 Windows Job Object 中仍在活跃的真实 PID 列表。"""
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    class _JOBOBJECT_BASIC_PROCESS_ID_LIST(ctypes.Structure):
        _fields_ = [
            ("NumberOfAssignedProcesses", wintypes.DWORD),
            ("NumberOfProcessIdsInList", wintypes.DWORD),
            ("ProcessIdList", ctypes.c_size_t * 256),
        ]

    buf = _JOBOBJECT_BASIC_PROCESS_ID_LIST()
    ret_len = wintypes.DWORD(0)
    ok = kernel32.QueryInformationJobObject(
        wintypes.HANDLE(job_handle),
        3,  # JobObjectBasicProcessIdList
        ctypes.byref(buf),
        ctypes.sizeof(buf),
        ctypes.byref(ret_len),
    )
    if not ok:
        return []
    count = min(int(buf.NumberOfProcessIdsInList), 256)
    return [int(buf.ProcessIdList[i]) for i in range(count) if int(buf.ProcessIdList[i]) > 0]


def _win32_pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.OpenProcess(0x1000, False, pid)
    if not handle:
        return False
    try:
        code = ctypes.c_uint32(0)
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return False
        return int(code.value) == 259  # STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def _kill_managed_tree_sync(
    pid: int,
    pgid: int,
    job_handle: int | None,
    timeout: float,
) -> tuple[bool, str]:
    """独立于直接子进程 returncode 终止并验证整棵进程树已退出。"""
    deadline = time.monotonic() + max(0.2, timeout)
    if os.name == "nt":
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        err_msg = ""
        if job_handle is not None:
            try:
                if not kernel32.TerminateJobObject(wintypes.HANDLE(job_handle), 1):
                    err_msg = f"TerminateJobObject 失败（winerr={ctypes.get_last_error()}）"
                while time.monotonic() < deadline:
                    pids = _win32_job_pids(job_handle)
                    if not pids:
                        break
                    time.sleep(0.03)
                remaining = _win32_job_pids(job_handle)
                if remaining:
                    err_msg = f"进程树终止超时，仍有存活 PID: {remaining}"
            finally:
                kernel32.CloseHandle(wintypes.HANDLE(job_handle))
            if err_msg:
                return False, err_msg
            return True, ""

        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=_minimal_env(),
                timeout=max(0.5, timeout),
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return False, f"taskkill 执行失败（{type(exc).__name__}）"
        while time.monotonic() < deadline and _win32_pid_alive(pid):
            time.sleep(0.03)
        if _win32_pid_alive(pid):
            return False, f"PID {pid} 在 taskkill 后仍存活"
        return True, ""

    # POSIX: 使用独立进程组 pgid 清理整棵进程树（先 SIGTERM，超时后 SIGKILL）。
    target_pgid = pgid if pgid > 0 else pid
    if target_pgid <= 0:
        return True, ""
    try:
        os.killpg(target_pgid, 0)
    except ProcessLookupError:
        return True, ""
    except PermissionError as exc:
        return False, f"无权探测进程组 {target_pgid}（{type(exc).__name__}）"

    sigterm_deadline = min(deadline, time.monotonic() + min(0.4, max(0.1, timeout * 0.25)))
    try:
        os.killpg(target_pgid, signal.SIGTERM)
    except ProcessLookupError:
        return True, ""
    except OSError as exc:
        return False, f"SIGTERM 发送失败（{type(exc).__name__}）"

    while time.monotonic() < sigterm_deadline:
        try:
            os.killpg(target_pgid, 0)
        except ProcessLookupError:
            return True, ""
        except OSError:
            break
        time.sleep(0.025)

    try:
        os.killpg(target_pgid, signal.SIGKILL)
    except ProcessLookupError:
        return True, ""
    except OSError as exc:
        return False, f"SIGKILL 发送失败（{type(exc).__name__}）"

    while time.monotonic() < deadline:
        try:
            os.killpg(target_pgid, 0)
        except ProcessLookupError:
            return True, ""
        except OSError as exc:
            return False, f"进程组状态确认失败（{type(exc).__name__}）"
        time.sleep(0.025)
    return False, f"进程组 {target_pgid} 在 {timeout:.2f}s 内未全部退出"


async def _run_uninterruptible(coro_factory: Callable[[], Any]) -> Any:
    """屏蔽连续外部 CancelledError 直到清理动作完全结束，并在结束后再重新抛出取消异常。"""
    task = asyncio.ensure_future(coro_factory())
    cancelled = False
    while not task.done():
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
    try:
        result = task.result()
    finally:
        if cancelled:
            raise asyncio.CancelledError
    return result


async def _read_stream_bounded(
    stream: asyncio.StreamReader | None,
    limit: int,
    stream_name: str,
    buffer: bytearray | None = None,
) -> bytes:
    """运行期间流式读取并强制限制字节上限，超限立刻中止读取；已读字节写入 buffer。"""
    if stream is None:
        return b""
    buf = buffer if buffer is not None else bytearray()
    total = 0
    while True:
        chunk = await stream.read(min(65536, limit + 1))
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise _OutputLimitExceeded(f"{stream_name} 超过 {limit} 字节上限")
        buf.extend(chunk)
    return bytes(buf)


def _inspect_git_repo(engine_path: Path) -> tuple[bool, str, bool | None, str]:
    """当目录为独立 Git 检出时，核验真实 commit 与干净状态。"""
    if not (engine_path / ".git").exists():
        return False, "", None, ""
    env = _minimal_env()
    try:
        head = subprocess.run(
            ["git", "-C", str(engine_path), "rev-parse", "HEAD"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=5.0,
            check=False,
        )
        status = subprocess.run(
            ["git", "-C", str(engine_path), "status", "--porcelain"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=5.0,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return True, "", None, f"无法核验 nikke-calc Git 版本（{type(exc).__name__}）"
    if head.returncode != 0 or status.returncode != 0:
        return True, "", None, "无法核验 nikke-calc Git 仓库状态"
    commit = head.stdout.strip().casefold()
    if not _COMMIT_RE.fullmatch(commit):
        return True, "", None, "nikke-calc Git HEAD 不是合法 40 位 SHA"
    dirty = bool(status.stdout.strip())
    return True, commit, dirty, ""


def load_name_mapping_with_meta(path: str | Path) -> tuple[dict[str, str], str]:
    """读取“本地角色名/name_code → 引擎官方名”映射及声明的 engine_commit。"""
    target = Path(path)
    if not target.is_file():
        raise EngineNameMappingError(f"未找到角色名称映射：{target.name}")
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except OSError as exc:
        raise EngineNameMappingError(f"名称映射无法读取：{target.name}") from exc
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise EngineNameMappingError("名称映射不是合法 UTF-8 JSON") from exc
    if not isinstance(payload, Mapping) or payload.get("schema_version") != 1:
        raise EngineNameMappingError("名称映射 schema_version 必须为 1")
    if payload.get("engine_repo") != ENGINE_REPO:
        raise EngineNameMappingError(f"名称映射必须声明 engine_repo={ENGINE_REPO}")
    commit = str(payload.get("engine_commit") or "").strip().casefold()
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise EngineNameMappingError("名称映射 engine_commit 必须是 40 位小写 SHA")
    source = str(payload.get("source_url") or "")
    parsed = urlparse(source)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise EngineNameMappingError("名称映射 source_url 必须是无凭据 HTTPS")
    names = payload.get("names")
    if not isinstance(names, Mapping) or not names:
        raise EngineNameMappingError("名称映射 names 必须是非空对象")
    result: dict[str, str] = {}
    for local, official in names.items():
        if not isinstance(local, str) or not local.strip() or not isinstance(official, str) or not official.strip():
            raise EngineNameMappingError("名称映射的键和值都必须是非空字符串")
        result[local.strip()] = official.strip()
    return result, commit


def load_name_mapping(path: str | Path) -> dict[str, str]:
    """读取“本地角色名/name_code → 引擎官方名”映射；不内置任何游戏名称表。"""
    mapping, _ = load_name_mapping_with_meta(path)
    return mapping


class SoloRaidDamageEngine:
    """以原生异步子进程调用外部引擎，并严格绑定信号量与进程树回收生命周期。"""

    def __init__(
        self,
        engine_path: str | Path,
        mapping: Mapping[str, str],
        *,
        python: str | None = None,
        timeout: float = 90.0,
        batch_timeout: float | None = None,
        cleanup_timeout: float = DEFAULT_CLEANUP_TIMEOUT,
        pipe_drain_timeout: float = DEFAULT_PIPE_DRAIN_TIMEOUT,
        concurrency: int = 2,
        mapping_error: str = "",
        mapping_commit: str = "",
        work_dir: str | Path | None = None,
        allow_unverified: bool = False,
        require_git: bool = False,
        _tree_killer: Callable[[int, int, int | None, float], tuple[bool, str]] | None = None,
    ) -> None:
        self.engine_path = Path(engine_path)
        self.mapping = dict(mapping)
        self.python = python or sys.executable
        self.timeout = float(timeout)
        self.batch_timeout = (
            float(batch_timeout)
            if batch_timeout is not None
            else min(DEFAULT_BATCH_TIMEOUT, max(self.timeout, self.timeout * 2.0))
        )
        self.cleanup_timeout = max(0.2, float(cleanup_timeout))
        self.pipe_drain_timeout = max(0.05, float(pipe_drain_timeout))
        self.concurrency = max(1, min(int(concurrency), 5))
        self.mapping_error = mapping_error
        self.mapping_commit = str(mapping_commit or "").strip().casefold()
        self.work_dir = Path(work_dir) if work_dir else self.engine_path.parent / ".nikke-calc-runs"
        self.allow_unverified = bool(allow_unverified)
        self.require_git = bool(require_git)
        self._tree_killer = _tree_killer or _kill_managed_tree_sync
        self._semaphores: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore] = (
            weakref.WeakKeyDictionary()
        )
        self._active_handles: set[_ManagedProcess] = set()
        self._cleanup_failures: list[str] = []
        self._spawning = 0
        self._spawning_idle: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Event] = (
            weakref.WeakKeyDictionary()
        )
        self._closed = False

    def _semaphore(self) -> asyncio.Semaphore:
        loop = asyncio.get_running_loop()
        sem = self._semaphores.get(loop)
        if sem is None:
            sem = asyncio.Semaphore(self.concurrency)
            self._semaphores[loop] = sem
        return sem

    def _spawn_idle_event(self) -> asyncio.Event:
        loop = asyncio.get_running_loop()
        ev = self._spawning_idle.get(loop)
        if ev is None:
            ev = asyncio.Event()
            if self._spawning == 0:
                ev.set()
            self._spawning_idle[loop] = ev
        return ev

    @property
    def active_process_count(self) -> int:
        return sum(1 for item in self._active_handles if not item.cleaned)

    @property
    def cleanup_failures(self) -> tuple[str, ...]:
        return tuple(self._cleanup_failures)

    async def _cleanup_managed(self, managed: _ManagedProcess) -> str:
        """无论直接父进程是否已退出，均强制终止整棵进程树并关闭管道/句柄。"""
        if managed.cleaned:
            return managed.cleanup_error
        try:
            ok, err = await asyncio.to_thread(
                self._tree_killer,
                managed.pid,
                managed.pgid,
                managed.job_handle,
                self.cleanup_timeout,
            )
            managed.job_handle = None
            if not ok:
                managed.cleanup_error = err or f"PID {managed.pid} 进程树清理未确认成功"
                self._cleanup_failures.append(managed.cleanup_error)
            if managed.proc.returncode is None:
                with contextlib.suppress(ProcessLookupError, OSError):
                    managed.proc.kill()
            try:
                await asyncio.wait_for(managed.proc.wait(), timeout=1.0)
            except (asyncio.TimeoutError, OSError) as exc:
                extra = f"父进程回收失败（{type(exc).__name__}）"
                managed.cleanup_error = f"{managed.cleanup_error}; {extra}".strip("; ")
                if not ok:
                    self._cleanup_failures[-1] = managed.cleanup_error
                else:
                    self._cleanup_failures.append(managed.cleanup_error)
            transport = getattr(managed.proc, "_transport", None)
            if transport is not None:
                with contextlib.suppress(Exception):
                    transport.close()
        finally:
            managed.cleaned = True
            self._active_handles.discard(managed)
        return managed.cleanup_error

    async def aclose(self) -> None:
        """插件关闭或清理阶段先阻断新创建、等待在途 spawn 注册完成，再强杀全部活动进程树。"""
        self._closed = True
        if self._spawning > 0:
            ev = self._spawn_idle_event()
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(ev.wait(), timeout=self.cleanup_timeout)
        handles = list(self._active_handles)
        if handles:
            await asyncio.gather(
                *(self._cleanup_managed(item) for item in handles),
                return_exceptions=True,
            )

    @property
    def available(self) -> bool:
        return self.engine_path.is_dir() and (self.engine_path / "runner" / "sim.py").is_file() and bool(self.mapping)

    def reason(self) -> str:
        if self._closed:
            return "外部 nikke-calc 引擎已关闭"
        if not self.engine_path.is_dir():
            return f"未找到本地 nikke-calc 引擎目录：{self.engine_path}"
        if not (self.engine_path / "runner" / "sim.py").is_file():
            return "本地引擎缺少 runner/sim.py"
        if not self.mapping:
            return self.mapping_error or "缺少角色名称映射（data/nikke/solo-raid-engine-names.json）"
        return "引擎可用"

    def _engine_name(self, member: Any) -> str | None:
        for key in (
            str(getattr(member, "name_code", "") or "").strip(),
            str(getattr(member, "resource_id", "") or "").strip(),
            str(getattr(member, "name", "") or "").strip(),
        ):
            if key and key in self.mapping:
                return self.mapping[key]
        return None

    def _request(self, team: Any, boss_element: str) -> dict[str, Any]:
        squad = [self._engine_name(member) for member in getattr(team, "members", ())]
        if any(name is None for name in squad):
            raise EngineNameMappingError("队伍中有成员缺少引擎官方名映射")
        request: dict[str, Any] = {
            "squad": squad,
            "sim": {"duration": 180, "expected": True, "seed": 0},
        }
        code = ELEMENT_CODES.get(str(boss_element or "").strip())
        if code:
            request["enemy"] = {"code": code}
        return request

    async def _run_team_subprocess(self, team: Any, boss_element: str) -> EngineTeamEstimate:
        """运行单队子进程；信号量在其外层持有直到整棵进程树与读取任务完全回收。"""
        index = int(getattr(team, "index", 0) or 0)
        if self._closed:
            return EngineTeamEstimate(index, None, "引擎已关闭")
        if len(getattr(team, "members", ())) != 5:
            return EngineTeamEstimate(index, None, "队伍不足五人，未调用引擎")
        if not getattr(team, "chain_ok", False):
            return EngineTeamEstimate(index, None, "爆裂链不完整，未调用引擎")
        try:
            request = self._request(team, boss_element)
        except EngineNameMappingError as exc:
            return EngineTeamEstimate(index, None, str(exc))

        env = _minimal_env()
        popen_kwargs: dict[str, Any] = {}
        if os.name == "nt":
            popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            popen_kwargs["start_new_session"] = True

        managed: _ManagedProcess | None = None
        stdout_task: asyncio.Task[bytes] | None = None
        stderr_task: asyncio.Task[bytes] | None = None
        wait_task: asyncio.Task[int] | None = None
        cleanup_err = ""
        try:
            self._spawning += 1
            self._spawn_idle_event().clear()
            try:
                if self._closed:
                    return EngineTeamEstimate(index, None, "引擎已关闭")
                proc = await asyncio.create_subprocess_exec(
                    self.python,
                    "-m",
                    "runner.sim",
                    "--request",
                    json.dumps(request, ensure_ascii=False),
                    "--json",
                    cwd=str(self.engine_path),
                    env=env,
                    stdin=asyncio.subprocess.DEVNULL,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    **popen_kwargs,
                )
                job = _win32_create_job_and_assign(proc.pid) if os.name == "nt" else None
                managed = _ManagedProcess(proc=proc, pid=proc.pid, pgid=proc.pid, job_handle=job)
                self._active_handles.add(managed)
            finally:
                self._spawning -= 1
                if self._spawning == 0:
                    self._spawn_idle_event().set()

            if self._closed:
                cleanup_err = await _run_uninterruptible(lambda: self._cleanup_managed(managed))
                return EngineTeamEstimate(index, None, "引擎已关闭", cleanup_error=cleanup_err)

            stdout_buf = bytearray()
            stderr_buf = bytearray()
            stdout_task = asyncio.ensure_future(
                _read_stream_bounded(proc.stdout, MAX_OUTPUT_BYTES, "stdout", stdout_buf)
            )
            stderr_task = asyncio.ensure_future(
                _read_stream_bounded(proc.stderr, MAX_OUTPUT_BYTES, "stderr", stderr_buf)
            )
            wait_task = asyncio.ensure_future(proc.wait())

            # 同时监听直接父进程退出与受限流读取，防止继承管道的后代进程阻塞等待。
            async def _collect_with_descendant_guard() -> tuple[bytes, bytes, int, bool]:
                readers_done_before_kill = True
                returncode = await wait_task
                pending_readers = [t for t in (stdout_task, stderr_task) if not t.done()]
                if pending_readers:
                    _, still_open = await asyncio.wait(
                        pending_readers, timeout=self.pipe_drain_timeout
                    )
                    if still_open:
                        readers_done_before_kill = False
                        # 存在继承了 stdout/stderr 的残留派生进程：立即强杀进程树，再短等管道 EOF。
                        await _run_uninterruptible(lambda: self._cleanup_managed(managed))
                        _, still_stuck = await asyncio.wait(still_open, timeout=0.2)
                        for t in still_stuck:
                            t.cancel()
                        if still_stuck:
                            await asyncio.gather(*still_stuck, return_exceptions=True)
                for t in (stdout_task, stderr_task):
                    if not t.done():
                        t.cancel()
                        await asyncio.gather(t, return_exceptions=True)
                out_bytes = bytes(stdout_buf) if stdout_task.cancelled() else stdout_task.result()
                err_bytes = bytes(stderr_buf) if stderr_task.cancelled() else stderr_task.result()
                return out_bytes, err_bytes, returncode, readers_done_before_kill

            # 若任一 reader 先于 proc.wait() 抛出异常（如输出超限），立刻感知而不是等到超时。
            async def _drive() -> tuple[bytes, bytes, int, bool]:
                collector = asyncio.ensure_future(_collect_with_descendant_guard())
                done, _ = await asyncio.wait(
                    [collector, stdout_task, stderr_task],
                    return_when=asyncio.FIRST_EXCEPTION,
                )
                for t in done:
                    if t is not collector and not t.cancelled() and t.exception() is not None:
                        collector.cancel()
                        await asyncio.gather(collector, return_exceptions=True)
                        raise t.exception()  # type: ignore[misc]
                return await collector

            stdout_bytes, stderr_bytes, returncode, _ = await asyncio.wait_for(
                _drive(), timeout=self.timeout
            )
        except _OutputLimitExceeded:
            return EngineTeamEstimate(index, None, "引擎输出超过大小上限")
        except asyncio.TimeoutError:
            return EngineTeamEstimate(index, None, "引擎计算超时")
        except OSError as exc:
            return EngineTeamEstimate(index, None, f"引擎无法启动（{type(exc).__name__}）")
        finally:
            async def _final_reap() -> str:
                pending_inner = [t for t in (wait_task, stdout_task, stderr_task) if t is not None and not t.done()]
                for t in pending_inner:
                    t.cancel()
                err = ""
                if managed is not None:
                    err = await self._cleanup_managed(managed)
                if pending_inner:
                    await asyncio.gather(*pending_inner, return_exceptions=True)
                return err

            cleanup_err = await _run_uninterruptible(_final_reap)

        text = stdout_bytes.decode("utf-8", errors="replace").strip()
        if returncode != 0:
            detail = _engine_error(text) or stderr_bytes.decode("utf-8", errors="replace").strip()[:200]
            return EngineTeamEstimate(
                index, None, detail or "引擎返回非零状态", cleanup_error=cleanup_err
            )
        lines = [line for line in text.splitlines() if line.strip()]
        if not lines:
            return EngineTeamEstimate(index, None, "引擎输出不是 JSON", cleanup_error=cleanup_err)
        try:
            payload = json.loads(lines[-1])
        except ValueError:
            return EngineTeamEstimate(index, None, "引擎输出不是 JSON", cleanup_error=cleanup_err)
        if not isinstance(payload, Mapping):
            return EngineTeamEstimate(index, None, "引擎输出不是 JSON 对象", cleanup_error=cleanup_err)
        error_obj = payload.get("error")
        if isinstance(error_obj, Mapping):
            return EngineTeamEstimate(
                index, None, str(error_obj.get("message") or "引擎输入错误"), cleanup_error=cleanup_err
            )
        if error_obj not in (None, "", False):
            return EngineTeamEstimate(index, None, "引擎返回异常错误字段", cleanup_error=cleanup_err)
        damage = payload.get("total_damage")
        if isinstance(damage, bool) or not isinstance(damage, int) or damage < 0:
            return EngineTeamEstimate(
                index, None, "引擎结果缺少有效 total_damage", cleanup_error=cleanup_err
            )
        evaluator = payload.get("evaluator") if isinstance(payload.get("evaluator"), Mapping) else {}
        commit = str(evaluator.get("commit") or "").strip().casefold()
        if not _COMMIT_RE.fullmatch(commit):
            commit = ""
        dirty = evaluator.get("dirty") if isinstance(evaluator.get("dirty"), bool) else None
        return EngineTeamEstimate(
            index,
            damage,
            cleanup_err and f"进程树清理异常：{cleanup_err}",
            commit,
            dirty,
            cleanup_error=cleanup_err,
        )

    async def estimate(self, teams: Sequence[Any], *, boss_element: str = "") -> EngineEstimate:
        """逐队估算；任一步失败都明确记录，不把未知或自报版本当成可信固定基线。"""
        if self._closed:
            return EngineEstimate(False, reason="外部 nikke-calc 引擎已关闭")
        if not self.available:
            return EngineEstimate(False, reason=self.reason())

        has_git, git_commit, git_dirty, git_err = await asyncio.to_thread(
            _inspect_git_repo, self.engine_path
        )
        if self.require_git and not has_git:
            return EngineEstimate(
                False,
                version_trust=VERSION_TRUST_UNVERIFIED,
                reason="外部 nikke-calc 缺少独立 Git 仓库，无法核验固定基线版本。",
            )
        if has_git:
            if git_err:
                return EngineEstimate(
                    False,
                    commit=git_commit,
                    dirty=git_dirty,
                    version_trust=VERSION_TRUST_UNVERIFIED,
                    reason=git_err,
                )
            mapping_mismatch = bool(self.mapping_commit and git_commit != self.mapping_commit)
            if not self.allow_unverified and (
                git_commit != PINNED_COMMIT or git_dirty is not False or mapping_mismatch
            ):
                extra = (
                    f"，名称映射声明={self.mapping_commit[:10]}"
                    if mapping_mismatch
                    else ""
                )
                return EngineEstimate(
                    False,
                    commit=git_commit,
                    dirty=git_dirty,
                    version_trust=VERSION_TRUST_MISMATCH_OR_DIRTY,
                    reason=(
                        f"外部 nikke-calc 版本校验失败（commit={git_commit[:10] or '未知'}, "
                        f"dirty={git_dirty}，要求 {PINNED_COMMIT[:10]} 且工作区干净{extra}）。"
                    ),
                )

        semaphore = self._semaphore()

        async def limited(team: Any) -> EngineTeamEstimate:
            # 信号量必须持续到 _run_team_subprocess 的 finally（含进程树强杀与验证）全部完成。
            async with semaphore:
                return await self._run_team_subprocess(team, boss_element)

        if not teams:
            results: tuple[EngineTeamEstimate, ...] = ()
        else:
            batch_tasks: list[asyncio.Task[EngineTeamEstimate]] = []
            try:
                async with asyncio.timeout(self.batch_timeout):
                    async with asyncio.TaskGroup() as tg:
                        batch_tasks = [tg.create_task(limited(team)) for team in teams]
                results = tuple(task.result() for task in batch_tasks)
            except TimeoutError:
                failures = tuple(
                    f for f in self._cleanup_failures if f
                )
                return EngineEstimate(
                    False,
                    commit=git_commit if has_git else "",
                    dirty=git_dirty if has_git else None,
                    version_trust=(
                        VERSION_TRUST_MISMATCH_OR_DIRTY
                        if has_git and (git_commit != PINNED_COMMIT or git_dirty is not False)
                        else VERSION_TRUST_UNVERIFIED
                    ),
                    cleanup_failures=failures,
                    reason=(
                        "外部 nikke-calc 批次计算超时，已中止本轮估算。"
                        + (f"（清理告警：{'；'.join(failures)}）" if failures else "")
                    ),
                )

        successes = [item for item in results if item.damage is not None and not item.cleanup_error]
        team_cleanup_failures = tuple(item.cleanup_error for item in results if item.cleanup_error)

        if has_git:
            commit = git_commit
            dirty = git_dirty
            reported_commits = {item.commit for item in successes if item.commit}
            reported_mismatch = bool(reported_commits and reported_commits != {git_commit})
            mapping_mismatch = bool(self.mapping_commit and git_commit != self.mapping_commit)
            if git_commit == PINNED_COMMIT and git_dirty is False and not reported_mismatch and not mapping_mismatch:
                version_trust = VERSION_TRUST_GIT_PINNED
            else:
                version_trust = VERSION_TRUST_MISMATCH_OR_DIRTY
        else:
            commits = {item.commit for item in results if item.commit}
            commit = next(iter(commits)) if len(commits) == 1 else ""
            dirty_values = [item.dirty for item in results if item.dirty is not None]
            if any(value is True for value in dirty_values):
                dirty = True
            elif len(results) > 0 and len(dirty_values) == len(results) and all(v is False for v in dirty_values):
                dirty = False
            else:
                dirty = None
            if not commit:
                version_trust = VERSION_TRUST_UNVERIFIED
            elif dirty is True or (self.mapping_commit and commit != self.mapping_commit) or commit != PINNED_COMMIT:
                version_trust = VERSION_TRUST_MISMATCH_OR_DIRTY
            elif dirty is False:
                version_trust = VERSION_TRUST_SELF_REPORTED
            else:
                version_trust = VERSION_TRUST_UNVERIFIED

        if version_trust == VERSION_TRUST_GIT_PINNED:
            label = f"nikke-calc {commit[:10]}（{LICENSE}，Git 核验固定基线）"
            version_note = ""
        elif version_trust == VERSION_TRUST_SELF_REPORTED:
            label = f"nikke-calc {commit[:10]}（{LICENSE}，引擎自报·未核验仓库）"
            version_note = "（缺少独立 Git 核验，仅为引擎自报版本，不适合可信基线对比）"
        elif version_trust == VERSION_TRUST_MISMATCH_OR_DIRTY:
            label = f"nikke-calc {commit[:10] if commit else '未知'}（{LICENSE}，版本不一致或工作区存在修改）"
            version_note = "（版本与固定基线不一致或存在未提交改动，结果不适合可信基线对比）"
        else:
            label = f"nikke-calc 未核验版本（{LICENSE}，非可信固定基线）"
            version_note = "（未完成版本核验，结果不适合可信基线对比）"

        total = (
            sum(item.damage for item in successes if item.damage is not None)
            if len(successes) == len(results) and results
            else None
        )
        errors = [f"第 {item.index} 队：{item.error}" for item in results if item.error]
        pinned = f"{ENGINE_REPO}@{PINNED_COMMIT}"
        actual = f"{ENGINE_REPO}@{commit}" if commit else f"{ENGINE_REPO}@unverified"
        note = (
            f"由外部 {actual}（{LICENSE}）{version_note}计算；"
            f"使用引擎默认敌人与已知赛季属性（基准 {pinned}），未提供官方防御/HP 精确参数，因此不是官方伤害数值。"
        )
        if errors:
            note += " 部分队伍无法估伤：" + "；".join(errors)
        return EngineEstimate(
            True,
            teams=results,
            total=total,
            commit=commit,
            dirty=dirty,
            label=label,
            note=note,
            version_trust=version_trust,
            cleanup_failures=team_cleanup_failures,
        )


def _engine_error(text: str) -> str:
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return ""
    try:
        payload = json.loads(lines[-1])
    except ValueError:
        return ""
    if not isinstance(payload, Mapping):
        return ""
    error = payload.get("error")
    if isinstance(error, Mapping):
        return str(error.get("message") or error.get("type") or "")
    return ""


__all__ = [
    "DEFAULT_CLEANUP_TIMEOUT",
    "ENGINE_PAGE_URL",
    "ENGINE_REPO",
    "ENGINE_SOURCE_URL",
    "EngineEstimate",
    "EngineNameMappingError",
    "EngineTeamEstimate",
    "LICENSE",
    "MAX_OUTPUT_BYTES",
    "PINNED_COMMIT",
    "SoloRaidDamageEngine",
    "VERSION_TRUST_GIT_PINNED",
    "VERSION_TRUST_MISMATCH_OR_DIRTY",
    "VERSION_TRUST_SELF_REPORTED",
    "VERSION_TRUST_UNVERIFIED",
    "load_name_mapping",
    "load_name_mapping_with_meta",
]
