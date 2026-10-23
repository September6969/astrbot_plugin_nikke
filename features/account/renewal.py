"""实验性续期：验证同一账号后原子提交，未知请求不重试。"""
from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import datetime, timezone
import time
from typing import Any, Protocol

from ..daily.action_models import (AccountLock, AutomationStore, OperationResult, account_scope,
                                  still_authorized, account_execution_lease)
from .renewal_errors import RenewalFailure


class RenewalGateway(Protocol):
    async def identity(self, account: Mapping[str, Any]) -> str: ...
    async def request_candidate(self, account: Mapping[str, Any], now: float) -> tuple[str, dict[str, Any]]: ...
    def invalidate(self, account: Mapping[str, Any]) -> None: ...


class SessionRenewalService:
    def __init__(self, *, gateway: RenewalGateway, store: AutomationStore, config,
                 account_lock: AccountLock, preflight, clock=time.time):
        self.gateway = gateway
        self.store = store
        self.config = config
        self.account_lock = account_lock
        self.preflight = preflight
        self.clock = clock

    async def execute(self, account, *, automatic=False):
        async with self.account_lock(account):
            with account_execution_lease(self.store, account) as acquired:
                if not acquired:
                    return OperationResult("busy_or_interrupted", "同账号仍在执行或上次进程异常终止；核实占用前不提交续期。")
                result = await self._execute_locked(account, automatic)
            self.store.set_setting(f"session_renewal:last:{account_scope(account)}", {
                "status": result.status, "detail": result.detail, "checked_at": int(self.clock())})
            return result

    async def _execute_locked(self, account, automatic):
        if not still_authorized(self.store, self.config, account, "session_renewal", automatic):
            return OperationResult("disabled", "续期写操作已关闭或绑定已变化。")
        try:
            self.preflight(account, self.clock())
        except ValueError as exc:
            # 预检只允许内部固定错误，不回显上游响应或原始凭证。
            return OperationResult("unavailable", str(exc))
        if automatic and not self._due(account):
            return OperationResult("not_due", "到期信息不可靠或尚未进入续期窗口，未试探。")
        scope = account_scope(account)
        revision = str(account.get("binding_revision") or "")
        key = f"session-renewal:v1:{scope}:{revision}"
        if self.store.get_run(key):
            return OperationResult("previous_attempt", "此凭证已有续期尝试记录；未知结果不重试，请查询状态或重新登录绑定。")
        try:
            before = await self.gateway.identity(account)
            if not still_authorized(self.store, self.config, account, "session_renewal", automatic):
                return OperationResult("disabled", "续期提交前已关闭或绑定变化。")
            return await self._submit(account, key, before, automatic)
        except asyncio.CancelledError:
            raise
        except Exception:
            return OperationResult("unavailable", "续期前只读登录或身份检查失败，保留原凭证；可能需要重新登录。")

    async def _submit(self, account, key, identity, automatic):
        # 每账号任意绑定共享24小时预算；重绑不能绕过频率上限。
        scope = "session-renewal-window:v1:" + account_scope(account)
        runs = [r for r in self.store.list_runs(action="session_renewal_window") if r["run_key"].startswith(scope + ":")]
        if any(self.clock() - r["created_at"] < 86400 for r in runs):
            return OperationResult("frequency_limited", "该账号24小时内已尝试续期，保留原凭证。")
        day = datetime.fromtimestamp(self.clock(), timezone.utc).date().isoformat()
        if not self.store.claim_run(scope + ":" + day, str(account["qq_id"]), "session_renewal_window", initial_status="DISPATCH_INTENT"):
            return OperationResult("frequency_limited", "该账号已有本轮续期记录，未重复提交。")
        if not self.store.claim_run(key, str(account["qq_id"]), "session_renewal", initial_status="DISPATCH_INTENT"):
            return OperationResult("previous_attempt", "此凭证已有提交记录，未重复提交。")
        committed = False
        try:
            cookie, material = await self.gateway.request_candidate(account, self.clock())
            candidate = {**account, "cookie": cookie, "session_material": material}
            try:
                after = await self.gateway.identity(candidate)
            except Exception:
                self.store.finish_run(key, "REJECTED", "候选登录验证失败；保留原凭证")
                return OperationResult("validation_failed", "候选凭证未通过只读登录检查，保留原凭证；不声称续期成功。")
            if after != identity:
                self.store.finish_run(key, "REJECTED", "候选凭证身份不一致；保留原凭证")
                return OperationResult("wrong_account", "候选凭证身份不一致，保留原凭证。")
            if not still_authorized(self.store, self.config, account, "session_renewal", automatic):
                return OperationResult("binding_changed", "绑定已变化或写操作关闭，候选凭证未保存。")
            try:
                replaced = self.store.replace_session(account, cookie, material)
            except Exception:
                self.store.finish_run(key, "STORAGE_FAILED", "原子加密保存失败；原凭证保留")
                return OperationResult("storage_failed", "候选凭证加密或原子保存失败，原凭证保留。")
            if not replaced:
                return OperationResult("binding_changed", "绑定代次已变化，候选凭证未覆盖当前绑定。")
            committed = True
            self.gateway.invalidate(account)
            self.store.finish_run(key, "VALIDATED", "新 Cookie 登录验证通过；长期有效期延长未证实")
            return OperationResult("validated", "实验性续期：新 Cookie 已通过同账号登录检查并加密保存；尚未证明有效期延长，仍可能需要重新登录。")
        except asyncio.CancelledError:
            raise
        except RenewalFailure as exc:
            self.store.finish_run(key, "UNKNOWN_AFTER_ACTION" if exc.unknown else "REJECTED", exc.detail)
            return OperationResult(exc.status, exc.detail)
        except Exception:
            if committed:
                return OperationResult("saved_cache_error", "候选凭证已通过验证并保存；缓存清理或执行记录更新失败，请重新查询，未证明有效期延长。")
            return OperationResult("unknown_after_action", "续期响应、候选验证或保存未完成；原凭证未被候选覆盖。请求结果未知时不重试。")
        finally:
            if (self.store.get_run(key) or {}).get("status") == "DISPATCH_INTENT":
                self.store.finish_run(key, "UNKNOWN_AFTER_ACTION", "续期结果未确认，不自动重试")

    def _due(self, account):
        material = account.get("session_material") or {}
        cookies = [c for c in material.get("cookies", []) if c.get("name") == "game_token"]
        if len(cookies) != 1 or type(cookies[0].get("expirationDate")) not in (int, float):
            return False
        expiry = min(cookies[0]["expirationDate"], material["login_payload"]["game_expire_time"])
        # 本地 Cookie 时间只决定是否尝试，绝不用作续期成功证明。
        return 0 < expiry - self.clock() <= 48 * 3600
