# SPDX-License-Identifier: GPL-3.0-or-later
"""公开 UID 声明、ShiftyPad 只读导入、公开分享 ID 与手工资料命令用例（26）。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ...features.identity.public_profile import (
    UID_DISCLAIMER,
    lookup_public_uid,
    parse_manual_profile,
    render_public_uid,
)
from ._toolbox_shared import ToolboxDomainHandler
from .contracts import CommandContext

_UID_HELP = (
    "【UID 与个人档案】\n"
    "• /妮姬 uid <UID> — 说明 UID 查询范围\n"
    "• /妮姬 我的妮姬 资料 — 查看已绑定账号的基础资料\n"
    "• /妮姬 我的妮姬 手工 <昵称>[,等级][,备注] — 手动记一份个人档案\n"
    "• /妮姬 我的妮姬 手工 清空 — 清除手动档案\n"
    + UID_DISCLAIMER
)


class ShiftypadCommandHandler(ToolboxDomainHandler):
    """处理公开 UID、ShiftyPad 只读导入与我的妮姬资料命令。"""

    async def _uid(self, context: CommandContext, action: str, value: str) -> str:
        key = action.strip()
        if not key:
            return _UID_HELP
        if key in {"手工", "manual"}:
            return self._manual(context, value)
        if key in {"导入", "shiftypad", "只读导入"}:
            return self._import_link(context)
        if key in {"只读", "导入状态", "shiftypad状态"}:
            return self._readonly_status(context)
        if key in {"分享", "share"}:
            return await self._share_lookup(value)
        if key in {"手工状态", "manual_status"}:
            return self._manual_status(context)
        if key in {"资料", "profile"}:
            return await self._bound_profile(context)
        own_uid = None
        account = self._account(context)
        if account is not None:
            own_uid = str(account.get("game_uid") or "")
        return render_public_uid(lookup_public_uid(key, own_uid=own_uid))

    def _manual(self, context: CommandContext, value: str) -> str:
        if value.strip() in {"清空", "clear"}:
            self.services.manual_profiles.clear(context.actor_id)
            return "已清除本人手工资料。"
        name, level, note = parse_manual_profile(value)
        profile = self.services.manual_profiles.save(
            context.actor_id, name=name, level=level, note=note
        )
        return (
            f"已记下你的个人档案：{profile.name}"
            + (f" · Lv.{profile.level}" if profile.level is not None else " · 未填等级")
            + "\n（这是你手动填写的记录，仅自己可见）"
        )

    def _import_link(self, context: CommandContext) -> str:
        if not context.is_private_chat:
            return "请私聊我发送 /妮姬 我的妮姬 导入 获取链接。"
        web = getattr(self.services, "shiftypad_web", None)
        if web is None:
            return "该功能暂未开启。"
        try:
            link = web.create_link(context.actor_id)
        except ValueError as exc:
            return str(exc)
        return (
            "打开下面的短时链接导入 ShiftyPad 公开档案（10 分钟内有效，仅限本人）：\n"
            + link
            + "\n\n（只读取公开页信息，不会取得登录权限，也不会影响你原有的账号绑定）"
        )

    def _readonly_status(self, context: CommandContext) -> str:
        readonly = getattr(self.services, "shiftypad_readonly", None)
        if readonly is None:
            return "该功能暂未开启。"
        status = readonly.status(context.actor_id)
        if status.get("status") == "unbound":
            return (
                "你还没有导入过 ShiftyPad 公开档案。\n"
                "私聊发送 /妮姬 我的妮姬 导入 获取导入链接。"
            )
        binding = status.get("binding") or {}
        raw_status = str(status.get("status") or "")
        status_label = {
            "fresh": "正常",
            "stale": "已过期（建议重新导入）",
        }.get(raw_status, raw_status or "未知")
        lines = [
            "【ShiftyPad 公开档案】",
            f"昵称：{binding.get('nickname') or '未知'}",
            f"UID / 区服：{binding.get('identity', {}).get('uid') or '未标注'}"
            f" / {binding.get('identity', {}).get('server') or '未标注'}",
            f"档案状态：{status_label}",
            f"同步时间：{binding.get('last_sync_at') or '未知'}",
            f"记录角色数：{binding.get('nikke_count') if binding.get('nikke_count') is not None else '未知'} 名"
            "（查完整练度和词条请使用账号绑定后的 /妮姬 查询 练度）",
        ]
        if status.get("last_error"):
            lines.append("最近提示：" + str(status["last_error"]))
        web = getattr(self.services, "shiftypad_web", None)
        if web is not None and callable(getattr(web, "active", None)) and not web.active():
            lines.append("（管理员暂未开启档案同步入口，如需更新请联系管理员）")
        return "\n".join(lines)

    async def _share_lookup(self, value: str) -> str:
        enabled = getattr(self.services, "public_share_enabled", None)
        lookup = getattr(self.services, "share_lookup", None)
        if enabled is False or lookup is None:
            return (
                "管理员默认关闭了第三方公开分享查询。\n"
                "由于需要把你输入的分享 ID 发往第三方中转接口（nikke-api.pages.dev），默认不开启以保护隐私。"
            )
        tokens = [part for part in value.strip().split() if part]
        if not tokens:
            return (
                "用法：/妮姬 我的妮姬 分享 <公开分享 ID> 确认\n"
                "提示：请填写分享 ID（不是数字 UID，也不用贴完整网址）；查询时只会发送你输入的分享 ID，不会发送你的 QQ 或绑定信息。"
            )
        confirmed = False
        if len(tokens) >= 2 and tokens[-1].casefold() in {"确认", "confirm", "--confirm"}:
            confirmed = True
            share_id = tokens[0]
        else:
            share_id = tokens[0]
        if not confirmed:
            return (
                "即将向第三方公开转发接口（nikke-api.pages.dev）请求查询：\n"
                "• 只会发送你输入的公开分享 ID，不会附带 QQ 号或登录凭证\n"
                "• 该接口不是官方服务，分享 ID 也不代表账号归属\n"
                f"确认要查询请发送：/妮姬 我的妮姬 分享 {share_id} 确认"
            )
        profile = await lookup(share_id)
        def shown(item: Any) -> str:
            return "未知" if item is None else str(item)
        return "\n".join(
            (
                "【公开分享资料】" + str(getattr(profile, "nickname", "未知")),
                "等级：" + shown(getattr(profile, "level", None))
                + " · 总战力：" + shown(getattr(profile, "team_combat", None)),
                "角色数：" + shown(getattr(profile, "nikke_count", None))
                + " · 同步器：" + shown(getattr(profile, "synchro_level", None)),
                "主线：普通 " + str(getattr(profile, "normal_stage", "未知"))
                + " / 困难 " + str(getattr(profile, "hard_stage", "未知")),
                str(getattr(profile, "note", "")),
            )
        )

    def _manual_status(self, context: CommandContext) -> str:
        profile = self.services.manual_profiles.load(context.actor_id)
        if profile is None:
            return "你还没有保存手动档案。发送 /妮姬 我的妮姬 手工 <昵称>[,等级][,备注] 即可记下。"
        return (
            f"我的手动档案：{profile.name}"
            + (f" · Lv.{profile.level}" if profile.level is not None else " · 未填等级")
            + (f" · 备注 {profile.note}" if profile.note else "")
            + f"\n更新于 {profile.updated_at}（仅自己可见）"
        )

    async def _bound_profile(self, context: CommandContext) -> str:
        account = self._account(context)
        if account is None:
            return "尚未绑定账号，请私聊发送 /妮姬 账号 绑定，或使用 /妮姬 我的妮姬 手工。"
        profile = await self._load_profile(account)
        basic = profile.get("basic") if isinstance(profile, Mapping) else None
        if not isinstance(basic, Mapping):
            return "暂时没读到账号资料，请稍后再试。"
        lines = [
            "【我的资料】",
            f"昵称：{basic.get('nickname') or basic.get('role_name') or '未知'}",
            f"UID：{account.get('game_uid') or '未知'}",
            f"指挥官等级：{basic.get('lv') if basic.get('lv') is not None else '未知'}",
            f"队伍总战力：{basic.get('team_combat') if basic.get('team_combat') is not None else '未知'}",
            "💡 想看完整角色练度，请发 /妮姬 查询 练度",
        ]
        return "\n".join(lines)


__all__ = ["ShiftypadCommandHandler"]
