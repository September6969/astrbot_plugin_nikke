"""社区额外能力的本人授权、命令及既有调度回调。"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
import random

from ...core.privacy import safe_exception_message
from ...features.daily.action_models import AutomationStore, account_scope, binding_stamp
from ...features.daily.runner import DailyRunner
from .contracts import CommandResult, TextReply

_LOGGER = logging.getLogger(__name__)
_RECOVERY_USAGE = ("确认恢复只用于你已在官网核实过的未决浏览/点赞动作：确认后这些动作不会被补做或重放，"
                   "所在周期仍保持暂停，从下一个周期起恢复。\n确认无误请私聊发送：/妮姬 日常 任务 确认恢复 确认")


class CommunityAutomationHandler:
    def __init__(self, *, tasks, renewal, store: AutomationStore, config, send_notice=None,
                 sleep=asyncio.sleep, clock=None):
        self.tasks = tasks
        self.renewal = renewal
        self.store = store
        self.config = config
        self.send_notice = send_notice
        self.sleep = sleep
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    async def handle_tasks(self, context):
        if not context.is_private_chat:
            return self._text("请私聊使用 /妮姬 日常 任务，进度与账号异常仅向本人展示。")
        account = self._account(context)
        if not account:
            return self._text("尚未绑定账号，请先私聊 /妮姬 账号 绑定。")
        self._register_route(context, account)
        parts = context.parameters.get("value", "").split()
        if parts == ["状态"]:
            current = await self.tasks.status(account)
            return self._text(current.detail + self._saved(account, "community_actions"))
        if parts == ["执行"]:
            return self._text((await self.tasks.execute(account)).detail)
        if len(parts) == 2 and parts[0] == "自动":
            return self._preference(account, "community_actions", parts[1], "浏览及点赞")
        if parts and parts[0] == "确认恢复":
            return self._recovery(account, context, confirmed=parts[1:] == ["确认"])
        return self._text("用法：/妮姬 日常 任务 状态|执行|自动 开|关|确认恢复")

    def _recovery(self, account, context, *, confirmed: bool):
        """Decision 2A：仅账号本人在私聊中两步确认；记录操作人、时间与原 run_key。"""
        rows = self.tasks.recovery_candidates(account)
        if not rows:
            return self._text("没有需要确认的未决浏览/点赞动作。")
        if not confirmed:
            listing = "\n".join(f"• {row['status']}（记录于 {row['created_at']}）" for row in rows[:10])
            return self._text(f"待核实的未决动作 {len(rows)} 项：\n{listing}\n\n{_RECOVERY_USAGE}")
        return self._text(self.tasks.acknowledge_unknown(account, operator=context.actor_id).detail)

    async def handle_renewal(self, context):
        if not context.is_private_chat:
            return self._text("请私聊使用账号续期命令，账号异常仅向本人展示。")
        account = self._account(context)
        if not account:
            return self._text("尚未绑定账号，请先私聊 /妮姬 账号 绑定。")
        self._register_route(context, account)
        if context.parameters.get("action") == "自动续期":
            return self._preference(account, "session_renewal", context.parameters.get("value", ""), "实验性续期")
        if context.parameters.get("value", "").strip() == "状态":
            return self._text("实验性续期：只在候选凭证同账号登录验证后保存；尚未证明长期有效期延长。" + self._saved(account, "session_renewal"))
        if context.parameters.get("value", "").strip():
            return self._text("用法：/妮姬 账号 续期 [状态]；/妮姬 账号 自动续期 开|关")
        return self._text((await self.renewal.execute(account)).detail)

    async def run_automatic(self, *, stagger=False):
        if self.config.get("enable_daily_actions", False) is not True:
            return
        # 不沿用旧 auto_daily_enabled：两项新能力各自只读取新的本人授权。
        for snapshot in self.store.list_accounts(with_cookie=False):
            if not any(self._enabled(snapshot, c) for c in ("community_actions", "session_renewal")):
                continue
            if stagger:
                await self.sleep(random.uniform(0, 60))
            try:
                await self._automatic_account(snapshot)
            except asyncio.CancelledError:
                raise
            except Exception:
                # 单账号损坏不泄漏凭证，也不阻塞其他账号或既有签到。
                continue

    async def _automatic_account(self, snapshot):
        for capability, service in (("session_renewal", self.renewal), ("community_actions", self.tasks)):
            account = self.store.get_account(str(snapshot["qq_id"]))
            if (not account or binding_stamp(account) != binding_stamp(snapshot)
                    or not self._enabled(account, capability)):
                continue
            result = await service.execute(account, automatic=True)
            stop = result.status in {"unknown_after_action", "validation_failed", "wrong_account", "rejected",
                    "rate_limited", "binding_changed", "saved_cache_error", "busy_or_interrupted", "stopped"}
            if stop:
                day = self.clock().astimezone(timezone.utc).date().isoformat()
                self.store.set_setting(f"community_automation:halt:{account_scope(account)}:{day}", True)
            if result.status not in {"completed", "validated", "not_due", "disabled", "frequency_limited"}:
                try:
                    await self._notify(account, capability, result)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    # 通知失败不阻断后续能力与其他账号；通知自身已按幂等键防重。
                    _LOGGER.warning("[NIKKE] 社区自动任务异常通知失败：%s", safe_exception_message(exc))
            if stop:
                return

    def _preference(self, account, capability, value, label):
        if value not in {"开", "关"}:
            return self._text("请使用 开 或 关；两项新能力默认关闭，旧日常授权不会自动扩大范围。")
        enabled = value == "开"
        self.store.set_setting(f"{capability}:auto:{account['qq_id']}", binding_stamp(account) if enabled else None)
        suffix = "全局写操作关闭，当前不会提交。" if not self.config.get("enable_daily_actions", False) else "成功静默，需处理时仅私聊一次。"
        return self._text(f"{label}自动执行已{'开启' if enabled else '关闭'}。{suffix}")

    def _enabled(self, account, capability):
        return self.store.get_setting(f"{capability}:auto:{account['qq_id']}", None) == binding_stamp(account)

    def register_route(self, context, account):
        """统一登记私聊异常通知路由：签到汇总与社区额外能力共用同一次登记。"""
        if not (context.is_private_chat and context.conversation_id):
            return
        self.store.set_setting(f"daily_private:{context.actor_id}", {
            "identity": DailyRunner.daily_identity(account), "conversation": context.conversation_id})
        try:
            stamp = binding_stamp(account)
        except ValueError:
            return
        self.store.set_setting(f"community_automation:private:{context.actor_id}", {
            **stamp, "conversation": context.conversation_id})

    _register_route = register_route

    async def _notify(self, account, capability, result):
        route = self.store.get_setting(f"community_automation:private:{account['qq_id']}", {})
        if (not isinstance(route, dict) or not self.send_notice or not route.get("conversation")
                or any(route.get(k) != v for k, v in binding_stamp(account).items())):
            return
        current = self.store.get_account(str(account["qq_id"]), with_cookie=False)
        if not current or binding_stamp(current) != binding_stamp(account) or not self._enabled(current, capability):
            return
        day = self.clock().astimezone(timezone.utc).date().isoformat()
        key = f"community-automation-notice:v1:{account_scope(account)}:{day}:{capability}"
        if not self.store.claim_run(key, str(account["qq_id"]), "community_automation_notice", initial_status="DISPATCH_INTENT"):
            return
        try:
            sent = await asyncio.wait_for(self.send_notice(route["conversation"], "【社区自动任务需处理】\n" + result.detail), 10)
            self.store.finish_run(key, "SENT" if sent is not False else "FAILED", "异常私聊发送已处理，不重复发送")
        finally:
            if (self.store.get_run(key) or {}).get("status") == "DISPATCH_INTENT":
                self.store.finish_run(key, "UNKNOWN_AFTER_ACTION", "通知结果未知，不重复发送")

    def _saved(self, account, capability):
        previous = self.store.get_setting(f"{capability}:last:{account_scope(account)}", {})
        if (isinstance(previous, dict) and previous.get("generation")
                and previous["generation"] != binding_stamp(account)["generation"]):
            previous = {}  # 来自旧绑定代次的结果不再作为当前告警展示
        enabled = "开" if self._enabled(account, capability) else "关"
        detail = f"\n独立自动开关：{enabled}" + ("\n最近执行：" + str(previous["detail"]) if isinstance(previous, dict) and previous.get("detail") else "")
        if capability == "session_renewal":
            scope = account_scope(account)
            revision = str(account.get("binding_revision") or "").strip()
            if revision:
                run = self.store.get_run(f"session-renewal:v1:{scope}:{revision}")
                pending = [run] if run and run["status"] in {"DISPATCH_INTENT", "UNKNOWN_AFTER_ACTION"} else []
            else:
                prefix = f"session-renewal:v1:{scope}:"
                pending = [r for r in self.store.list_runs(action="session_renewal")
                           if r["run_key"].startswith(prefix) and r["status"] in {"DISPATCH_INTENT", "UNKNOWN_AFTER_ACTION"}]
            if pending:
                detail += "\n存在未决续期尝试，此凭证不自动重试；请核实或重新登录绑定。"
        return detail

    def _account(self, context):
        return self.store.get_account(context.actor_id)

    @staticmethod
    def _text(text):
        return CommandResult((TextReply(text),))
