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
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import urlparse

ENGINE_REPO = "Jgaram/nikke-calc"
PINNED_COMMIT = "67835ca3033a95482749ea2db35a8ee2a0856a92"
ENGINE_SOURCE_URL = f"https://github.com/{ENGINE_REPO}/tree/{PINNED_COMMIT}"
ENGINE_PAGE_URL = "https://nikkehub.com/zh-tw/about"
LICENSE = "MIT"
ELEMENT_CODES = {
    "燃烧": "작열", "风压": "풍압", "铁甲": "철갑", "电击": "전격", "水冷": "수냉",
    "Fire": "작열", "Wind": "풍압", "Iron": "철갑", "Electric": "전격", "Water": "수냉",
}


class EngineNameMappingError(ValueError):
    """角色名称映射文件不符合合同。"""


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
        return self.commit == PINNED_COMMIT and self.dirty is not True


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
    """以子进程调用外部引擎；不复制、不修改引擎代码。"""

    def __init__(
        self,
        engine_path: str | Path,
        mapping: Mapping[str, str],
        *,
        python: str | None = None,
        timeout: float = 90.0,
        concurrency: int = 2,
        mapping_error: str = "",
        work_dir: str | Path | None = None,
    ) -> None:
        self.engine_path = Path(engine_path)
        self.mapping = dict(mapping)
        self.python = python or sys.executable
        self.timeout = timeout
        self.concurrency = max(1, min(int(concurrency), 5))
        self.mapping_error = mapping_error
        self.work_dir = Path(work_dir) if work_dir else self.engine_path.parent / ".nikke-calc-runs"

    @property
    def available(self) -> bool:
        return self.engine_path.is_dir() and (self.engine_path / "runner" / "sim.py").is_file() and bool(self.mapping)

    def reason(self) -> str:
        if not self.engine_path.is_dir():
            return f"未找到本地 nikke-calc 引擎目录：{self.engine_path}"
        if not (self.engine_path / "runner" / "sim.py").is_file():
            return "本地引擎缺少 runner/sim.py"
        if not self.mapping:
            return self.mapping_error or "缺少角色名称映射（data/nikke/solo-raid-engine-names.json）"
        return "引擎可用"

    def _engine_name(self, member: Any) -> str | None:
        for key in (str(getattr(member, "name_code", "") or ""), str(getattr(member, "name", "") or "")):
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

    def _run_team_sync(self, team: Any, boss_element: str) -> EngineTeamEstimate:
        index = int(getattr(team, "index", 0) or 0)
        if len(getattr(team, "members", ())) != 5:
            return EngineTeamEstimate(index, None, "队伍不足五人，未调用引擎")
        if not getattr(team, "chain_ok", False):
            return EngineTeamEstimate(index, None, "爆裂链不完整，未调用引擎")
        try:
            request = self._request(team, boss_element)
        except EngineNameMappingError as exc:
            return EngineTeamEstimate(index, None, str(exc))
        self.work_dir.mkdir(parents=True, exist_ok=True)
        env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
        stdout_path = stderr_path = None
        try:
            with tempfile.NamedTemporaryFile(
                "w+", dir=self.work_dir, suffix=".out.json", delete=False, encoding="utf-8"
            ) as stdout_file, tempfile.NamedTemporaryFile(
                "w+", dir=self.work_dir, suffix=".err.log", delete=False, encoding="utf-8"
            ) as stderr_file:
                stdout_path, stderr_path = Path(stdout_file.name), Path(stderr_file.name)
                completed = subprocess.run(
                    [
                        self.python, "-m", "runner.sim", "--request",
                        json.dumps(request, ensure_ascii=False), "--json",
                    ],
                    cwd=str(self.engine_path),
                    env=env,
                    stdin=subprocess.DEVNULL,
                    stdout=stdout_file,
                    stderr=stderr_file,
                    timeout=self.timeout,
                    check=False,
                )
            text = stdout_path.read_text(encoding="utf-8", errors="replace").strip()
            if completed.returncode != 0:
                detail = _engine_error(text) or stderr_path.read_text(
                    encoding="utf-8", errors="replace"
                ).strip()[:200]
                return EngineTeamEstimate(index, None, detail or "引擎返回非零状态")
        except subprocess.TimeoutExpired:
            return EngineTeamEstimate(index, None, "引擎计算超时")
        except OSError as exc:
            return EngineTeamEstimate(index, None, f"引擎无法启动（{type(exc).__name__}）")
        finally:
            for path in (stdout_path, stderr_path):
                if path is not None:
                    path.unlink(missing_ok=True)
        try:
            payload = json.loads(text.splitlines()[-1])
        except (ValueError, IndexError):
            return EngineTeamEstimate(index, None, "引擎输出不是 JSON")
        if isinstance(payload.get("error"), Mapping):
            return EngineTeamEstimate(index, None, str(payload["error"].get("message") or "引擎输入错误"))
        damage = payload.get("total_damage")
        if isinstance(damage, bool) or not isinstance(damage, int) or damage < 0:
            return EngineTeamEstimate(index, None, "引擎结果缺少有效 total_damage")
        evaluator = payload.get("evaluator") if isinstance(payload.get("evaluator"), Mapping) else {}
        commit = str(evaluator.get("commit") or "")
        dirty = evaluator.get("dirty") if isinstance(evaluator.get("dirty"), bool) else None
        return EngineTeamEstimate(index, damage, "", commit, dirty)

    async def _run_team(self, team: Any, boss_element: str) -> EngineTeamEstimate:
        return await asyncio.to_thread(self._run_team_sync, team, boss_element)

    async def estimate(self, teams: Sequence[Any], *, boss_element: str = "") -> EngineEstimate:
        """逐队估算；任一步失败都明确记录，不把未知当成 0 或猜测值。"""
        if not self.available:
            return EngineEstimate(False, reason=self.reason())
        semaphore = asyncio.Semaphore(self.concurrency)

        async def limited(team: Any) -> EngineTeamEstimate:
            async with semaphore:
                return await self._run_team(team, boss_element)

        results = tuple(await asyncio.gather(*(limited(team) for team in teams)))
        commits = {item.commit for item in results if item.commit}
        commit = next(iter(commits)) if len(commits) == 1 else ("" if commits else PINNED_COMMIT)
        dirty_values = [item.dirty for item in results if item.dirty is not None]
        dirty = True if any(dirty_values) else (False if dirty_values else None)
        label = f"nikke-calc {(commit or PINNED_COMMIT)[:10]}（{LICENSE}，外部本地引擎）"
        successes = [item for item in results if item.damage is not None]
        total = sum(item.damage for item in successes) if len(successes) == len(results) and results else None
        errors = [f"第 {item.index} 队：{item.error}" for item in results if item.error]
        pinned = f"{ENGINE_REPO}@{PINNED_COMMIT}"
        actual = f"{ENGINE_REPO}@{commit}" if commit else pinned
        version_note = "" if commit == PINNED_COMMIT and dirty is not True else "（引擎版本与固定基线不一致，未验证）"
        note = (
            f"由外部 {actual}（{LICENSE}）{version_note}计算；"
            "使用引擎默认敌人与已知赛季属性，未提供赛季 43 防御/HP，因此不是官方伤害数值。"
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
    try:
        payload = json.loads(text.splitlines()[-1])
    except (ValueError, IndexError):
        return ""
    error = payload.get("error") if isinstance(payload, Mapping) else None
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
    "PINNED_COMMIT",
    "SoloRaidDamageEngine",
    "load_name_mapping",
]
