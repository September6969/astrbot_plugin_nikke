"""浏览和点赞逐项执行，按官方周期共享持久预算；未决结果不重发。"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import hashlib
import json

from .action_models import (ACKNOWLEDGED_UNKNOWN, LEASE_TIMEOUT_SECONDS, ActionGateway, AccountLock,
                            AutomationStore, KINDS, LABELS, OperationResult, account_scope, binding_stamp,
                            still_authorized, account_execution_lease, lease_key)


UNRESOLVED = {"DISPATCH_INTENT", "DISPATCHED", "UNKNOWN_AFTER_ACTION"}
# 所在周期内仍阻断新动作的状态：未决 + 已人工核实（只放行之后的新周期）。
PERIOD_BLOCKING = UNRESOLVED | {ACKNOWLEDGED_UNKNOWN}
# 确认未发送的记录保留去重与审计，但不占用周期预算。
BUDGET_EXEMPT = frozenset({"NOT_SENT"})
# 写前意图超过该秒数仍未推进，才视为进程中断遗留，可纳入人工核实。
INTENT_STALE_AFTER_SECONDS = 120
RECOVERY_AUDIT_LIMIT = 50


class CommunityTaskService:
    def __init__(self, *, gateway: ActionGateway, store: AutomationStore, config,
                 account_lock: AccountLock, sleep=asyncio.sleep, clock=None):
        self.gateway = gateway
        self.store = store
        self.config = config
        self.account_lock = account_lock
        self.sleep = sleep
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    async def status(self, account) -> OperationResult:
        try:
            await self.gateway.identity(account)
            tasks = await self.gateway.progress(account)
            return OperationResult("status", self._describe(tasks) + self._pending_description(account))
        except asyncio.CancelledError:
            raise
        except Exception:
            return OperationResult("unavailable", "浏览、点赞状态未知：登录、身份或响应合同未通过检查；未执行动作。")

    async def execute(self, account, *, automatic=False) -> OperationResult:
        async with self.account_lock(account):
            with account_execution_lease(self.store, account) as acquired:
                if not acquired:
                    return OperationResult("busy_or_interrupted", "同账号仍在执行或上次进程异常终止；请只读查询状态，核实占用前不提交新动作。")
                result = await self._execute_locked(account, automatic)
            self.store.set_setting(f"community_actions:last:{account_scope(account)}", {
                "status": result.status, "detail": result.detail,
                "generation": binding_stamp(account)["generation"],
                "checked_at": self.clock().astimezone(timezone.utc).isoformat()})
            return result

    async def _execute_locked(self, account, automatic):
        if not self._allowed(account, automatic):
            return OperationResult("disabled", "浏览、点赞已关闭或绑定已变化，未执行。")
        lines = []
        try:
            await self.gateway.identity(account)
            tasks = await self.gateway.progress(account)
            candidates = None
            for kind in KINDS:
                task = tasks.get(kind)
                if task is None:
                    lines.append(f"{LABELS[kind]}：状态缺失或合同变化，已暂停")
                    continue
                if task.completed:
                    lines.append(f"{LABELS[kind]}：已完成 {task.current}/{task.target}；{task.reward}")
                    continue
                scope = self._scope(account, task)
                rows = self._rows(scope)
                if any(json.loads(row["detail"]).get("target") != task.target for row in rows):
                    lines.append(f"{LABELS[kind]}：周期内目标发生变化，已暂停并保留原预算")
                    continue
                unresolved = self._unresolved(account, kind, task.period)
                if unresolved:
                    # 不能用聚合进度把重启前动作归因到某篇帖子；本周期仅只读恢复。
                    lines.append(f"{LABELS[kind]}：{task.current}/{task.target}，存在未决动作，只查询不补做；跨周期也需先核实旧动作影响")
                    continue
                if candidates is None:
                    candidates = await self.gateway.candidates(account)
                detail = await self._run_task(account, task, candidates, automatic)
                lines.append(detail.detail)
                if detail.status in {"stopped", "disabled", "unknown_after_action"}:
                    return OperationResult(detail.status, "\n".join(lines))
            final = await self.gateway.progress(account)
            status = "completed" if all(tasks.get(k) and final.get(k) and final[k].completed and final[k].period == tasks[k].period for k in KINDS) else "incomplete"
            # 最终状态来自运行内已核验的逐项进度，不把接口接受冒充完成。
            return OperationResult(status, "\n".join(lines) + "\n最终只读核验：\n" + self._describe(final))
        except asyncio.CancelledError:
            raise
        except Exception:
            return OperationResult("stopped", "\n".join(lines + ["登录失效、限流、验证要求或响应异常，已停止；未发送额外领取请求。 "]))

    async def _run_task(self, account, task, candidates, automatic):
        scope = self._scope(account, task)
        used = [row for row in self._rows(scope) if row["status"] not in BUDGET_EXEMPT]
        limit = min(task.target, int(self.config.get("community_cycle_action_budget", 10)))
        run_limit = int(self.config.get("community_run_action_budget", 5))
        submitted = 0
        current = task
        seen = set()
        for post in candidates:
            if current.completed or submitted >= run_limit or len(used) + submitted >= limit:
                break
            if post.post_id in seen:
                continue
            seen.add(post.post_id)
            key = scope + ":" + hashlib.sha256(post.post_id.encode()).hexdigest()
            if self.store.get_run(key):
                continue
            if task.kind == "like":
                if post.liked is not False or await self.gateway.liked(account, post.post_id) is not False:
                    continue
            # 延迟后再检查授权、周期、来源进度；不让已排队动作绕过关闭操作。
            await self.sleep(max(2, int(self.config.get("community_action_interval_seconds", 5))))
            if not self._allowed(account, automatic):
                return OperationResult("disabled", f"{LABELS[task.kind]}：执行前授权关闭或绑定变化，已停止")
            fresh = (await self.gateway.progress(account)).get(task.kind)
            if fresh is None or fresh.period != task.period or fresh.target != task.target:
                return OperationResult("stopped", f"{LABELS[task.kind]}：周期或任务合同变化，已停止")
            if fresh.completed:
                current = fresh
                break
            if fresh.current != current.current:
                return OperationResult("stopped", f"{LABELS[task.kind]}：检测到外部进度变化，已停止并保留预算")
            if task.kind == "like" and await self.gateway.liked(account, post.post_id) is not False:
                continue
            result, updated = await self._one_action(account, fresh, post.post_id, scope, key, limit, automatic)
            if updated is not None:
                current = updated
            if result.status != "verified":
                return result
            submitted += 1
        detail = (f"{LABELS[task.kind]}：{'已完成' if current.completed else '未完成'} {current.current}/{current.target}；"
                  f"本次核验入账 {submitted} 次；{'预算已用尽或候选不足；' if not current.completed else ''}{current.reward}")
        return OperationResult("completed" if current.completed else "incomplete", detail)

    async def _one_action(self, account, task, post_id, scope, key, limit, automatic):
        intent = {"post_id": post_id, "before": task.current, "target": task.target,
                  "request": "intent", "progress": "unverified"}
        # 账号锁之外仍使用事务预算，保护多绑定、多实例及重启后的同账号竞争。
        if not self.store.reserve_run(scope, key, str(account["qq_id"]), "community_action", limit=limit,
                blocking_statuses=PERIOD_BLOCKING, initial_status="DISPATCH_INTENT", detail=json.dumps(intent),
                budget_exempt_statuses=BUDGET_EXEMPT):
            return OperationResult("stopped", f"{LABELS[task.kind]}：已有记录、未决动作或周期预算不足，未提交"), None
        try:
            period = "community-utc:" + self.clock().astimezone(timezone.utc).date().isoformat()
            if not self._allowed(account, automatic) or task.period != period:
                intent["request"] = "not_sent"
                intent["reason"] = "提交前关闭授权或周期变化；预算保留"
                self.store.finish_run(key, "NOT_SENT", json.dumps(intent))
                return OperationResult("disabled", "授权已关闭，未提交"), None
            await self.gateway.dispatch(account, task.kind, post_id)
            intent["request"] = "accepted"
            self.store.finish_run(key, "DISPATCHED", json.dumps(intent))
            updated = await self._verify(account, task)
            if updated is not None:
                intent["progress"] = "increased_by_one"
                self.store.finish_run(key, "VERIFIED", json.dumps(intent))
                return OperationResult("verified", "来源进度已增加"), updated
            return OperationResult("unknown_after_action", f"{LABELS[task.kind]}：请求已接受，进度未核实；本周期暂停补做"), None
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # 超时或断线后仅查询；即使聚合进度增加也不据此重发或补做。
            if isinstance(exc, (TimeoutError, ConnectionError)) or getattr(exc, "outcome_unknown", False):
                try:
                    await self.gateway.progress(account)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    pass
            return OperationResult("unknown_after_action", f"{LABELS[task.kind]}：提交结果未知，已停止；之后仅只读核验"), None
        finally:
            if (self.store.get_run(key) or {}).get("status") in {"DISPATCH_INTENT", "DISPATCHED"}:
                self.store.finish_run(key, "UNKNOWN_AFTER_ACTION", json.dumps(intent))

    async def _verify(self, account, task):
        for attempt in range(3):
            if attempt:
                await self.sleep(2)
            current = (await self.gateway.progress(account)).get(task.kind)
            if current is None or current.period != task.period or current.target != task.target:
                return None
            if current.current == task.current + 1:
                return current
            if current.current != task.current:
                return None
        return None

    def _allowed(self, account, automatic):
        return still_authorized(self.store, self.config, account, "community_actions", automatic)

    @staticmethod
    def _scope(account, task):
        # 不含绑定代次，重绑或同账号多绑定不能重获本周期预算。
        return f"community-actions:v1:{account_scope(account)}:{task.period}:{task.kind}"

    def _rows(self, scope):
        return [r for r in self.store.list_runs(action="community_action") if r["run_key"].startswith(scope + ":")]

    def _unresolved(self, account, kind, period=None):
        """未决动作跨周期阻断；已人工核实的记录只在其所在周期内继续阻断。"""
        prefix = f"community-actions:v1:{account_scope(account)}:"
        current = f"{prefix}{period}:{kind}:" if period else None
        return [r for r in self.store.list_runs(action="community_action")
                if r["run_key"].startswith(prefix) and f":{kind}:" in r["run_key"]
                and (r["status"] in UNRESOLVED
                     or (current and r["status"] == ACKNOWLEDGED_UNKNOWN and r["run_key"].startswith(current)))]

    def _pending_description(self, account):
        lines = [f"{LABELS[kind]}：存在未决动作，停止补做，需先核实旧动作影响。" for kind in KINDS if self._unresolved(account, kind)]
        if lines:
            lines.append("在官网核实这些动作的实际结果后，可私聊发送 /妮姬 日常 任务 确认恢复 查看处理方式。")
        lease = self.store.get_run(lease_key(account)) or {}
        if lease.get("status") == "LEASED":
            minutes = LEASE_TIMEOUT_SECONDS // 60
            lines.append(f"执行占用尚未释放：可能正在运行或进程异常退出；超过 {minutes} 分钟未释放会自动回收，期间仅允许查询。")
        return "\n" + "\n".join(lines) if lines else ""

    def recovery_candidates(self, account):
        """可人工核实的未决动作：结果未知，或写前意图已超过陈旧阈值（进程中断遗留）。"""
        prefix = f"community-actions:v1:{account_scope(account)}:"
        now = int(self.clock().timestamp())
        return [r for r in self.store.list_runs(action="community_action")
                if r["run_key"].startswith(prefix) and r["status"] in UNRESOLVED
                and (r["status"] == "UNKNOWN_AFTER_ACTION"
                     or now - int(r.get("created_at") or now) >= INTENT_STALE_AFTER_SECONDS)]

    def acknowledge_unknown(self, account, *, operator: str) -> OperationResult:
        """本人显式核实后解除未决阻断：只放行之后的新周期，绝不补跑或重放历史动作。"""
        lease = self.store.get_run(lease_key(account)) or {}
        if lease.get("status") == "LEASED":
            return OperationResult("busy_or_interrupted", "同账号仍有执行占用，暂不能确认恢复；请稍后再试。")
        rows = self.recovery_candidates(account)
        if not rows:
            return OperationResult("nothing", "没有需要确认的未决动作。")
        at = self.clock().astimezone(timezone.utc).isoformat()
        confirmed = []
        for row in rows:
            audit = {"acknowledged_by": str(operator), "acknowledged_at": at,
                     "original_run_key": row["run_key"], "previous_status": row["status"],
                     "replayed": False}
            stale = None if row["status"] == "UNKNOWN_AFTER_ACTION" else INTENT_STALE_AFTER_SECONDS
            if self.store.transition_run(row["run_key"], from_statuses={row["status"]}, to_status=ACKNOWLEDGED_UNKNOWN,
                                         detail=json.dumps(audit, ensure_ascii=False), stale_after=stale):
                confirmed.append(audit)
        key = f"community_automation:recovery_audit:{account_scope(account)}"
        history = self.store.get_setting(key, [])
        history = (history if isinstance(history, list) else []) + confirmed
        self.store.set_setting(key, history[-RECOVERY_AUDIT_LIMIT:])
        return OperationResult("acknowledged", f"已确认 {len(confirmed)} 项未决动作并记录审计。"
                               "这些动作不会被补做或重放；所在周期仍保持暂停，从下一个周期起恢复。")

    @staticmethod
    def _describe(tasks):
        lines = ["社区浏览与点赞（UTC零点／北京时间08:00刷新）"]
        for kind in KINDS:
            task = tasks.get(kind)
            lines.append(f"{LABELS[kind]}：{task.current}/{task.target}，{'已完成' if task.completed else '未完成'}；{task.reward}"
                         if task else f"{LABELS[kind]}：状态未知，写操作暂停")
        return "\n".join(lines)
