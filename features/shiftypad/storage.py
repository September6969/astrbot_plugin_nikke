# SPDX-License-Identifier: GPL-3.0-or-later
"""ShiftyPad 只读绑定的最小化持久化与同步语义。

只保存本人授权的公开快照；与账号登录/私有权限完全分离。同步失败或公开开关
关闭时保留旧快照并标记 stale，不用空数据覆盖；同一内容重复同步保持幂等。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Protocol

from .models import (
    ReadonlyBinding,
    ShiftypadPrivateError,
    ShiftypadProfile,
    ShiftypadUpstreamError,
)

KEY_PREFIX = "shiftypad_readonly_v1:"


class SettingsStorePort(Protocol):
    def get_setting(self, key: str, default: Any = None) -> Any: ...

    def set_setting(self, key: str, value: Any) -> None: ...


class ProfileFetcherPort(Protocol):
    async def fetch(self, identity: Any) -> ShiftypadProfile: ...


@dataclass(frozen=True, slots=True)
class SyncOutcome:
    ok: bool
    status: str
    changed: bool
    binding: ReadonlyBinding | None = None
    error_code: str = ""
    message: str = ""


class ShiftypadReadOnlyStore:
    def __init__(self, store: SettingsStorePort, *, clock=None) -> None:
        self._store = store
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def _key(self, actor_id: str) -> str:
        text = str(actor_id or "").strip()
        if not text:
            raise ValueError("缺少用户标识，无法保存只读绑定")
        return f"{KEY_PREFIX}{text}"

    def _now(self) -> datetime:
        current = self._clock()
        if not isinstance(current, datetime) or current.tzinfo is None:
            raise ValueError("时钟必须包含明确时区")
        return current.astimezone(timezone.utc)

    def bind(self, actor_id: str, profile: ShiftypadProfile) -> ReadonlyBinding:
        if not isinstance(profile, ShiftypadProfile):
            raise ValueError("只读绑定需要公开档案快照")
        if not profile.identity.openid:
            raise ValueError("只读绑定缺少公开 OpenID")
        now = self._now().isoformat()
        existing = self.get(actor_id)
        same_identity = (
            existing is not None
            and existing.profile.identity.openid == profile.identity.openid
        )
        binding = ReadonlyBinding(
            actor_id=str(actor_id),
            profile=profile,
            bound_at=existing.bound_at if same_identity else now,
            last_sync_at=now,
            last_error="",
            stale=False,
            sync_count=(existing.sync_count + 1) if same_identity else 1,
        )
        self._store.set_setting(self._key(actor_id), binding.to_dict())
        return binding

    def get(self, actor_id: str) -> ReadonlyBinding | None:
        raw = self._store.get_setting(self._key(actor_id), None)
        if not isinstance(raw, Mapping):
            return None
        try:
            return ReadonlyBinding.from_dict(str(actor_id), raw)
        except (TypeError, ValueError):
            return None

    def fresh_binding(
        self,
        actor_id: str,
        *,
        max_age_hours: int = 24,
    ) -> ReadonlyBinding | None:
        """返回未 stale 且在时限内的本人只读快照；不返回他人数据。"""
        binding = self.get(actor_id)
        if binding is None or binding.stale:
            return None
        try:
            last = datetime.fromisoformat(binding.last_sync_at)
        except (TypeError, ValueError):
            return None
        if last.tzinfo is None:
            return None
        age = self._now() - last.astimezone(timezone.utc)
        if age.total_seconds() < 0 or age > timedelta(hours=max_age_hours):
            return None
        return binding

    def status(self, actor_id: str) -> dict[str, Any]:
        binding = self.get(actor_id)
        if binding is None:
            return {"status": "unbound", "can_sync": False}
        return {
            "status": "stale" if binding.stale else "ready",
            "can_sync": True,
            "binding": binding.public_dict(),
            "last_error": binding.last_error,
        }

    async def sync(self, actor_id: str, fetcher: ProfileFetcherPort) -> SyncOutcome:
        binding = self.get(actor_id)
        if binding is None:
            return SyncOutcome(False, "unbound", False, error_code="UNBOUND",
                               message="尚未建立只读绑定")
        try:
            profile = await fetcher.fetch(binding.profile.identity)
        except ShiftypadPrivateError as exc:
            return self._mark_failure(binding, "PRIVATE", str(exc))
        except ShiftypadUpstreamError as exc:
            return self._mark_failure(binding, "UPSTREAM", str(exc))
        except Exception as exc:
            return self._mark_failure(binding, "UPSTREAM", f"同步失败（{type(exc).__name__}）")
        now = self._now().isoformat()
        changed = profile.content_hash != binding.profile.content_hash
        updated = ReadonlyBinding(
            actor_id=binding.actor_id,
            profile=profile,
            bound_at=binding.bound_at,
            last_sync_at=now,
            last_error="",
            stale=False,
            sync_count=binding.sync_count + 1,
        )
        self._store.set_setting(self._key(actor_id), updated.to_dict())
        return SyncOutcome(
            True,
            "ready",
            changed,
            binding=updated,
            message="已更新公开快照" if changed else "公开快照无变化",
        )

    def _mark_failure(self, binding: ReadonlyBinding, code: str, message: str) -> SyncOutcome:
        updated = ReadonlyBinding(
            actor_id=binding.actor_id,
            profile=binding.profile,
            bound_at=binding.bound_at,
            last_sync_at=binding.last_sync_at,
            last_error=f"{code}: {message}"[:240],
            stale=True,
            sync_count=binding.sync_count,
        )
        # 失败时只更新状态，不删除既有公开快照。
        self._store.set_setting(self._key(binding.actor_id), updated.to_dict())
        return SyncOutcome(False, "stale", False, binding=updated, error_code=code, message=message)

    def unbind(self, actor_id: str) -> None:
        self._store.set_setting(self._key(actor_id), None)

    def roster_snapshot(self, actor_id: str) -> tuple[Any, ...]:
        binding = self.get(actor_id)
        return binding.profile.characters if binding else ()


__all__ = ["KEY_PREFIX", "ProfileFetcherPort", "SettingsStorePort", "ShiftypadReadOnlyStore", "SyncOutcome"]
