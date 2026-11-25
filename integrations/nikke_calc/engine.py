# SPDX-License-Identifier: GPL-3.0-or-later
"""单人突袭伤害估算：调用 NikkeHub 明确采用的 MIT 开源引擎。

上游：https://github.com/Jgaram/nikke-calc
固定基线：``67835ca3033a95482749ea2db35a8ee2a0856a92``（2026-11-02，MIT）。
NikkeHub 在 https://nikkehub.com/zh-tw/about 说明其单人突袭估伤使用该引擎的修正版。

本模块**不内置引擎代码或游戏数据**：运营者需把该 commit 的本地检出放到
``data/nikke/nikke-calc``（或配置 ``solo_raid_engine_path``），并提供角色名称映射
``data/nikke/solo-raid-engine-names.json``。缺失时明确返回“无法估伤”，绝不使用猜测公式。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
import signal
import subprocess
import sys
import weakref
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import urlparse

ENGINE_REPO = "Jgaram/nikke-calc"
PINNED_COMMIT = "67835ca3033a95482749ea2db35a8ee2a0856a92"
ENGINE_SOURCE_URL = f"https://github.com/{ENGINE_REPO}/tree/{PINNED_COMMIT}"
ENGINE_PAGE_URL = "https://nikkehub.com/zh-tw/about"
LICENSE = "MIT"
MAX_OUTPUT_BYTES = 256 * 1024
DEFAULT_BATCH_TIMEOUT = 180.0
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

    @property
    def version_ok(self) -> bool:
        return self.commit == PINNED_COMMIT and self.dirty is False


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


def _kill_process_tree_sync(pid: int) -> None:
    """按进程组/进程树强制终止孤儿外部进程。"""
    if pid <= 0:
        return
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=_minimal_env(),
                timeout=3.0,
                check=False,
            )
        else:
            os.killpg(pid, signal.SIGKILL)
    except (OSError, subprocess.SubprocessError):
        pass


async def _terminate_async_process_tree(proc: asyncio.subprocess.Process) -> None:
    """不可打断地终止并回收外部子进程及其派生进程树。"""
    if proc.returncode is None:
        try:
            await asyncio.to_thread(_kill_process_tree_sync, proc.pid)
        except Exception:
            pass
        if proc.returncode is None:
            with contextlib.suppress(ProcessLookupError, OSError):
                proc.kill()
        with contextlib.suppress(asyncio.TimeoutError, OSError):
            await asyncio.wait_for(proc.wait(), timeout=3.0)


async def _read_stream_bounded(
    stream: asyncio.StreamReader | None,
    limit: int,
    stream_name: str,
) -> bytes:
    """运行期间流式读取并强制限制字节上限，超限立刻中止读取。"""
    if stream is None:
        return b""
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await stream.read(min(65536, limit + 1))
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise _OutputLimitExceeded(f"{stream_name} 超过 {limit} 字节上限")
        chunks.append(chunk)
    return b"".join(chunks)


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


def load_name_mapping(path: str | Path) -> dict[str, str]:
    """读取“本地角色名/name_code → 引擎官方名”映射；不内置任何游戏名称表。"""
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
    commit = str(payload.get("engine_commit") or "")
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
    return result


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
        concurrency: int = 2,
        mapping_error: str = "",
        work_dir: str | Path | None = None,
        allow_unverified: bool = False,
        require_git: bool = False,
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
        self.concurrency = max(1, min(int(concurrency), 5))
        self.mapping_error = mapping_error
        self.work_dir = Path(work_dir) if work_dir else self.engine_path.parent / ".nikke-calc-runs"
        self.allow_unverified = bool(allow_unverified)
        self.require_git = bool(require_git)
        self._semaphores: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore] = (
            weakref.WeakKeyDictionary()
        )
        self._active_procs: set[asyncio.subprocess.Process] = set()
        self._closed = False

    def _semaphore(self) -> asyncio.Semaphore:
        loop = asyncio.get_running_loop()
        sem = self._semaphores.get(loop)
        if sem is None:
            sem = asyncio.Semaphore(self.concurrency)
            self._semaphores[loop] = sem
        return sem

    @property
    def active_process_count(self) -> int:
        return sum(1 for proc in self._active_procs if proc.returncode is None)

    async def aclose(self) -> None:
        """插件关闭或清理阶段终止并回收全部仍在运行的外部估伤子进程。"""
        self._closed = True
        procs = list(self._active_procs)
        if procs:
            await asyncio.gather(
                *(_terminate_async_process_tree(proc) for proc in procs),
                return_exceptions=True,
            )
        self._active_procs.difference_update(proc for proc in procs if proc.returncode is not None)

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
        """运行单队子进程；必须在信号量持有期外层包覆本方法以便强杀完成后再释放并发槽位。"""
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

        proc: asyncio.subprocess.Process | None = None
        try:
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
            self._active_procs.add(proc)
            if self._closed:
                await asyncio.shield(_terminate_async_process_tree(proc))
                return EngineTeamEstimate(index, None, "引擎已关闭")

            async def _collect() -> tuple[bytes, bytes, int]:
                out_bytes, err_bytes = await asyncio.gather(
                    _read_stream_bounded(proc.stdout, MAX_OUTPUT_BYTES, "stdout"),
                    _read_stream_bounded(proc.stderr, MAX_OUTPUT_BYTES, "stderr"),
                )
                rc = await proc.wait()
                return out_bytes, err_bytes, rc

            stdout_bytes, stderr_bytes, returncode = await asyncio.wait_for(
                _collect(), timeout=self.timeout
            )
        except _OutputLimitExceeded:
            if proc is not None:
                await asyncio.shield(_terminate_async_process_tree(proc))
            return EngineTeamEstimate(index, None, "引擎输出超过大小上限")
        except asyncio.TimeoutError:
            if proc is not None:
                await asyncio.shield(_terminate_async_process_tree(proc))
            return EngineTeamEstimate(index, None, "引擎计算超时")
        except asyncio.CancelledError:
            if proc is not None:
                await asyncio.shield(_terminate_async_process_tree(proc))
            raise
        except OSError as exc:
            return EngineTeamEstimate(index, None, f"引擎无法启动（{type(exc).__name__}）")
        finally:
            if proc is not None:
                if proc.returncode is None:
                    await asyncio.shield(_terminate_async_process_tree(proc))
                transport = getattr(proc, "_transport", None)
                if transport is not None:
                    with contextlib.suppress(Exception):
                        transport.close()
                self._active_procs.discard(proc)

        text = stdout_bytes.decode("utf-8", errors="replace").strip()
        if returncode != 0:
            detail = _engine_error(text) or stderr_bytes.decode("utf-8", errors="replace").strip()[:200]
            return EngineTeamEstimate(index, None, detail or "引擎返回非零状态")
        lines = [line for line in text.splitlines() if line.strip()]
        if not lines:
            return EngineTeamEstimate(index, None, "引擎输出不是 JSON")
        try:
            payload = json.loads(lines[-1])
        except ValueError:
            return EngineTeamEstimate(index, None, "引擎输出不是 JSON")
        if not isinstance(payload, Mapping):
            return EngineTeamEstimate(index, None, "引擎输出不是 JSON 对象")
        error_obj = payload.get("error")
        if isinstance(error_obj, Mapping):
            return EngineTeamEstimate(index, None, str(error_obj.get("message") or "引擎输入错误"))
        if error_obj not in (None, "", False):
            return EngineTeamEstimate(index, None, "引擎返回异常错误字段")
        damage = payload.get("total_damage")
        if isinstance(damage, bool) or not isinstance(damage, int) or damage < 0:
            return EngineTeamEstimate(index, None, "引擎结果缺少有效 total_damage")
        evaluator = payload.get("evaluator") if isinstance(payload.get("evaluator"), Mapping) else {}
        commit = str(evaluator.get("commit") or "").strip().casefold()
        if not _COMMIT_RE.fullmatch(commit):
            commit = ""
        dirty = evaluator.get("dirty") if isinstance(evaluator.get("dirty"), bool) else None
        return EngineTeamEstimate(index, damage, "", commit, dirty)

    async def estimate(self, teams: Sequence[Any], *, boss_element: str = "") -> EngineEstimate:
        """逐队估算；任一步失败都明确记录，不把未知当成 0 或猜测值。"""
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
                reason="外部 nikke-calc 缺少独立 Git 仓库，无法核验固定基线版本。",
            )
        if has_git:
            if git_err:
                return EngineEstimate(False, commit=git_commit, dirty=git_dirty, reason=git_err)
            if not self.allow_unverified and (git_commit != PINNED_COMMIT or git_dirty is not False):
                return EngineEstimate(
                    False,
                    commit=git_commit,
                    dirty=git_dirty,
                    reason=(
                        f"外部 nikke-calc 版本校验失败（commit={git_commit[:10] or '未知'}, "
                        f"dirty={git_dirty}，要求 {PINNED_COMMIT[:10]} 且工作区干净）。"
                    ),
                )

        semaphore = self._semaphore()

        async def limited(team: Any) -> EngineTeamEstimate:
            # 信号量必须持续到 _run_team_subprocess 的 finally（含进程树强杀与 wait）全部完成。
            async with semaphore:
                return await self._run_team_subprocess(team, boss_element)

        if not teams:
            results: tuple[EngineTeamEstimate, ...] = ()
        else:
            batch_tasks: list[asyncio.Task[EngineTeamEstimate]] = []
            try:
                # TaskGroup + timeout 会在超时或取消退出时阻塞等待所有子任务（含信号量内的进程树强杀）彻底结束。
                async with asyncio.timeout(self.batch_timeout):
                    async with asyncio.TaskGroup() as tg:
                        batch_tasks = [tg.create_task(limited(team)) for team in teams]
                results = tuple(task.result() for task in batch_tasks)
            except TimeoutError:
                return EngineEstimate(
                    False,
                    commit=git_commit if has_git else "",
                    dirty=git_dirty if has_git else None,
                    reason="外部 nikke-calc 批次计算超时，已中止本轮估算。",
                )

        successes = [item for item in results if item.damage is not None]
        if has_git:
            commit = git_commit
            dirty = git_dirty
            reported_commits = {item.commit for item in successes if item.commit}
            if reported_commits and reported_commits != {git_commit}:
                commit = ""
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

        verified = commit == PINNED_COMMIT and dirty is False
        label = (
            f"nikke-calc {commit[:10]}（{LICENSE}，外部本地引擎）"
            if verified
            else f"nikke-calc 未核验版本（{LICENSE}，非可信固定基线）"
        )
        total = sum(item.damage for item in successes if item.damage is not None) if len(successes) == len(results) and results else None
        errors = [f"第 {item.index} 队：{item.error}" for item in results if item.error]
        pinned = f"{ENGINE_REPO}@{PINNED_COMMIT}"
        actual = f"{ENGINE_REPO}@{commit}" if commit else f"{ENGINE_REPO}@unverified"
        version_note = "" if verified else "（版本与固定基线未完成核验或存在未提交改动，结果不可作为可信基线对比）"
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
    "load_name_mapping",
]
