#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""只读抓取 NORMAL/HARD 战役历史阵容，并生成脱敏静态快照。

该工具只在维护期运行。它复用项目现有的 ``BlaBlaClient``、账号存储、
``CampaignHistoryBuilder`` 和 ``CharacterMasterResolver``，不会登录新账号，
不会执行 Daily/CDK/Signin 或其它写操作。完整响应不会写入磁盘。
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import hashlib
import importlib.util
import json
import random
import re
import subprocess
import sys
import tempfile
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any, Awaitable, Callable, Iterable


REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT.parent) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT.parent))


def _load_current_worktree_package() -> None:
    """脚本直接运行时，优先加载当前 worktree 而不是同级旧目录。"""
    package_name = "astrbot_plugin_nikke"
    package_init = REPO_ROOT / "__init__.py"
    if REPO_ROOT.name == package_name or not package_init.is_file():
        return
    loaded = sys.modules.get(package_name)
    loaded_paths = getattr(loaded, "__path__", ()) if loaded is not None else ()
    if any(Path(path).resolve() == REPO_ROOT for path in loaded_paths):
        return
    spec = importlib.util.spec_from_file_location(
        package_name,
        package_init,
        submodule_search_locations=[str(REPO_ROOT)],
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("无法加载当前 worktree 的插件包")
    module = importlib.util.module_from_spec(spec)
    sys.modules[package_name] = module
    spec.loader.exec_module(module)


_load_current_worktree_package()

from astrbot_plugin_nikke.campaign_history_builder import CampaignHistoryBuilder
from astrbot_plugin_nikke.campaign_history_models import ClearLineupStatus
from astrbot_plugin_nikke.campaign_stage_resolver import CampaignStage, CampaignStageResolver
from astrbot_plugin_nikke.character_master_resolver import CharacterMasterResolver
from astrbot_plugin_nikke.client import (
    BlaBlaClient,
    BlaBlaError,
    BlaBlaNetworkError,
    BlaBlaTimeoutError,
    CookieExpired,
)
from astrbot_plugin_nikke.costume_registry import CostumeRegistry
from astrbot_plugin_nikke.storage import NikkeStore


NORMAL_SNAPSHOT = "campaign_capture_normal.jsonl"
HARD_SNAPSHOT = "campaign_capture_hard.jsonl"
MANIFEST_NAME = "campaign_capture_manifest.json"
TID_INVENTORY_NAME = "campaign_tid_inventory.json"
COSTUME_INVENTORY_NAME = "campaign_costume_inventory.json"
TID_UNRESOLVED_NAME = "campaign_tid_unresolved.json"
DEFAULT_OUTPUT_DIR = Path("/AstrBot/data/nikke/campaign-capture")
DEFAULT_DATA_DIR = Path("/AstrBot/data/nikke")
RATE_LIMIT_CODES = {"212000", "429", "too_many_requests", "rate_limit", "rate_limited"}
RATE_LIMIT_BACKOFF = (5.0, 10.0, 20.0, 40.0)
COMPLETED_STATUSES = {
    ClearLineupStatus.AVAILABLE.value,
    ClearLineupStatus.UNAVAILABLE.value,
}
_INTEGER = re.compile(r"^[0-9]+$", re.ASCII)
_SAFE_COSTUME = re.compile(r"^[A-Za-z0-9_-]{1,120}$", re.ASCII)


def _now_iso() -> str:
    """返回带时区的稳定时间文本。"""
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _strict_int(value: Any) -> int | None:
    """解析非负整数；拒绝布尔、小数、负数和过长数字。"""
    if isinstance(value, bool):
        return None
    if type(value) is int:
        return value if 0 <= value <= 10**15 else None
    if isinstance(value, str) and _INTEGER.fullmatch(value.strip()):
        text = value.strip()
        if len(text) > 15:
            return None
        try:
            return int(text)
        except ValueError:
            return None
    return None


def _safe_code(value: Any) -> int | str | None:
    """只保留可审计的 API code 标量，不保存任意响应文本。"""
    parsed = _strict_int(value)
    if parsed is not None:
        return parsed
    if isinstance(value, str):
        text = value.strip().casefold()
        if text and len(text) <= 40 and re.fullmatch(r"[a-z0-9_-]+", text, re.ASCII):
            return text
    return None


def _safe_costume(value: Any) -> str | None:
    """只保留 API 明确给出的服装标量，不把 TID 推导成服装。"""
    if isinstance(value, bool):
        return None
    if type(value) is int and value >= 0:
        return str(value)
    if isinstance(value, str):
        text = value.strip()
        return text if _SAFE_COSTUME.fullmatch(text) else None
    return None


def response_shape(value: Any, *, depth: int = 0) -> dict[str, Any]:
    """只记录响应类型、键和数组形状，不记录响应值。"""
    if isinstance(value, dict):
        result: dict[str, Any] = {
            "type": "object",
            "keys": sorted(str(key)[:120] for key in value.keys()),
        }
        if depth < 2:
            for key in ("data", "list", "characters", "daily_progress"):
                if key in value:
                    result[key] = response_shape(value[key], depth=depth + 1)
        return result
    if isinstance(value, list):
        result = {"type": "array", "length": len(value)}
        if value and depth < 2:
            result["items"] = response_shape(value[0], depth=depth + 1)
        return result
    if value is None:
        return {"type": "null"}
    if isinstance(value, bool):
        return {"type": "boolean"}
    if isinstance(value, int):
        return {"type": "integer"}
    if isinstance(value, float):
        return {"type": "number"}
    if isinstance(value, str):
        return {"type": "string"}
    return {"type": "other"}


def _safe_message(code: Any, message: Any = None) -> str:
    """将接口消息压缩为不含身份数据的有限枚举。"""
    normalized = str(code).strip().casefold() if code is not None else ""
    if normalized == "1300017":
        return "暂无可查询的历史阵容"
    if normalized in RATE_LIMIT_CODES:
        return "请求过频"
    if normalized in {"", "0"}:
        return "ok"
    if isinstance(message, str) and message.strip().casefold() in {"ok", "success"}:
        return "ok"
    return "官方响应未成功"


def _safe_exception_message(exc: BaseException) -> str:
    """异常只映射到固定类别，避免将 Cookie 或账号上下文落盘。"""
    code = str(getattr(exc, "code", "") or "").strip().casefold()
    if code in RATE_LIMIT_CODES:
        return "请求过频"
    if isinstance(exc, CookieExpired):
        return "登录状态失效"
    if isinstance(exc, BlaBlaTimeoutError):
        return "请求超时"
    if isinstance(exc, BlaBlaNetworkError):
        return "网络异常"
    if isinstance(exc, BlaBlaError):
        return "接口请求失败"
    return "维护工具异常"


def _safe_captured_at(value: Any) -> str:
    """只复制生成器的 ISO 时间，避免旧快照字段被当作任意文本回写。"""
    if not isinstance(value, str):
        return ""
    text = value.strip()
    if len(text) > 80 or not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})",
        text,
        re.ASCII,
    ):
        return ""
    return text


def _is_rate_limited_response(response: Any) -> bool:
    if not isinstance(response, dict):
        return False
    code = response.get("code", response.get("retcode", response.get("ret_code")))
    return str(code).strip().casefold() in RATE_LIMIT_CODES


def _is_rate_limited_exception(exc: BaseException) -> bool:
    return str(getattr(exc, "code", "") or "").strip().casefold() in RATE_LIMIT_CODES


def _stage_sort_key(stage: CampaignStage) -> tuple[int, tuple[tuple[int, str], ...], int]:
    parts: list[tuple[int, str]] = []
    for part in re.split(r"[-]", stage.name):
        match = re.fullmatch(r"(\d+)([A-Z]?)", part, re.ASCII)
        if match:
            parts.append((int(match.group(1)), match.group(2)))
        else:
            parts.append((10**9, part))
    return stage.chapter, tuple(parts), stage.stage_id


def enumerate_stages(
    resolver: CampaignStageResolver,
    *,
    mode: str | None = None,
    chapter: int | None = None,
) -> list[CampaignStage]:
    """从 verified 静态表枚举 NORMAL/HARD，绝不按公式生成 stage ID。"""
    modes = [CampaignStageResolver.normalize_mode(mode)] if mode else ["NORMAL", "HARD"]
    result: list[CampaignStage] = []
    for selected_mode in modes:
        chapters = resolver.mapping.get(selected_mode, {})
        for chapter_text, stage_rows in chapters.items():
            try:
                selected_chapter = int(chapter_text)
            except (TypeError, ValueError):
                continue
            if chapter is not None and selected_chapter != chapter:
                continue
            if not isinstance(stage_rows, dict):
                continue
            for stage_name, stage_id in stage_rows.items():
                parsed_id = _strict_int(stage_id)
                if parsed_id is None:
                    continue
                result.append(CampaignStage(selected_mode, selected_chapter, str(stage_name), parsed_id))
    return sorted(result, key=lambda item: (0 if item.mode == "NORMAL" else 1, *_stage_sort_key(item)))


def estimate_duration_seconds(stage_count: int, *, minimum_interval: float = 0.8) -> float:
    """估算单线程请求间隔的最低耗时，不把服务端响应时间伪装成保证。"""
    if stage_count <= 1:
        return 0.0
    return (stage_count - 1) * max(0.0, float(minimum_interval))


def _stage_key(mode: str, stage_id: int) -> tuple[str, int]:
    return mode, stage_id


def _stage_ref(stage: CampaignStage) -> dict[str, Any]:
    return {
        "mode": stage.mode,
        "chapter": stage.chapter,
        "stage_name": stage.name,
        "stage_id": stage.stage_id,
    }


def _sanitize_members(members: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """仅复制战役历史合同允许的五个字段。"""
    result: list[dict[str, Any]] = []
    for item in members:
        if not isinstance(item, dict):
            continue
        row: dict[str, Any] = {}
        for source, target in (("slot", "slot"), ("tid", "tid"), ("lv", "lv"), ("combat", "combat")):
            parsed = _strict_int(item.get(source))
            if parsed is not None:
                row[target] = parsed
        if "costume_id" in item:
            costume_id = _safe_costume(item.get("costume_id"))
            if costume_id is not None:
                row["costume_id"] = costume_id
        result.append(row)
    return result


def classify_response(stage: CampaignStage, response: Any, builder: CampaignHistoryBuilder) -> tuple[str, list[dict[str, Any]], int]:
    """把 API 响应映射为捕获状态，并用现有 Builder 验证 AVAILABLE 合同。"""
    if not isinstance(response, dict):
        return "malformed", [], 0
    code = response.get("code")
    if type(code) is not int:
        return "malformed", [], 0
    if code == 1300017:
        return "unavailable", [], 0
    if code == 212000 or str(code) in RATE_LIMIT_CODES:
        return "rate_limited", [], 0
    if code != 0:
        return "error", [], 0
    data = response.get("data")
    raw_members = data.get("list") if isinstance(data, dict) else None
    if not isinstance(data, dict) or not isinstance(raw_members, list):
        return "malformed", [], 0
    if not raw_members:
        return "unavailable", [], 0
    record = builder.build(stage, response)
    if record.status != ClearLineupStatus.AVAILABLE or len(record.members) != 5:
        return "malformed", [], len(raw_members)
    members = _sanitize_members(raw_members)
    allowed = {"slot", "tid", "lv", "combat"}
    if len(members) != 5 or any(set(row) not in (allowed, allowed | {"costume_id"}) for row in members):
        return "malformed", [], len(raw_members)
    return "available", members, len(members)


def make_snapshot(
    stage: CampaignStage,
    response: Any,
    *,
    builder: CampaignHistoryBuilder,
    captured_at: str | None = None,
) -> dict[str, Any]:
    """生成单条无账号身份的快照。"""
    captured_at = captured_at or _now_iso()
    status, members, member_count = classify_response(stage, response, builder)
    code = response.get("code") if isinstance(response, dict) else None
    row: dict[str, Any] = {
        **_stage_ref(stage),
        "captured_at": captured_at,
        "api_code": _safe_code(code),
        "safe_message": _safe_message(code, response.get("msg") if isinstance(response, dict) else None),
        "status": status,
        "response_schema": response_shape(response),
        "member_count": member_count,
    }
    if status == "available":
        row["members"] = members
        row["total_combat"] = sum(int(item["combat"]) for item in members)
    else:
        row["members"] = []
    return row


def make_exception_snapshot(stage: CampaignStage, exc: BaseException, *, captured_at: str | None = None) -> dict[str, Any]:
    """生成不携带异常文本的受控错误快照。"""
    captured_at = captured_at or _now_iso()
    status = "rate_limited" if _is_rate_limited_exception(exc) else "error"
    code = _safe_code(getattr(exc, "code", None))
    return {
        **_stage_ref(stage),
        "captured_at": captured_at,
        "api_code": code,
        "safe_message": _safe_exception_message(exc),
        "status": status,
        "response_schema": {"type": "exception", "class": type(exc).__name__[:80]},
        "member_count": 0,
        "members": [],
    }


def _normalize_snapshot(row: Any) -> dict[str, Any] | None:
    """读取旧快照时只保留当前白名单字段，顺便清理历史意外泄漏。"""
    if not isinstance(row, dict):
        return None
    mode = row.get("mode")
    stage_id = _strict_int(row.get("stage_id"))
    chapter = _strict_int(row.get("chapter"))
    stage_name = row.get("stage_name")
    status = row.get("status")
    stage_name_text = row.get("stage_name")
    if mode not in {"NORMAL", "HARD"} or stage_id is None or chapter is None or not isinstance(stage_name, str) or status not in {
        "available", "unavailable", "rate_limited", "error", "malformed"
    }:
        return None
    if not re.fullmatch(r"\d+-\d+(?:[A-Z]-\d+)?", stage_name_text.strip().upper(), re.ASCII):
        return None
    members = _sanitize_members(row.get("members", []))
    safe_messages = {
        "available": "ok",
        "unavailable": "暂无可查询的历史阵容",
        "rate_limited": "请求过频",
        "error": "接口请求失败",
        "malformed": "响应结构异常",
    }
    result = {
        "mode": mode,
        "chapter": chapter,
        "stage_name": stage_name_text.strip().upper()[:80],
        "stage_id": stage_id,
        "captured_at": _safe_captured_at(row.get("captured_at")),
        "api_code": _safe_code(row.get("api_code")),
        "safe_message": safe_messages[status],
        "status": status,
        "response_schema": response_shape(row.get("response_schema")) if isinstance(row.get("response_schema"), dict) else {"type": "unknown"},
        "member_count": len(members) if status == "available" else 0,
        "members": members if status == "available" else [],
    }
    if status == "available" and len(members) == 5:
        result["total_combat"] = sum(int(item.get("combat", 0)) for item in members)
    return result


def _read_jsonl(path: Path) -> OrderedDict[tuple[str, int], dict[str, Any]]:
    result: OrderedDict[tuple[str, int], dict[str, Any]] = OrderedDict()
    if not path.is_file():
        return result
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        return result
    for line in lines:
        try:
            row = _normalize_snapshot(json.loads(line))
        except (TypeError, ValueError, json.JSONDecodeError):
            row = None
        if row is not None:
            result[_stage_key(row["mode"], row["stage_id"])] = row
    return result


def _filter_active_rows(
    rows_by_mode: dict[str, OrderedDict[tuple[str, int], dict[str, Any]]],
    stages: Iterable[CampaignStage],
) -> dict[str, OrderedDict[tuple[str, int], dict[str, Any]]]:
    """只保留当前静态 stage 表仍声明的 mode/stage_id 快照。"""
    active_keys = {
        _stage_key(stage.mode, stage.stage_id)
        for stage in stages
    }
    return {
        mode: OrderedDict(
            (key, row)
            for key, row in rows.items()
            if key in active_keys
        )
        for mode, rows in rows_by_mode.items()
    }


def _write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    """以同目录临时文件原子替换快照，避免限流中断留下半行。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    content = "".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(content)
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False) as handle:
        temporary = Path(handle.name)
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_sha(path: Path = REPO_ROOT) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    value = result.stdout.strip()
    return value if re.fullmatch(r"[0-9a-fA-F]{7,64}", value) else "unknown"


def _safe_area_id(value: Any) -> str | None:
    parsed = _strict_int(value)
    return str(parsed) if parsed is not None else None


def build_tid_inventory(rows: Iterable[dict[str, Any]], resolver: CharacterMasterResolver) -> dict[str, Any]:
    """从已脱敏成员字段生成 TID 覆盖率，未知值保持 unresolved。"""
    entries: OrderedDict[int, dict[str, Any]] = OrderedDict()
    for row in rows:
        if row.get("status") != "available":
            continue
        stage = {
            "mode": row.get("mode"),
            "chapter": row.get("chapter"),
            "stage_name": row.get("stage_name"),
            "stage_id": row.get("stage_id"),
        }
        for member in row.get("members", []):
            if not isinstance(member, dict):
                continue
            tid = _strict_int(member.get("tid"))
            if tid is None:
                continue
            entry = entries.get(tid)
            if entry is None:
                prefix = resolver.normalize_battle_tid_prefix(tid)
                character = resolver.resolve_battle_tid(tid)
                entry = {
                    "raw_tid": tid,
                    "normalized_prefix": prefix,
                    "occurrence_count": 0,
                    "resolved_character": character.name_cn if character else None,
                    "resource_id": str(character.resource_id) if character else None,
                    "spine_asset_id": character.spine_asset_id if character else None,
                    "first_seen_stage": stage,
                    "last_seen_stage": stage,
                }
                entries[tid] = entry
            entry["occurrence_count"] += 1
            entry["last_seen_stage"] = stage
    values = list(entries.values())
    resolved_count = sum(item["resolved_character"] is not None for item in values)
    unresolved_count = len(values) - resolved_count
    prefixes = {item["normalized_prefix"] for item in values if item["normalized_prefix"] is not None}
    return {
        "schema_version": 1,
        "unique_raw_tids": len(values),
        "unique_normalized_prefixes": len(prefixes),
        "resolved": resolved_count,
        "unresolved": unresolved_count,
        "coverage_percent": round(resolved_count * 100 / len(values), 2) if values else None,
        "entries": values,
    }


def build_costume_inventory(rows: Iterable[dict[str, Any]], resolver: CharacterMasterResolver, registry: CostumeRegistry) -> dict[str, Any]:
    """只统计 response 明确携带的 costume_id，并用 Registry 做所有者校验。"""
    entries: OrderedDict[tuple[int, str], dict[str, Any]] = OrderedDict()
    for row in rows:
        if row.get("status") != "available":
            continue
        stage = {
            "mode": row.get("mode"),
            "chapter": row.get("chapter"),
            "stage_name": row.get("stage_name"),
            "stage_id": row.get("stage_id"),
        }
        for member in row.get("members", []):
            if not isinstance(member, dict) or "costume_id" not in member:
                continue
            tid = _strict_int(member.get("tid"))
            costume_id = _safe_costume(member.get("costume_id"))
            if tid is None or costume_id is None:
                continue
            key = (tid, costume_id)
            entry = entries.get(key)
            if entry is None:
                character = resolver.resolve_battle_tid(tid)
                expected_resource = character.resource_id if character else None
                resolved = registry.resolve(costume_id, expected_resource)
                entry = {
                    "costume_id": costume_id,
                    "raw_tid": tid,
                    "occurrence_count": 0,
                    "registry_status": resolved.status,
                    "spine_asset_id": resolved.costume.spine_asset_id if resolved.ok and resolved.costume else None,
                    "first_seen_stage": stage,
                    "last_seen_stage": stage,
                }
                entries[key] = entry
            entry["occurrence_count"] += 1
            entry["last_seen_stage"] = stage
    return {"schema_version": 1, "unique_pairs": len(entries), "entries": list(entries.values())}


def snapshot_to_response(row: dict[str, Any]) -> dict[str, Any]:
    """将脱敏快照还原成 Builder 可回放的最小响应。"""
    if row.get("status") == "available":
        return {"code": 0, "data": {"list": row.get("members", [])}}
    if row.get("status") == "unavailable":
        return {"code": 1300017, "data": None}
    if row.get("status") == "rate_limited":
        return {"code": 212000, "data": None}
    return {"code": row.get("api_code"), "data": {"list": row.get("members", [])}}


async def _query_with_rate_limit(
    client: BlaBlaClient,
    account: dict[str, Any],
    stage: CampaignStage,
    area_id: int,
    *,
    sleep: Callable[[float], Awaitable[Any]],
    max_rate_retries: int,
) -> tuple[Any, BaseException | None, bool]:
    """按 5/10/20/40 秒退避；达到阈值返回 rate_limited 并由调用方停止。"""
    retries = 0
    while True:
        try:
            response = await client.get_main_quest_clear_lineup(account, stage.stage_id, area_id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if _is_rate_limited_exception(exc) and retries < min(max_rate_retries, len(RATE_LIMIT_BACKOFF)):
                await sleep(RATE_LIMIT_BACKOFF[retries])
                retries += 1
                continue
            return None, exc, _is_rate_limited_exception(exc)
        if _is_rate_limited_response(response):
            if retries < min(max_rate_retries, len(RATE_LIMIT_BACKOFF)):
                await sleep(RATE_LIMIT_BACKOFF[retries])
                retries += 1
                continue
            return response, None, True
        return response, None, False


async def capture(
    data_dir: str | Path,
    output_dir: str | Path,
    *,
    mode: str | None = None,
    chapter: int | None = None,
    resume: bool = False,
    force: bool = False,
    stage_file: str | Path | None = None,
    client: BlaBlaClient | None = None,
    account: dict[str, Any] | None = None,
    store_cls: type[NikkeStore] = NikkeStore,
    sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
    jitter: Callable[[float, float], float] = random.uniform,
    max_rate_retries: int = len(RATE_LIMIT_BACKOFF),
    plugin_version: str = "",
) -> dict[str, Any]:
    """执行一次只读抓取并返回不含凭证的摘要。"""
    if force:
        resume = False
    data_dir = Path(data_dir)
    output_dir = Path(output_dir)
    source_path = Path(stage_file) if stage_file else REPO_ROOT / "assets" / "campaign_stages.json"
    stage_resolver = CampaignStageResolver.from_file(source_path)
    stages = enumerate_stages(stage_resolver, mode=mode, chapter=chapter)
    if not stages:
        raise ValueError("verified Campaign stage 表中没有符合筛选条件的关卡")
    active_stages = enumerate_stages(stage_resolver)

    if account is None:
        store = store_cls(data_dir)
        accounts = store.list_accounts(with_cookie=True)
        if not accounts:
            raise RuntimeError("没有可用的已授权绑定账号")
        account = accounts[0]
    area_id = _strict_int(account.get("area_id"))
    if area_id is None:
        raise RuntimeError("已绑定账号缺少有效 area_id")

    output_dir.mkdir(parents=True, exist_ok=True)
    normal_path = output_dir / NORMAL_SNAPSHOT
    hard_path = output_dir / HARD_SNAPSHOT
    old_manifest: dict[str, Any] = {}
    manifest_path = output_dir / MANIFEST_NAME
    if manifest_path.is_file():
        try:
            loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                old_manifest = loaded
        except (OSError, UnicodeError, ValueError):
            old_manifest = {}
    rows_by_mode: dict[str, OrderedDict[tuple[str, int], dict[str, Any]]] = {
        "NORMAL": _read_jsonl(normal_path),
        "HARD": _read_jsonl(hard_path),
    }
    # 映射更新时立即排除旧 stage_id；旧 JSONL 仍保留在历史存储中，但不再进入
    # 当前 TID、服装 inventory、统计或后续回放输入。
    rows_by_mode = _filter_active_rows(rows_by_mode, active_stages)
    selected_keys = {_stage_key(stage.mode, stage.stage_id) for stage in stages}
    if force:
        for selected_key in selected_keys:
            rows_by_mode[selected_key[0]].pop(selected_key, None)

    history_builder = CampaignHistoryBuilder(master_resolver=CharacterMasterResolver())
    request_count = 0
    skipped_count = 0
    stopped_reason = ""
    started_at = _now_iso()
    started_monotonic = time.monotonic()
    last_request = False
    active_client = client or BlaBlaClient()

    for stage in stages:
        key = _stage_key(stage.mode, stage.stage_id)
        existing = rows_by_mode[stage.mode].get(key)
        if resume and not force and existing and existing.get("status") in COMPLETED_STATUSES:
            skipped_count += 1
            continue
        if last_request:
            await sleep(float(jitter(0.8, 1.5)))
        last_request = True
        request_count += 1
        response, error, rate_limited = await _query_with_rate_limit(
            active_client,
            account,
            stage,
            area_id,
            sleep=sleep,
            max_rate_retries=max_rate_retries,
        )
        if error is not None:
            snapshot = make_exception_snapshot(stage, error)
        else:
            snapshot = make_snapshot(stage, response, builder=history_builder)
        rows_by_mode[stage.mode][key] = snapshot
        _write_jsonl(normal_path, rows_by_mode["NORMAL"].values())
        _write_jsonl(hard_path, rows_by_mode["HARD"].values())
        if rate_limited or snapshot.get("status") == "rate_limited":
            stopped_reason = "RATE_LIMITED"
            break

    all_rows = [*rows_by_mode["NORMAL"].values(), *rows_by_mode["HARD"].values()]
    resolver = CharacterMasterResolver()
    tid_inventory = build_tid_inventory(all_rows, resolver)
    costume_inventory = build_costume_inventory(all_rows, resolver, CostumeRegistry(REPO_ROOT / "assets"))
    _write_json(output_dir / TID_INVENTORY_NAME, tid_inventory)
    _write_json(output_dir / COSTUME_INVENTORY_NAME, costume_inventory)
    unresolved_entries = [
        entry for entry in tid_inventory["entries"]
        if entry.get("resolved_character") is None
    ]
    unresolved_payload = {
        "schema_version": 1,
        "unresolved": len(unresolved_entries),
        "entries": unresolved_entries,
    }
    _write_json(output_dir / TID_UNRESOLVED_NAME, unresolved_payload)

    source_hash = _sha256(source_path)
    previous_hash = old_manifest.get("stage_source_sha256")
    snapshot_status = "SNAPSHOT_OUTDATED" if previous_hash and previous_hash != source_hash else "CURRENT"
    status_counts = {name: sum(row.get("status") == name for row in all_rows) for name in ("available", "unavailable", "rate_limited", "error", "malformed")}
    completed_at = _now_iso()
    elapsed_seconds = round(max(0.0, time.monotonic() - started_monotonic), 3)
    manifest = {
        "schema_version": 1,
        "snapshot_status": snapshot_status,
        "stage_source": source_path.name,
        "stage_source_sha256": source_hash,
        "plugin_git_sha": _git_sha(),
        "plugin_version": str(plugin_version)[:40],
        "capture_started_at": started_at,
        "capture_completed_at": completed_at,
        "area_id": str(area_id),
        "normal_count": len(rows_by_mode["NORMAL"]),
        "hard_count": len(rows_by_mode["HARD"]),
        "total_count": len(all_rows),
        "normal_target_count": sum(stage.mode == "NORMAL" for stage in active_stages),
        "hard_target_count": sum(stage.mode == "HARD" for stage in active_stages),
        "target_count": len(active_stages),
        "requested_mode": CampaignStageResolver.normalize_mode(mode) if mode else "ALL",
        "requested_chapter": chapter,
        "request_count": request_count,
        "skipped_count": skipped_count,
        "estimated_minimum_seconds": estimate_duration_seconds(len(stages)),
        "elapsed_seconds": elapsed_seconds,
        "status_counts": status_counts,
        "stopped_reason": stopped_reason,
        "files": {
            "normal": {"name": NORMAL_SNAPSHOT, "sha256": _sha256(normal_path), "records": len(rows_by_mode["NORMAL"])},
            "hard": {"name": HARD_SNAPSHOT, "sha256": _sha256(hard_path), "records": len(rows_by_mode["HARD"])},
            "tid_inventory": {"name": TID_INVENTORY_NAME, "sha256": _sha256(output_dir / TID_INVENTORY_NAME)},
            "costume_inventory": {"name": COSTUME_INVENTORY_NAME, "sha256": _sha256(output_dir / COSTUME_INVENTORY_NAME)},
            "tid_unresolved": {"name": TID_UNRESOLVED_NAME, "sha256": _sha256(output_dir / TID_UNRESOLVED_NAME)},
        },
    }
    _write_json(manifest_path, manifest)
    return {
        "normal_count": len(rows_by_mode["NORMAL"]),
        "hard_count": len(rows_by_mode["HARD"]),
        "total_count": len(all_rows),
        "request_count": request_count,
        "skipped_count": skipped_count,
        "status_counts": status_counts,
        "stopped_reason": stopped_reason,
        "normal_target_count": sum(stage.mode == "NORMAL" for stage in active_stages),
        "hard_target_count": sum(stage.mode == "HARD" for stage in active_stages),
        "target_count": len(active_stages),
        "elapsed_seconds": elapsed_seconds,
        "tid_resolved": tid_inventory["resolved"],
        "tid_unresolved": tid_inventory["unresolved"],
        "output_dir": str(output_dir),
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--stage-file", type=Path, default=REPO_ROOT / "assets" / "campaign_stages.json")
    parser.add_argument("--mode", choices=("NORMAL", "HARD"), default=None)
    parser.add_argument("--chapter", type=int, default=None)
    parser.add_argument("--resume", action="store_true", help="跳过已有 AVAILABLE/UNAVAILABLE 快照")
    parser.add_argument("--force", action="store_true", help="重抓筛选范围内的快照")
    parser.add_argument("--max-rate-retries", type=int, default=len(RATE_LIMIT_BACKOFF))
    return parser.parse_args()


async def _main() -> int:
    args = _parse_args()
    resolver = CampaignStageResolver.from_file(args.stage_file)
    stages = enumerate_stages(resolver, mode=args.mode, chapter=args.chapter)
    print(json.dumps({
        "normal_count": sum(stage.mode == "NORMAL" for stage in stages),
        "hard_count": sum(stage.mode == "HARD" for stage in stages),
        "total_count": len(stages),
        "estimated_minimum_seconds": estimate_duration_seconds(len(stages)),
    }, ensure_ascii=False))
    summary = await capture(
        args.data_dir,
        args.output_dir,
        mode=args.mode,
        chapter=args.chapter,
        resume=args.resume,
        force=args.force,
        stage_file=args.stage_file,
        max_rate_retries=max(0, args.max_rate_retries),
    )
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if not summary["stopped_reason"] else 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
