# SPDX-License-Identifier: GPL-3.0-or-later
"""战役历史通关阵容构建器。

遵循 contracts/campaign_history.md：
1. 错误码 1300017 统一映射为 UNAVAILABLE，文案“该关卡暂无可查询的历史阵容”；
2. 错误码 212000 映射为 RATE_LIMITED；
3. code == 0 且包含合法 list 时构建 AVAILABLE 状态；
4. 严格只使用响应自身的 tid/lv/combat/slot，不伪造历史皮肤；
5. 总战力为 5 人战力之和。
"""

from __future__ import annotations

import re
from typing import Any

from .campaign_history_models import ClearLineupStatus, StageClearMember, StageClearRecord
from .campaign_stage_resolver import CampaignStage
from .character_master_resolver import CharacterMasterResolver


def _strict_non_negative_int(value: Any) -> int:
    """只接受 JSON 整数或十进制整数字符串，拒绝布尔、小数和负数。"""
    if isinstance(value, bool):
        raise ValueError("布尔值不是数值字段")
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, str) and re.fullmatch(r"[0-9]+", value, flags=re.ASCII):
        parsed = int(value)
    else:
        raise ValueError("数值字段必须是整数")
    if parsed < 0:
        raise ValueError("数值字段不能为负数")
    return parsed


def _strict_costume_id(value: Any) -> int | str:
    """只保留可进入皮肤映射合同的标量，不把异常值当默认服装。"""
    if isinstance(value, bool):
        raise ValueError("布尔值不是皮肤字段")
    if type(value) is int:
        if value < 0:
            raise ValueError("皮肤字段不能为负数")
        return value
    if isinstance(value, str):
        candidate = value.strip()
        if candidate and re.fullmatch(r"[A-Za-z0-9_-]+", candidate, flags=re.ASCII):
            return candidate
    raise ValueError("皮肤字段格式异常")


class CampaignHistoryBuilder:
    def __init__(
        self,
        directory: list[dict] | None = None,
        master_resolver: CharacterMasterResolver | None = None,
    ):
        self._resolver = master_resolver or CharacterMasterResolver()
        self._directory_by_tid: dict[int, dict] = {}
        if directory:
            self.update_directory(directory)

    def update_directory(self, directory: list[dict]) -> None:
        self._directory_by_tid.clear()
        for item in directory:
            nc = item.get("name_code")
            if nc is not None:
                try:
                    self._directory_by_tid[int(nc)] = item
                except (ValueError, TypeError):
                    pass

    def build(
        self,
        stage: CampaignStage,
        response: dict[str, Any],
        commander_name: str = "",
        fetched_at: str = "",
        plugin_version: str = "",
    ) -> StageClearRecord:
        if not isinstance(response, dict):
            return StageClearRecord(
                mode=stage.mode,
                chapter=stage.chapter,
                stage_name=stage.name,
                stage_id=stage.stage_id,
                status=ClearLineupStatus.ERROR,
                status_message="历史阵容数据结构异常，请稍后重试",
                commander_name=commander_name,
                fetched_at=fetched_at,
                plugin_version=plugin_version,
            )

        code = response.get("code")
        if isinstance(code, bool) or not isinstance(code, int):
            return StageClearRecord(
                mode=stage.mode,
                chapter=stage.chapter,
                stage_name=stage.name,
                stage_id=stage.stage_id,
                status=ClearLineupStatus.ERROR,
                status_message="历史阵容数据结构异常，请稍后重试",
                commander_name=commander_name,
                fetched_at=fetched_at,
                plugin_version=plugin_version,
            )
        msg = str(response.get("msg") or "")

        if code == 1300017:
            return StageClearRecord(
                mode=stage.mode,
                chapter=stage.chapter,
                stage_name=stage.name,
                stage_id=stage.stage_id,
                status=ClearLineupStatus.UNAVAILABLE,
                status_message="该关卡暂无可查询的历史阵容",
                commander_name=commander_name,
                fetched_at=fetched_at,
                plugin_version=plugin_version,
            )

        if code == 212000:
            return StageClearRecord(
                mode=stage.mode,
                chapter=stage.chapter,
                stage_name=stage.name,
                stage_id=stage.stage_id,
                status=ClearLineupStatus.RATE_LIMITED,
                status_message="战役查询请求过频，请稍后再试",
                commander_name=commander_name,
                fetched_at=fetched_at,
                plugin_version=plugin_version,
            )

        if code != 0:
            return StageClearRecord(
                mode=stage.mode,
                chapter=stage.chapter,
                stage_name=stage.name,
                stage_id=stage.stage_id,
                status=ClearLineupStatus.ERROR,
                status_message=f"查询失败: {msg or code}",
                commander_name=commander_name,
                fetched_at=fetched_at,
                plugin_version=plugin_version,
            )

        data = response.get("data")
        raw_list = data.get("list") if isinstance(data, dict) else None

        if not isinstance(data, dict) or not isinstance(raw_list, list):
            return StageClearRecord(
                mode=stage.mode,
                chapter=stage.chapter,
                stage_name=stage.name,
                stage_id=stage.stage_id,
                status=ClearLineupStatus.ERROR,
                status_message="历史阵容数据结构异常，请稍后重试",
                commander_name=commander_name,
                fetched_at=fetched_at,
                plugin_version=plugin_version,
            )

        if len(raw_list) == 0:
            return StageClearRecord(
                mode=stage.mode,
                chapter=stage.chapter,
                stage_name=stage.name,
                stage_id=stage.stage_id,
                status=ClearLineupStatus.UNAVAILABLE,
                status_message="该关卡暂无可查询的历史阵容",
                commander_name=commander_name,
                fetched_at=fetched_at,
                plugin_version=plugin_version,
            )

        if len(raw_list) != 5:
            return StageClearRecord(
                mode=stage.mode,
                chapter=stage.chapter,
                stage_name=stage.name,
                stage_id=stage.stage_id,
                status=ClearLineupStatus.ERROR,
                status_message="历史阵容数据结构异常，请稍后重试",
                commander_name=commander_name,
                fetched_at=fetched_at,
                plugin_version=plugin_version,
            )

        members: list[StageClearMember] = []
        malformed = False
        required = {"tid", "lv", "combat", "slot"}

        for item in raw_list:
            if not isinstance(item, dict):
                malformed = True
                continue
            if not required.issubset(item):
                malformed = True
                continue
            try:
                tid = _strict_non_negative_int(item["tid"])
                level = _strict_non_negative_int(item["lv"])
                combat = _strict_non_negative_int(item["combat"])
                slot = _strict_non_negative_int(item["slot"])
                costume_id = _strict_costume_id(item["costume_id"]) if "costume_id" in item else None
                if tid == 0 or slot not in {1, 2, 3, 4, 5}:
                    raise ValueError("tid 或 slot 超出合同")
            except (ValueError, TypeError):
                malformed = True
                continue

            info = self._directory_by_tid.get(tid)
            if info:
                name_cn = info.get("name_cn", f"NIKKE {tid}")
                name_en = info.get("name_en", "")
                res_val = info.get("resource_id")
                resource_id = str(res_val) if res_val is not None else None
                name_code = info.get("name_code")
            else:
                char = self._resolver.resolve_battle_tid(tid)
                if char is not None:
                    name_cn = char.name_cn
                    name_en = char.name_en
                    resource_id = str(char.resource_id)
                    name_code = char.name_code
                else:
                    name_cn = f"NIKKE {tid}"
                    name_en = ""
                    resource_id = None
                    name_code = None

            members.append(
                StageClearMember(
                    tid=tid,
                    level=level,
                    combat=combat,
                    slot=slot,
                    name_cn=name_cn,
                    name_en=name_en,
                    resource_id=resource_id,
                    costume_id=costume_id,
                    name_code=name_code,
                )
            )

        members.sort(key=lambda m: m.slot)

        if (
            malformed
            or len(members) != 5
            or set(m.slot for m in members) != {1, 2, 3, 4, 5}
        ):
            return StageClearRecord(
                mode=stage.mode,
                chapter=stage.chapter,
                stage_name=stage.name,
                stage_id=stage.stage_id,
                status=ClearLineupStatus.ERROR,
                status_message="历史阵容数据结构异常，请稍后重试",
                commander_name=commander_name,
                fetched_at=fetched_at,
                plugin_version=plugin_version,
            )

        return StageClearRecord(
            mode=stage.mode,
            chapter=stage.chapter,
            stage_name=stage.name,
            stage_id=stage.stage_id,
            status=ClearLineupStatus.AVAILABLE,
            members=members,
            commander_name=commander_name,
            fetched_at=fetched_at,
            plugin_version=plugin_version,
        )

