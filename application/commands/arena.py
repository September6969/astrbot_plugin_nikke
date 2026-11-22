"""竞技场命令与私聊角色库边界。"""

import asyncio

from ...features.arena.presentation import analysis_text, three_team_text
from ...features.arena.models import ArenaThreeTeamPlan, MODEL_VERSION
from ...features.arena.optimizer import ThreeTeamOptimizer
from .contracts import CommandContext, CommandResult, TextReply, ImageReply

HELP = (
    "【竞技场】\n"
    "/妮姬 竞技场 解队 红莲/豺狼/布兰儿/桑迪/特蕾娜\n"
    "/妮姬 竞技场 沙盒 <五人>\n"
    "/妮姬 竞技场 我的\n"
    "/妮姬 竞技场 数据状态\n"
    "私聊解队按已确认持有过滤，群聊解队使用公开沙盒。\n"
    "角色按 P1–P5，用 /、顿号或逗号分隔。"
)


class ArenaCommandHandler:
    def __init__(self, application, *, enabled: bool = False, web_routes=None, render=None):
        self.application = application
        self.enabled = enabled
        self.web_routes = web_routes
        self.render = render
        self._render_status = "未尝试" if render else "未装配"

    async def handle(self, context: CommandContext) -> CommandResult:
        if not self.enabled:
            return CommandResult((TextReply("竞技场功能当前未启用。"),))
        action = context.parameters.get("action", "").strip()
        text = context.parameters.get("value", "")
        try:
            result = await self._handle(context, action, text)
        except ValueError as exc:
            result = str(exc)
        except Exception:
            result = "竞技场查询暂不可用，请稍后重试。"
        if isinstance(result, str):
            return CommandResult((TextReply(result),))
        text = three_team_text(result) if isinstance(result, ArenaThreeTeamPlan) else analysis_text(result)
        has_suggestions = result.teams if isinstance(result, ArenaThreeTeamPlan) else result.recommendations
        if self.render and has_suggestions:
            try:
                page = "arena_three_teams" if isinstance(result, ArenaThreeTeamPlan) else "arena_matchup"
                rendered = await self.render(page, result)
                paths = (rendered,) if isinstance(rendered, str) else rendered
                if isinstance(paths, (list, tuple)) and paths and all(
                    isinstance(path, str) and path.strip() for path in paths
                ):
                    self._render_status = "最近一次成功"
                    return CommandResult(tuple(ImageReply(path) for path in paths))
            except Exception:
                pass
            self._render_status = "最近一次回退文本"
        return CommandResult((TextReply(text),))

    async def _handle(self, context: CommandContext, action: str, text: str):
        if action in {"", "帮助", "help"}:
            extra = ""
            if self.web_routes and self.web_routes.active():
                extra = ("\n/妮姬 竞技场 编辑 或 三队（私聊获取临时网页）"
                         "\n/妮姬 竞技场 结果（私聊回查本人最近网页结果）")
            return HELP + extra
        if action in {"编辑", "edit", "三队", "three", "结果", "result"}:
            if not context.is_private_chat:
                return "请先私聊机器人，再使用编辑、三队或结果回查命令。"
            if self.web_routes is None or not self.web_routes.active():
                return "竞技场网页当前未启用，单队可继续使用文字解队。"
            if action in {"结果", "result"}:
                result = self.web_routes.latest(context.actor_id)
                return result if result is not None else "本人最近两小时内暂无网页分析结果。"
            mode = "three" if action in {"三队", "three"} else "single"
            return "临时编辑链接，15 分钟内首次进入有效。\n" + self.web_routes.link(context.actor_id, mode)
        if action in {"数据状态", "status"}:
            data = self.application.analyzer
            stats = data.statistics
            statistics_status = stats.status if stats else "disabled"
            listener, sessions = self.web_routes.diagnostics() if self.web_routes else ("未装配", "未装配")
            return (f"模型 {MODEL_VERSION}\n模板 {len(data.templates)} 组\n"
                    f"已映射 {len(data.parameters)} 个充能曲线\n"
                    f"来源 {data.provenance.source}\n版本 {data.provenance.version}\n"
                    f"规则快照日期 {data.snapshot_date or '未知'}\n静态 RL 基线，未知个人配置。\n"
                    f"再入延迟及全阶段连续爆裂待验证。\n历史统计 {statistics_status}\n"
                    f"网页 {listener}\n会话存储 {sessions}\n图片输出 {self._render_status}")
        if action in {"我的", "my"}:
            if not context.is_private_chat:
                return "请私聊发送 /妮姬 竞技场 我的，查看本人角色库状态。"
            snapshot = await self.application.read_roster(context.actor_id)
            hint = "\n请重新绑定后查询。" if snapshot.status == "expired" else ""
            return (f"角色库状态 {snapshot.status}\n已映射 {len(snapshot.keys)} 人\n"
                    f"未映射 {snapshot.unmapped} 项\n读取时间 {snapshot.fetched_at}\n"
                    "缺失 " + "、".join(snapshot.missing_fields) + hint)
        if action in {"解队", "沙盒", "solve", "sandbox"}:
            owned = context.is_private_chat and action not in {"沙盒", "sandbox"}
            return await self.application.analyze(text, actor_id=context.actor_id, owned=owned)
        if action == "三队导入":
            lines = text.strip().splitlines()
            if len(lines) != 3:
                raise ValueError("三队导入需要三行，每行用 / 分隔五人。")
            teams = tuple(self.application.directory.parse_team(line) for line in lines)
            available = None
            if context.is_private_chat:
                available = await self.application.read_roster(context.actor_id)
                if available.status not in {"available", "partial"}:
                    raise ValueError("请检查绑定后使用个人三队导入，或在网页手动选择角色范围。")
            optimizer = ThreeTeamOptimizer(self.application.analyzer)
            return await asyncio.to_thread(optimizer.solve, teams, available)
        return HELP
