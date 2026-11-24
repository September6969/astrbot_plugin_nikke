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
    "【UID 与我的妮姬】\n"
    "/妮姬 uid <UID> — 公开 UID 查询（上游缺失时明确说明）\n"
    "/妮姬 我的妮姬 资料 — 读取自己已绑定账号的非敏感资料\n"
    "/妮姬 我的妮姬 手工 <昵称>[,等级][,备注] — 保存本人手工资料（未验证）\n"
    "/妮姬 我的妮姬 手工 清空 — 清除手工资料\n"
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
            f"已保存本人手工资料：{profile.name}"
            + (f" · 等级 {profile.level}" if profile.level is not None else " · 等级未填写")
            + "\n该资料未验证，只用于本人下游展示，不参与权限判断。"
        )

    def _import_link(self, context: CommandContext) -> str:
        if not context.is_private_chat:
            return "请在私聊使用 /妮姬 我的妮姬 导入，获取只读导入网页入口。"
        web = getattr(self.services, "shiftypad_web", None)
        if web is None:
            return "ShiftyPad 只读导入尚未装配。"
        try:
            link = web.create_link(context.actor_id)
        except ValueError as exc:
            return str(exc)
        return (
            "打开以下短时网页完成 ShiftyPad 只读导入（10 分钟内有效，仅本人可用）：\n"
            + link
            + "\n\n只读导入不会获得登录或私有账号权限；数字 UID 不能直接查询所有账号，"
            "网页会优先要求官方 ShiftyPad 公开链接。原账号登录/扩展绑定不受影响。"
        )

    def _readonly_status(self, context: CommandContext) -> str:
        readonly = getattr(self.services, "shiftypad_readonly", None)
        if readonly is None:
            return "ShiftyPad 只读导入尚未装配。"
        status = readonly.status(context.actor_id)
        if status.get("status") == "unbound":
            return (
                "尚未建立 ShiftyPad 只读绑定。\n"
                "私聊发送 /妮姬 我的妮姬 导入 获取短时网页入口。"
            )
        binding = status.get("binding") or {}
        lines = [
            "【ShiftyPad 只读绑定】",
            f"昵称：{binding.get('nickname') or '未知'}",
            f"UID/区服：{binding.get('identity', {}).get('uid') or '未标注'}"
            f" / {binding.get('identity', {}).get('server') or '未标注'}",
            f"状态：{status.get('status')}",
            f"最近同步：{binding.get('last_sync_at') or '未知'}",
            f"只读角色快照：{binding.get('nikke_count') if binding.get('nikke_count') is not None else '未知'} 名"
            "（仅供只读查看，不替代 /妮姬 查询 练度 的登录能力）",
        ]
        if status.get("last_error"):
            lines.append("最近错误：" + str(status["last_error"]))
        lines.append("解绑或同步请使用同一个短时网页入口；不会影响原账号登录绑定。")
        return "\n".join(lines)

    async def _share_lookup(self, value: str) -> str:
        lookup = getattr(self.services, "share_lookup", None)
        if lookup is None:
            return "公开分享资料入口尚未装配。"
        if not value.strip():
            return "用法：/妮姬 我的妮姬 分享 <BlablaLink 公开分享 ID>（不是 UID，不要粘贴完整 URL）"
        profile = await lookup(value.strip())
        def shown(item: Any) -> str:
            return "未知" if item is None else str(item)
        return "\n".join(
            (
                "【公开分享资料】" + str(getattr(profile, "nickname", "未知")),
                "等级：" + shown(getattr(profile, "level", None))
                + " · 队伍总战力：" + shown(getattr(profile, "team_combat", None)),
                "角色数量：" + shown(getattr(profile, "nikke_count", None))
                + " · 同步器：" + shown(getattr(profile, "synchro_level", None)),
                "普通主线：" + str(getattr(profile, "normal_stage", "未知"))
                + " · 困难主线：" + str(getattr(profile, "hard_stage", "未知")),
                str(getattr(profile, "note", "")),
                "来源：" + str(getattr(profile, "source_url", "")),
            )
        )

    def _manual_status(self, context: CommandContext) -> str:
        profile = self.services.manual_profiles.load(context.actor_id)
        if profile is None:
            return "你还没有保存手工资料。用法：/妮姬 我的妮姬 手工 <昵称>[,等级][,备注]"
        return (
            f"本人手工资料：{profile.name}"
            + (f" · 等级 {profile.level}" if profile.level is not None else " · 等级未填写")
            + (f" · 备注 {profile.note}" if profile.note else "")
            + f"\n更新：{profile.updated_at} · 未验证，仅用于本人下游展示。"
        )

    async def _bound_profile(self, context: CommandContext) -> str:
        account = self._account(context)
        if account is None:
            return "尚未绑定账号；请私聊发送 /妮姬 账号 绑定，或使用 /妮姬 我的妮姬 手工。"
        profile = await self._load_profile(account)
        basic = profile.get("basic") if isinstance(profile, Mapping) else None
        if not isinstance(basic, Mapping):
            return "上游未返回账号资料（缺失）。"
        lines = [
            "【我的妮姬 · 已绑定资料】",
            f"UID：{account.get('game_uid') or '未知'}（仅用于本人识别，不构成所有权证明）",
            f"昵称：{basic.get('nickname') or basic.get('role_name') or '未知'}",
            f"指挥官等级：{basic.get('lv') if basic.get('lv') is not None else '未知'}",
            f"队伍总战力：{basic.get('team_combat') if basic.get('team_combat') is not None else '未知'}",
            "角色库入口：/妮姬 查询 练度（仅读取本人绑定账号）",
        ]
        return "\n".join(lines)


__all__ = ["ShiftypadCommandHandler"]
