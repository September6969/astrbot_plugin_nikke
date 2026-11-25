# SPDX-License-Identifier: GPL-3.0-or-later
"""双入口内存会话、一次性兑换、群聊反馈幂等与分享脱敏确认状态机。

严格保证：
1. 公共大厅仅可在显式 /hall/open/{token} 领取后持有最小群聊反馈上下文，不包含任何个人账号或练度数据；
2. 个人工作台严格采用 GET 不消费 -> POST /claim 兑换 -> HttpOnly Cookie + CSRF；
3. QQ 群内反馈与分享均强制幂等键；遇到未知投递状态 (status='unknown') 拒绝自动重放。
"""

from __future__ import annotations

import hashlib
import re
import secrets
import time
from dataclasses import dataclass, field
from typing import Any, Callable


TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{32,128}$")
_SENSITIVE_KV_RE = re.compile(
    r"(?i)(game_token|cookie|x-common-params|authorization|bearer\s+[A-Za-z0-9._-]+|secret\s*=)"
    r"[^\s\n]*"
)
_LONG_DIGIT_ID_RE = re.compile(r"\b\d{8,24}\b")


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def mask_actor_label(actor_id: str) -> str:
    text = str(actor_id or "").strip()
    if len(text) <= 4:
        return "****"
    return f"***{text[-4:]}"


def redact_share_text(
    text: str,
    *,
    raw_uid: str = "",
    raw_openid: str = "",
    raw_actor_id: str = "",
) -> tuple[str, tuple[str, ...]]:
    """对即将发往 QQ 群聊的个人摘要执行强制脱敏，返回 (脱敏正文, 脱敏说明列表)。"""
    cleaned = str(text or "")
    notes: list[str] = []

    for label, secret in (
        ("游戏 UID", raw_uid),
        ("OpenID", raw_openid),
        ("用户标识", raw_actor_id),
    ):
        val = str(secret or "").strip()
        if val and val in cleaned:
            cleaned = cleaned.replace(val, f"***{val[-4:]}" if len(val) > 4 else "***")
            notes.append(f"已隐藏{label}")

    if _SENSITIVE_KV_RE.search(cleaned):
        cleaned = _SENSITIVE_KV_RE.sub("[已脱敏凭据]", cleaned)
        notes.append("已清除凭据字段")

    # 额外保护未知长串数字编号（如未传入 raw_uid 的 9+ 位账号标识）
    def _mask_digits(match: re.Match[str]) -> str:
        num = match.group(0)
        if len(num) >= 8:
            notes.append("已脱敏长串数字标识")
            return f"***{num[-4:]}"
        return num

    cleaned = _LONG_DIGIT_ID_RE.sub(_mask_digits, cleaned)
    dedup_notes = tuple(dict.fromkeys(notes))
    return cleaned, dedup_notes


@dataclass
class DeliveryRecord:
    key: str
    kind: str
    status: str  # "pending" | "sent" | "failed" | "unknown"
    target_label: str
    message: str
    created_at: float


@dataclass
class ShareConfirmation:
    token_hash: str
    kind: str
    target_id: str
    target_label: str
    preview_text: str
    payload: dict[str, Any]
    expires_at: float
    used: bool = False


@dataclass
class HallContextSession:
    actor_id: str
    conversation_id: str
    group_label: str
    csrf: str
    created: float
    accessed: float
    expires_at: float
    requests: list[float] = field(default_factory=list)
    deliveries: dict[str, DeliveryRecord] = field(default_factory=dict)


@dataclass
class WorkspaceSession:
    actor_id: str
    conversation_id: str
    group_label: str
    csrf: str
    created: float
    accessed: float
    expires_at: float
    requests: list[float] = field(default_factory=list)
    pending_shares: dict[str, ShareConfirmation] = field(default_factory=dict)
    deliveries: dict[str, DeliveryRecord] = field(default_factory=dict)


class PortalSessionStore:
    """管理公共大厅群聊上下文与个人工作台安全会话的有界内存存储。"""

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        capacity: int = 128,
        link_ttl: float = 900.0,
        session_ttl: float = 3600.0,
        idle_ttl: float = 1800.0,
        share_ttl: float = 300.0,
    ) -> None:
        self.clock = clock
        self.capacity = max(8, int(capacity))
        self.link_ttl = float(link_ttl)
        self.session_ttl = float(session_ttl)
        self.idle_ttl = float(idle_ttl)
        self.share_ttl = float(share_ttl)
        self._hall_links: dict[str, tuple[str, str, str, float]] = {}
        self._hall_sessions: dict[str, HallContextSession] = {}
        self._workspace_links: dict[str, tuple[str, str, str, float]] = {}
        self._workspace_sessions: dict[str, WorkspaceSession] = {}

    def clean(self) -> None:
        now = self.clock()
        self._hall_links = {
            k: v for k, v in self._hall_links.items() if now < v[3]
        }
        self._workspace_links = {
            k: v for k, v in self._workspace_links.items() if now < v[3]
        }
        self._hall_sessions = {
            k: s
            for k, s in self._hall_sessions.items()
            if now < s.expires_at and (now - s.accessed) < self.idle_ttl
        }
        self._workspace_sessions = {
            k: s
            for k, s in self._workspace_sessions.items()
            if now < s.expires_at and (now - s.accessed) < self.idle_ttl
        }
        for session in self._workspace_sessions.values():
            session.pending_shares = {
                k: item
                for k, item in session.pending_shares.items()
                if not item.used and now < item.expires_at
            }

    # ------------------------------------------------------------------ 公共大厅上下文

    def create_hall_link(
        self, actor_id: str, conversation_id: str, group_label: str = ""
    ) -> str:
        self.clean()
        actor = str(actor_id or "").strip()
        target = str(conversation_id or "").strip()
        if not actor or not target:
            raise ValueError("缺少有效的群聊或发起者上下文。")
        if len(self._hall_links) >= self.capacity:
            raise ValueError("大厅群聊引导链接已达上限，请稍后再试。")
        token = secrets.token_urlsafe(32)
        label = str(group_label or target)[:64]
        self._hall_links[_digest(token)] = (
            actor,
            target,
            label,
            self.clock() + self.link_ttl,
        )
        return token

    def claim_hall(self, token: str) -> str:
        self.clean()
        if not TOKEN_RE.fullmatch(token or ""):
            raise ValueError("大厅上下文链接格式无效。")
        key = _digest(token)
        record = self._hall_links.pop(key, None)
        if record is None:
            raise ValueError("大厅群聊链接已失效或已使用，请回群重新发送 /妮姬 大厅。")
        if len(self._hall_sessions) >= self.capacity:
            oldest = min(
                self._hall_sessions,
                key=lambda item: self._hall_sessions[item].accessed,
            )
            del self._hall_sessions[oldest]
        cookie = secrets.token_urlsafe(32)
        now = self.clock()
        self._hall_sessions[_digest(cookie)] = HallContextSession(
            actor_id=record[0],
            conversation_id=record[1],
            group_label=record[2],
            csrf=secrets.token_urlsafe(32),
            created=now,
            accessed=now,
            expires_at=now + self.session_ttl,
        )
        return cookie

    def get_hall(self, cookie: str, *, touch: bool = True) -> HallContextSession | None:
        self.clean()
        if not TOKEN_RE.fullmatch(cookie or ""):
            return None
        session = self._hall_sessions.get(_digest(cookie))
        if session is not None and touch:
            session.accessed = self.clock()
        return session

    def revoke_hall(self, cookie: str) -> None:
        if cookie:
            self._hall_sessions.pop(_digest(cookie), None)

    # ------------------------------------------------------------------ 个人工作台会话

    def create_workspace_link(
        self,
        actor_id: str,
        *,
        conversation_id: str = "",
        group_label: str = "",
    ) -> str:
        self.clean()
        actor = str(actor_id or "").strip()
        if not actor:
            raise ValueError("缺少指挥官用户标识。")
        # 同一用户重新申请时淘汰尚未兑换的旧工作台入口
        self._workspace_links = {
            k: v for k, v in self._workspace_links.items() if v[0] != actor
        }
        if len(self._workspace_links) >= self.capacity:
            raise ValueError("工作台入口链接已满，请稍后再试。")
        token = secrets.token_urlsafe(32)
        self._workspace_links[_digest(token)] = (
            actor,
            str(conversation_id or "").strip(),
            str(group_label or "").strip()[:64],
            self.clock() + self.link_ttl,
        )
        return token

    def claim_workspace(self, token: str) -> str:
        self.clean()
        if not TOKEN_RE.fullmatch(token or ""):
            raise ValueError("工作台链接格式无效。")
        key = _digest(token)
        record = self._workspace_links.pop(key, None)
        if record is None:
            raise ValueError("工作台链接已过期或已使用，请回 QQ 私聊获取新链接。")
        if len(self._workspace_sessions) >= self.capacity:
            oldest = min(
                self._workspace_sessions,
                key=lambda item: self._workspace_sessions[item].accessed,
            )
            del self._workspace_sessions[oldest]
        cookie = secrets.token_urlsafe(32)
        now = self.clock()
        self._workspace_sessions[_digest(cookie)] = WorkspaceSession(
            actor_id=record[0],
            conversation_id=record[1],
            group_label=record[2],
            csrf=secrets.token_urlsafe(32),
            created=now,
            accessed=now,
            expires_at=now + self.session_ttl,
        )
        return cookie

    def get_workspace(
        self, cookie: str, *, touch: bool = True
    ) -> WorkspaceSession | None:
        self.clean()
        if not TOKEN_RE.fullmatch(cookie or ""):
            return None
        session = self._workspace_sessions.get(_digest(cookie))
        if session is not None and touch:
            session.accessed = self.clock()
        return session

    def revoke_workspace(self, cookie: str) -> None:
        if cookie:
            self._workspace_sessions.pop(_digest(cookie), None)

    # ------------------------------------------------------------------ 分享二次确认与防重放

    def create_share_confirmation(
        self,
        session: WorkspaceSession,
        *,
        kind: str,
        target_id: str,
        target_label: str,
        preview_text: str,
        payload: dict[str, Any],
    ) -> tuple[str, ShareConfirmation]:
        self.clean()
        token = secrets.token_urlsafe(24)
        token_hash = _digest(token)
        item = ShareConfirmation(
            token_hash=token_hash,
            kind=kind,
            target_id=target_id,
            target_label=target_label,
            preview_text=preview_text,
            payload=dict(payload),
            expires_at=self.clock() + self.share_ttl,
        )
        if len(session.pending_shares) >= 16:
            oldest = min(
                session.pending_shares,
                key=lambda k: session.pending_shares[k].expires_at,
            )
            del session.pending_shares[oldest]
        session.pending_shares[token_hash] = item
        return token, item

    def consume_share_confirmation(
        self, session: WorkspaceSession, token: str
    ) -> ShareConfirmation | None:
        self.clean()
        if not token:
            return None
        item = session.pending_shares.get(_digest(token))
        if item is None or item.used or self.clock() >= item.expires_at:
            return None
        item.used = True
        return item

    def check_or_begin_delivery(
        self,
        session: HallContextSession | WorkspaceSession,
        *,
        idempotency_key: str,
        kind: str,
        target_label: str,
    ) -> tuple[DeliveryRecord | None, DeliveryRecord]:
        """检查幂等键；若已处于 sent/unknown/pending，返回已有记录禁止重复投递。"""
        existing = session.deliveries.get(idempotency_key)
        if existing is not None and existing.status in {"sent", "unknown", "pending"}:
            return existing, existing
        if len(session.deliveries) >= 32:
            oldest = min(
                session.deliveries,
                key=lambda k: session.deliveries[k].created_at,
            )
            del session.deliveries[oldest]
        record = DeliveryRecord(
            key=idempotency_key,
            kind=kind,
            status="pending",
            target_label=target_label,
            message="正在投递至 QQ 会话",
            created_at=self.clock(),
        )
        session.deliveries[idempotency_key] = record
        return None, record

    @staticmethod
    def finish_delivery(
        record: DeliveryRecord, *, status: str, message: str
    ) -> DeliveryRecord:
        record.status = status
        record.message = message
        return record

    def clear(self) -> None:
        self._hall_links.clear()
        self._hall_sessions.clear()
        self._workspace_links.clear()
        self._workspace_sessions.clear()
