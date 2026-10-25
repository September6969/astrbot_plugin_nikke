"""社区额外任务的严格状态合同，不将网络提交当作任务完成。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol
from collections.abc import Callable
from contextlib import contextmanager
import hashlib


KINDS = ("browse", "like")
LABELS = {"browse": "浏览", "like": "点赞"}


def account_scope(account: Mapping[str, Any]) -> str:
    """社区任务以核实过的社区身份去重，不让不同游戏区服重复取得预算。"""
    openid = account.get("game_openid")
    if not isinstance(openid, str) or not openid.strip():
        raise ValueError("社区身份不完整，请重新绑定")
    return hashlib.sha256(f"blablalink-community:{openid.strip()}".encode()).hexdigest()


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
                    blocking_statuses: set[str], initial_status: str, detail: str = "") -> bool: ...
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


@contextmanager
def account_execution_lease(store: AutomationStore, account):
    """多进程也串行读取和提交；进程崩溃留下占用时只允许状态查询。"""
    key = "community-account-lease:v1:" + account_scope(account)
    acquired = store.claim_run(key, str(account["qq_id"]), "community_account_lease", initial_status="LEASED")
    if not acquired:
        acquired = store.transition_run(key, from_statuses={"RELEASED"}, to_status="LEASED", detail="额外能力执行中")
    try:
        yield acquired
    finally:
        if acquired:
            store.finish_run(key, "RELEASED", "执行上下文已正常退出；未决动作保护仍独立保留")
