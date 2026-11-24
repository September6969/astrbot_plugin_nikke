# SPDX-License-Identifier: GPL-3.0-or-later
"""本命九宫格与最爱人气榜（29）。

九个妮姬按输入顺序解析并渲染为 3x3；重复输入显式报错，图片缺失时由渲染层给出
稳定占位。人气榜按用户隔离保存投票：同一用户再次投票会覆盖旧投票，不会重复累计。
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Protocol

CELL_COUNT = 9


class FavoriteGridError(ValueError):
    """九宫格输入或人气榜存储不合法。"""


def _norm(value: Any) -> str:
    return unicodedata.normalize("NFKC", str(value or "")).casefold().strip()


@dataclass(frozen=True, slots=True)
class GridCell:
    index: int
    name: str
    name_code: str
    resource_id: str
    burst: str
    element: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "name": self.name,
            "name_code": self.name_code,
            "resource_id": self.resource_id,
            "burst": self.burst,
            "element": self.element,
        }


@dataclass(frozen=True, slots=True)
class RankEntry:
    name: str
    name_code: str
    votes: int


def split_nine(text: str) -> list[str]:
    """按显式分隔符拆分；没有分隔符时按空白拆分（英文名可用换行或逗号）。"""
    raw = str(text or "").strip()
    if not raw:
        raise FavoriteGridError("请提供九个不同的妮姬名称")
    normalized = unicodedata.normalize("NFKC", raw)
    if re.search(r"[,，、/\n;；]", normalized):
        parts = re.split(r"[,，、/\n;；]+", normalized)
    else:
        parts = normalized.split()
    return [part.strip() for part in parts if part.strip()]


def resolve_nine(
    text: str,
    rows: Iterable[Mapping[str, Any]],
    resolver: Any,
) -> tuple[GridCell, ...]:
    """解析九个妮姬并按输入顺序返回；重名或多结果显式区分。"""
    tokens = split_nine(text)
    if len(tokens) != CELL_COUNT:
        raise FavoriteGridError(f"需要九个妮姬，当前收到 {len(tokens)} 个")
    directory = [dict(row) for row in rows if isinstance(row, Mapping)]
    if not directory:
        raise FavoriteGridError("缺少可核验的角色目录，无法解析名称")
    cells: list[GridCell] = []
    seen: dict[str, str] = {}
    for index, token in enumerate(tokens, 1):
        matches = resolver.find(directory, token)
        if not matches:
            raise FavoriteGridError(f"未找到妮姬：{token}")
        if len(matches) > 1:
            names = "、".join(str(item.get("name_zh_cn") or item.get("name_zh_tw") or token) for item in matches[:5])
            raise FavoriteGridError(f"妮姬“{token}”有多个匹配，请使用完整名称：{names}")
        item = matches[0]
        code = str(item.get("name_code") or item.get("character_key") or "").strip()
        if not code:
            raise FavoriteGridError(f"妮姬“{token}”缺少稳定身份，无法生成九宫格")
        if code in seen:
            raise FavoriteGridError(f"重复妮姬：{token}（与第 {seen[code]} 格相同）")
        seen[code] = index
        cells.append(
            GridCell(
                index=index,
                name=str(item.get("name_zh_cn") or item.get("name_zh_tw") or item.get("name_cn") or token),
                name_code=code,
                resource_id=str(item.get("resource_id") or ""),
                burst=str(item.get("burst") or ""),
                element=str(item.get("element") or ""),
            )
        )
    return tuple(cells)


class FavoriteRankingStorePort(Protocol):
    def get_setting(self, key: str, default: Any = None) -> Any: ...

    def set_setting(self, key: str, value: Any) -> None: ...


class FavoriteRanking:
    """按用户覆盖保存九宫格投票，并聚合为公开人气榜。"""

    KEY_PREFIX = "favorite_grid_v1:"
    INDEX_KEY = "favorite_grid_v1:index"

    def __init__(self, store: FavoriteRankingStorePort, *, clock=None) -> None:
        self._store = store
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def _key(self, actor_id: str) -> str:
        text = str(actor_id or "").strip()
        if not text:
            raise FavoriteGridError("缺少用户标识，无法保存投票")
        return f"{self.KEY_PREFIX}{text}"

    def _voters(self) -> list[str]:
        raw = self._store.get_setting(self.INDEX_KEY, [])
        if not isinstance(raw, list):
            return []
        return [str(item) for item in raw if isinstance(item, str) and item.strip()]

    def vote(self, actor_id: str, cells: Iterable[GridCell]) -> tuple[GridCell, ...]:
        """保存或覆盖该用户的九票；同一角色在同一用户内只计一次。"""
        items = tuple(cells)
        if len(items) != CELL_COUNT:
            raise FavoriteGridError("人气榜投票需要九个不同妮姬")
        codes = [cell.name_code for cell in items]
        if len(set(codes)) != CELL_COUNT:
            raise FavoriteGridError("人气榜投票包含重复妮姬")
        current = self._clock()
        if not isinstance(current, datetime) or current.tzinfo is None:
            raise FavoriteGridError("投票时间必须包含明确时区")
        payload = {
            "cells": [cell.to_dict() for cell in items],
            "updated_at": current.astimezone(timezone.utc).isoformat(),
            "version": int(
                hashlib.sha256(json.dumps(codes, ensure_ascii=False).encode("utf-8")).hexdigest()[:8],
                16,
            ),
        }
        self._store.set_setting(self._key(actor_id), payload)
        voters = self._voters()
        if str(actor_id) not in voters:
            voters.append(str(actor_id))
            self._store.set_setting(self.INDEX_KEY, voters)
        return items

    def my_vote(self, actor_id: str) -> tuple[GridCell, ...]:
        raw = self._store.get_setting(self._key(actor_id), None)
        if not isinstance(raw, Mapping):
            return ()
        cells_raw = raw.get("cells")
        if not isinstance(cells_raw, list):
            return ()
        result: list[GridCell] = []
        for item in cells_raw:
            if not isinstance(item, Mapping):
                continue
            try:
                result.append(
                    GridCell(
                        index=int(item.get("index") or 0),
                        name=str(item.get("name") or ""),
                        name_code=str(item.get("name_code") or ""),
                        resource_id=str(item.get("resource_id") or ""),
                        burst=str(item.get("burst") or ""),
                        element=str(item.get("element") or ""),
                    )
                )
            except (TypeError, ValueError):
                continue
        return tuple(result)

    def ranking(self, *, limit: int = 10) -> tuple[RankEntry, ...]:
        """聚合所有用户的最新投票；每名用户对同一角色只贡献 1 票。"""
        if not 1 <= limit <= 50:
            raise FavoriteGridError("榜单数量上限必须在 1–50")
        counts: dict[str, dict[str, Any]] = {}
        for actor in self._voters():
            for cell in self.my_vote(actor):
                entry = counts.setdefault(
                    cell.name_code,
                    {"name": cell.name, "votes": 0},
                )
                entry["votes"] += 1
        ordered = sorted(
            counts.items(),
            key=lambda pair: (-pair[1]["votes"], pair[0]),
        )
        return tuple(
            RankEntry(name=entry["name"], name_code=code, votes=entry["votes"])
            for code, entry in ordered[:limit]
        )

    def clear(self, actor_id: str) -> None:
        self._store.set_setting(self._key(actor_id), None)
        voters = [item for item in self._voters() if item != str(actor_id)]
        self._store.set_setting(self.INDEX_KEY, voters)


def render_ranking(entries: tuple[RankEntry, ...], *, limit: int = 10) -> str:
    lines = [f"【本命九宫格 · 人气榜 TOP {limit}】"]
    if not entries:
        lines.append("暂无投票。发送 /妮姬 九宫格 <九个妮姬> 即可参与。")
        return "\n".join(lines)
    for position, entry in enumerate(entries, 1):
        lines.append(f"{position}. {entry.name}（{entry.votes} 票）")
    lines.append("每人只计一票；再次提交会覆盖旧投票。")
    return "\n".join(lines)


__all__ = [
    "CELL_COUNT",
    "FavoriteGridError",
    "FavoriteRanking",
    "GridCell",
    "RankEntry",
    "render_ranking",
    "resolve_nine",
    "split_nine",
]
