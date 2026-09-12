# SPDX-License-Identifier: GPL-3.0-or-later
"""持久化记录未映射 OL 词条，严禁写入账号或请求身份信息。"""

from __future__ import annotations

import json
import re
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_OPTION_ID = re.compile(r"^\d{1,32}$")
_RAW_KEY = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")


class UnknownOlInventory:
    """只统计 option ID 与 function key，不保存角色、账号或原始响应。"""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._lock = threading.RLock()

    @staticmethod
    def _safe_option_id(value: Any) -> str | None:
        if isinstance(value, bool):
            return None
        text = str(value or "").strip()
        return text if _OPTION_ID.fullmatch(text) else None

    @staticmethod
    def _safe_raw_key(value: Any) -> str | None:
        text = str(value or "").strip()
        return text if _RAW_KEY.fullmatch(text) else None

    def observe(self, raw_id: Any, raw_key: Any) -> None:
        """原子累计未知 OL option；非法外部字段只会被丢弃。"""
        option_id = self._safe_option_id(raw_id)
        key = self._safe_raw_key(raw_key)
        if option_id is None and key is None:
            return
        identity = f"id:{option_id}" if option_id is not None else f"key:{key}"
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            entries = self._read_entries()
            entry = entries.get(identity)
            if entry is None:
                entry = {
                    "raw_id": option_id,
                    "raw_key": key,
                    "observed_raw_keys": {},
                    "occurrence": 0,
                    "first_seen": now,
                    "last_seen": now,
                    "resolved_status": "UNKNOWN_OL_OPTION",
                }
                entries[identity] = entry
            entry["occurrence"] = int(entry.get("occurrence", 0)) + 1
            entry["last_seen"] = now
            if entry.get("raw_key") is None and key is not None:
                entry["raw_key"] = key
            observed = entry.setdefault("observed_raw_keys", {})
            if key is not None:
                observed[key] = int(observed.get(key, 0)) + 1
            self._write_entries(entries)

    def prune_known(self, known_option_ids: set[str]) -> list[str]:
        """移除已由完整 OL 表确认的历史误报，不影响真正未知条目。"""
        with self._lock:
            entries = self._read_entries()
            resolved = sorted(
                key.removeprefix("id:") for key, row in entries.items()
                if row.get("raw_id") in known_option_ids
            )
            if resolved:
                entries = {
                    key: row for key, row in entries.items()
                    if row.get("raw_id") not in known_option_ids
                }
                self._write_entries(entries)
            return resolved

    def _read_entries(self) -> dict[str, dict[str, Any]]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            rows = data.get("entries", []) if isinstance(data, dict) else []
        except (OSError, UnicodeError, json.JSONDecodeError):
            rows = []
        result: dict[str, dict[str, Any]] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            option_id = self._safe_option_id(row.get("raw_id"))
            raw_key = self._safe_raw_key(row.get("raw_key"))
            if option_id is None and raw_key is None:
                continue
            identity = f"id:{option_id}" if option_id is not None else f"key:{raw_key}"
            result[identity] = dict(row)
        return result

    def _write_entries(self, entries: dict[str, dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": 1,
            "status": "UNKNOWN_OL_OPTION",
            "privacy": "Contains only option IDs, normalized function keys and timestamps.",
            "entries": [entries[key] for key in sorted(entries)],
        }
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=self.path.parent,
            prefix=f".{self.path.name}.", suffix=".tmp", delete=False,
        ) as handle:
            temporary = Path(handle.name)
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        try:
            temporary.replace(self.path)
        finally:
            temporary.unlink(missing_ok=True)
