"""文字与网页共享的竞技场应用入口。"""

import asyncio
from dataclasses import replace

from ..account.errors import CredentialExpiredError
from .models import ArenaRosterSnapshot
from .roster import apply_favorite_marks

SANDBOX_MARK_NOTE = "公开沙盒已包含全部珍藏形态，珍藏标记未使用。"


class ArenaApplication:
    def __init__(self, directory, analyzer, roster):
        self.directory = directory
        self.analyzer = analyzer
        self.roster = roster

    async def read_roster(self, actor_id: str) -> ArenaRosterSnapshot:
        try:
            return await asyncio.wait_for(self.roster.owned(actor_id), timeout=15)
        except CredentialExpiredError:
            status = "expired"
        except Exception:
            status = "unavailable"
        # 对外只返回状态，取消信号仍向上传播。
        return ArenaRosterSnapshot(frozenset(), status, 0, "", ("roster",))

    async def read_marked_roster(self, actor_id: str, marks: tuple[str, ...] = ()) -> ArenaRosterSnapshot:
        """读取个人名单并叠加本次手动珍藏标记；名单不可用时原样返回状态。"""
        snapshot = await self.read_roster(actor_id)
        if snapshot.status not in {"available", "partial"} or not marks:
            return snapshot
        return apply_favorite_marks(snapshot, marks, self.directory)

    async def analyze(self, text: str, *, actor_id: str = "", owned: bool = False):
        team_text, marks = self.directory.split_favorite_marks(text)
        enemy = self.directory.parse_team(team_text)
        snapshot = None
        if owned:
            snapshot = await self.read_marked_roster(actor_id, marks)
            if snapshot.status not in {"available", "partial"}:
                raise ValueError("个人角色库暂不可读取，请检查绑定。公开沙盒可用 /妮姬 竞技场 沙盒 <五人>。")
        # 纯 CPU 搜索最长约 1s，移出事件循环避免阻塞其他指令。
        result = await asyncio.to_thread(self.analyzer.analyze, enemy, snapshot)
        if marks and snapshot is None:
            result = replace(result, warnings=(*result.warnings, SANDBOX_MARK_NOTE))
        return result
