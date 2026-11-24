"""社区额外任务的严格状态合同，不将网络提交当作任务完成。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol
from collections.abc import Callable
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
import uuid


KINDS = ("browse", "like")
# 执行租约：进程存活锁，与动作结果状态（UNKNOWN_AFTER_ACTION）完全解耦。
LEASE_TIMEOUT_SECONDS = 600
# 每个进程代次唯一；同一进程内由 asyncio 账号锁串行，跨进程只在租约超时后接管。
PROCESS_TOKEN = f"{os.getpid()}:{uuid.uuid4().hex}"
# 人工核实后的未决动作：解除后续新周期阻断，但所在周期仍保持暂停，绝不补跑。
ACKNOWLEDGED_UNKNOWN = "ACKNOWLEDGED_UNKNOWN"
LABELS = {"browse": "浏览", "like": "点赞"}


def account_scope(account: Mapping[str, Any]) -> str:
    """社区任务以核实过的社区身份去重，不让不同游戏区服重复取得预算。"""
    openid = account.get("game_openid")
    if not isinstance(openid, str) or not openid.strip():
        raise ValueError("社区身份不完整，请重新绑定")
    return hashlib.sha256(f"blablalink-community:{openid.strip()}".encode()).hexdigest()


def execution_lock_key(account: Mapping[str, Any]) -> str:
    """进程内账号锁与数据库租约共用的作用域：优先社区身份，缺失时退回游戏身份。"""
    try:
        return "community:" + account_scope(account)
    except ValueError:
        uid = str(account.get("game_uid") or account.get("uid") or "").strip()
        area = str(account.get("area_id") or "").strip()
        platform = str(account.get("platform") or "global").strip().casefold()
        return f"game:{uid}:{area}:{platform}" if uid and area else ""


def binding_stamp(account: Mapping[str, Any]) -> dict[str, str]:
    generation = str(account.get("binding_generation") or "")
    if not generation:
        raise ValueError("绑定代次缺失，请重新绑定")
    return {"identity": account_scope(account), "generation": generation}


@dataclass(frozen=True)
class TaskProgress:
    kind: str
    task_id: str
    period: str
    target: int
    current: int
    completed: bool
    reward: str = "未核实到账；未发送领取请求"


@dataclass(frozen=True)
class PostCandidate:
    post_id: str
    liked: bool | None


@dataclass(frozen=True)
class OperationResult:
    status: str
    detail: str


class ActionGateway(Protocol):
    async def identity(self, account: Mapping[str, Any]) -> str: ...
    async def progress(self, account: Mapping[str, Any]) -> dict[str, TaskProgress | None]: ...
    async def candidates(self, account: Mapping[str, Any]) -> list[PostCandidate]: ...
    async def liked(self, account: Mapping[str, Any], post_id: str) -> bool | None: ...
    async def dispatch(self, account: Mapping[str, Any], kind: str, post_id: str) -> None: ...


class AutomationStore(Protocol):
    def get_account(self, qq_id: str, with_cookie: bool = True) -> dict[str, Any] | None: ...
    def get_setting(self, key: str, default: Any = None) -> Any: ...
    def set_setting(self, key: str, value: Any) -> None: ...
    def list_accounts(self, **kwargs: Any) -> list[dict[str, Any]]: ...
    def list_runs(self, *, action: str | None = None) -> list[dict[str, Any]]: ...
    def get_run(self, key: str) -> dict[str, Any] | None: ...
    def claim_run(self, key: str, qq_id: str, action: str, *, initial_status: str) -> bool: ...
    def finish_run(self, key: str, status: str, detail: str = "") -> None: ...
    def transition_run(self, key: str, *, from_statuses: set[str], to_status: str,
                       detail: str = "", **kwargs: Any) -> bool: ...
    def reserve_run(self, scope: str, key: str, qq_id: str, action: str, *, limit: int,
                    blocking_statuses: set[str], initial_status: str, detail: str = "",
                    budget_exempt_statuses: frozenset[str] | set[str] = ...) -> bool: ...
    def replace_session(self, account: Mapping[str, Any], cookie: str, material: dict[str, Any]) -> bool: ...


def still_authorized(store: AutomationStore, config: Mapping[str, Any], account: Mapping[str, Any],
                     capability: str, automatic: bool) -> bool:
    """每次出队和提交前重新检查本人授权、绑定代次及总开关。"""
    if config.get("enable_daily_actions", False) is not True:
        return False
    current = store.get_account(str(account["qq_id"]))
    if not current or not current.get("cookie_valid"):
        return False
    if binding_stamp(current) != binding_stamp(account):
        return False
    if current.get("binding_revision") != account.get("binding_revision"):
        return False
    preference = store.get_setting(f"{capability}:auto:{account['qq_id']}", None)
    if automatic:
        from datetime import datetime, timezone
        day = datetime.now(timezone.utc).date().isoformat()
        if store.get_setting(f"community_automation:halt:{account_scope(account)}:{day}", False):
            return False
    return not automatic or preference == binding_stamp(current)


AccountLock = Callable[[Mapping[str, Any]], Any]


def lease_key(account: Mapping[str, Any]) -> str:
    return "community-account-lease:v1:" + account_scope(account)


def _lease_detail() -> str:
    return json.dumps({"owner": PROCESS_TOKEN, "acquired_at": datetime.now(timezone.utc).isoformat(),
                       "timeout_seconds": LEASE_TIMEOUT_SECONDS, "note": "额外能力执行中"})


def _lease_owner(row: Mapping[str, Any] | None) -> str:
    try:
        return str(json.loads(str((row or {}).get("detail") or "{}")).get("owner") or "")
    except (TypeError, ValueError):
        return ""


@contextmanager
def account_execution_lease(store: AutomationStore, account):
    """多进程也串行读取和提交。

    崩溃遗留的占用不再永久锁死：同一进程代次（已持有进程内账号锁）可立即接管；
    其他进程的占用只有超过 LEASE_TIMEOUT_SECONDS 才接管。租约只代表“正在执行”，
    回收它不会解除或重放任何 UNKNOWN_AFTER_ACTION 动作结果。
    """
    key = lease_key(account)
    acquired = store.claim_run(key, str(account["qq_id"]), "community_account_lease", initial_status="LEASED")
    if not acquired:
        acquired = store.transition_run(key, from_statuses={"RELEASED"}, to_status="LEASED",
                                        detail=_lease_detail(), refresh_created_at=True)
    if not acquired:
        stale_after = 0 if _lease_owner(store.get_run(key)) == PROCESS_TOKEN else LEASE_TIMEOUT_SECONDS
        acquired = store.transition_run(key, from_statuses={"LEASED"}, to_status="LEASED",
                                        detail=_lease_detail(), stale_after=stale_after,
                                        refresh_created_at=True)
    elif store.get_run(key) and not _lease_owner(store.get_run(key)):
        store.transition_run(key, from_statuses={"LEASED"}, to_status="LEASED", detail=_lease_detail())
    try:
        yield acquired
    finally:
        if acquired:
            store.finish_run(key, "RELEASED", "执行上下文已正常退出；未决动作保护仍独立保留")
