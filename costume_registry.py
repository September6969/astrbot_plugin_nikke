# SPDX-License-Identifier: GPL-3.0-or-later
"""带所有者验证的已核验服装 Registry。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class VerifiedCostume:
    costume_id: str
    character_resource_id: str
    spine_asset_id: str
    costume_name: str
    verified_at: str


@dataclass(frozen=True, slots=True)
class CostumeResolveResult:
    ok: bool
    status: str  # "SUCCESS", "RESET_DEFAULT", "UNVERIFIED_COSTUME", "OWNER_MISMATCH"
    costume: VerifiedCostume | None = None
    message: str = ""


class CostumeRegistry:
    """加载并严格校验服装资产，防止未核验或所有者不匹配的皮肤生效。"""

    def __init__(self, asset_dir: str | Path | None = None):
        if asset_dir is None:
            asset_dir = Path(__file__).resolve().parent / "assets"
        else:
            asset_dir = Path(asset_dir).resolve()

        self.asset_dir = asset_dir
        self.costumes_path = self.asset_dir / "costumes.json"
        self._entries: list[VerifiedCostume] = []
        self._by_id: dict[str, VerifiedCostume] = {}
        self._load()

    def _load(self) -> None:
        if not self.costumes_path.is_file():
            return
        try:
            data = json.loads(self.costumes_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return

        entries = data.get("entries", []) if isinstance(data, dict) else []
        for row in entries:
            if not isinstance(row, dict):
                continue
            cid = str(row.get("costume_id", "")).strip()
            rid = str(row.get("character_resource_id", "")).strip()
            spine = str(row.get("spine_asset_id", "")).strip()
            name = str(row.get("costume_name", "")).strip()
            verified_at = str(row.get("verified_at", "")).strip()
            if not cid or not rid or not spine or not name:
                continue
            item = VerifiedCostume(cid, rid, spine, name, verified_at)
            self._entries.append(item)
            self._by_id[cid] = item

    @property
    def verified_count(self) -> int:
        return len(self._entries)

    def get_costumes_for_resource(self, resource_id: int | str | None) -> list[VerifiedCostume]:
        """查询指定角色 resource_id 拥有的所有已核验服装。"""
        if resource_id is None:
            return []
        target_rid = str(resource_id).strip()
        return [e for e in self._entries if e.character_resource_id == target_rid]

    def resolve(
        self,
        query: str | None,
        expected_resource_id: int | str | None = None,
    ) -> CostumeResolveResult:
        """根据输入值解析服装并进行所有者强核验。

        query 支持：
        - "默认" / "default" / "原皮" / "0" -> 重置为默认皮肤
        - costume_id（如 "10005", "20001", "80001"）
        - costume_name（如 "Classic Vacation", "White Promise", "Villain Racer"，大小写不敏感）
        """
        if not query:
            return CostumeResolveResult(
                ok=False,
                status="EMPTY_QUERY",
                message="请输入服装 ID 或名称，或输入“默认”恢复原皮。",
            )

        term = str(query).strip()
        if term.casefold() in {"默认", "default", "原皮", "0", "无"}:
            return CostumeResolveResult(
                ok=True,
                status="RESET_DEFAULT",
                costume=None,
                message="服装已恢复默认原皮。",
            )

        # 1. 查找匹配的服装条目（按 ID 或名称）
        matched: VerifiedCostume | None = self._by_id.get(term)
        if matched is None:
            term_fold = term.casefold()
            for entry in self._entries:
                if entry.costume_name.casefold() == term_fold:
                    matched = entry
                    break

        if matched is None:
            return CostumeResolveResult(
                ok=False,
                status="UNVERIFIED_COSTUME",
                message=f"未找到已核验服装：{query}。仅支持已登记核验的官方服装。",
            )

        # 2. 校验所有者
        if expected_resource_id is not None:
            expected_str = str(expected_resource_id).strip()
            if matched.character_resource_id != expected_str:
                return CostumeResolveResult(
                    ok=False,
                    status="OWNER_MISMATCH",
                    costume=matched,
                    message=f"服装 {matched.costume_name}（ID: {matched.costume_id}）不属于当前选择的角色。",
                )

        return CostumeResolveResult(
            ok=True,
            status="SUCCESS",
            costume=matched,
            message=f"服装已设置为：{matched.costume_name}（{matched.costume_id}）。",
        )
