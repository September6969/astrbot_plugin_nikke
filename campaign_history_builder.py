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

from typing import Any

from .campaign_history_models import ClearLineupStatus, StageClearMember, StageClearRecord
from .campaign_stage_resolver import CampaignStage


class CampaignHistoryBuilder:
    def __init__(self, directory: list[dict] | None = None):
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
        code = response.get("code")
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

        if not isinstance(raw_list, list) or len(raw_list) == 0:
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

        members: list[StageClearMember] = []
        for item in raw_list:
            if not isinstance(item, dict):
                continue
            try:
                tid = int(item.get("tid", 0))
                level = int(item.get("lv", 0))
                combat = int(item.get("combat", 0))
                slot = int(item.get("slot", 0))
            except (ValueError, TypeError):
                continue

            info = self._directory_by_tid.get(tid, {})
            name_cn = info.get("name_cn", f"NIKKE {tid}")
            name_en = info.get("name_en", "")
            resource_id = str(info.get("resource_id", tid))

            members.append(
                StageClearMember(
                    tid=tid,
                    level=level,
                    combat=combat,
                    slot=slot,
                    name_cn=name_cn,
                    name_en=name_en,
                    resource_id=resource_id,
                )
            )

        members.sort(key=lambda m: m.slot)

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

