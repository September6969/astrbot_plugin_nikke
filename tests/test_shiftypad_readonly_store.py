# SPDX-License-Identifier: GPL-3.0-or-later
"""ShiftyPad 只读快照：同步幂等、公开变化、上游失败、隔离与解绑。"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from astrbot_plugin_nikke.features.shiftypad.models import (
    ShiftypadIdentity,
    ShiftypadPrivateError,
    ShiftypadProfile,
    ShiftypadUpstreamError,
)
from astrbot_plugin_nikke.features.shiftypad.storage import ShiftypadReadOnlyStore

OPENID = "12345-1234567890"


class MemoryStore:
    def __init__(self) -> None:
        self.values: dict[str, object] = {}

    def get_setting(self, key, default=None):
        return self.values.get(key, default)

    def set_setting(self, key, value):
        self.values[key] = value


def identity() -> ShiftypadIdentity:
    return ShiftypadIdentity(
        openid=OPENID, uid="123456789", server="na", area_id="83",
        source="trusted_mapping", source_url="https://example.invalid/source",
    )


def make_profile(nickname: str = "公开昵称", level: int = 300) -> ShiftypadProfile:
    return ShiftypadProfile(
        identity=identity(),
        nickname=nickname,
        level=level,
        team_combat=123456,
        nikke_count=2,
        synchro_level=200,
        visibility="public",
        characters=(),
        fetched_at="2026-11-23T00:00:00+00:00",
    )


class FakeFetcher:
    def __init__(self, profile_factory) -> None:
        self.profile_factory = profile_factory
        self.calls = 0

    async def fetch(self, _identity):
        self.calls += 1
        value = self.profile_factory(self.calls)
        if isinstance(value, Exception):
            raise value
        return value


def store() -> ShiftypadReadOnlyStore:
    return ShiftypadReadOnlyStore(
        MemoryStore(), clock=lambda: datetime(2026, 11, 23, tzinfo=timezone.utc)
    )


@pytest.mark.asyncio
async def test_bind_sync_is_idempotent_and_reports_changes() -> None:
    readonly = store()
    readonly.bind("user-a", make_profile())
    same = await readonly.sync("user-a", FakeFetcher(lambda _n: make_profile()))
    assert same.ok and same.changed is False
    assert reading(readonly, "user-a").profile.nickname == "公开昵称"

    changed = await readonly.sync("user-a", FakeFetcher(lambda _n: make_profile("新昵称", 301)))
    assert changed.ok and changed.changed is True
    assert reading(readonly, "user-a").profile.level == 301


def reading(readonly: ShiftypadReadOnlyStore, actor: str):
    value = readonly.get(actor)
    assert value is not None
    return value


@pytest.mark.asyncio
async def test_private_or_upstream_failure_preserves_previous_snapshot_and_marks_stale() -> None:
    readonly = store()
    readonly.bind("user-a", make_profile())

    private = await readonly.sync(
        "user-a", FakeFetcher(lambda _n: ShiftypadPrivateError("公开开关已关闭"))
    )
    assert private.ok is False
    assert private.error_code == "PRIVATE"
    assert readonly.status("user-a")["status"] == "stale"
    assert readonly.status("user-a")["can_sync"] is True
    assert reading(readonly, "user-a").profile.nickname == "公开昵称"

    upstream = await readonly.sync(
        "user-a", FakeFetcher(lambda _n: ShiftypadUpstreamError("上游 503"))
    )
    assert upstream.ok is False
    assert upstream.error_code == "UPSTREAM"
    assert readonly.status("user-a")["can_sync"] is True
    assert reading(readonly, "user-a").profile.nickname == "公开昵称"


@pytest.mark.asyncio
async def test_bindings_are_isolated_and_unbind_does_not_touch_other_users() -> None:
    readonly = store()
    readonly.bind("user-a", make_profile("A"))
    readonly.bind("user-b", make_profile("B"))
    assert readonly.get("user-a").profile.nickname == "A"
    assert readonly.get("user-b").profile.nickname == "B"

    readonly.unbind("user-a")
    assert readonly.get("user-a") is None
    assert readonly.get("user-b").profile.nickname == "B"
    assert readonly.status("user-a")["status"] == "unbound"


@pytest.mark.asyncio
async def test_sync_without_binding_and_roster_snapshot() -> None:
    readonly = store()
    outcome = await readonly.sync("user-a", FakeFetcher(lambda _n: make_profile()))
    assert outcome.ok is False and outcome.status == "unbound"

    readonly.bind("user-a", make_profile())
    assert readonly.roster_snapshot("user-a") == ()
    assert readonly.status("user-a")["status"] == "ready"
    assert readonly.status("user-a")["can_sync"] is True


def test_rebind_different_openid_resets_bound_at_and_sync_count() -> None:
    ticks = iter([
        datetime(2026, 11, 23, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 11, 24, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 11, 25, 0, 0, tzinfo=timezone.utc),
    ])
    readonly = ShiftypadReadOnlyStore(MemoryStore(), clock=lambda: next(ticks))
    first = readonly.bind("user-a", make_profile("A1"))
    same = readonly.bind("user-a", make_profile("A2"))
    assert same.bound_at == first.bound_at
    assert same.sync_count == 2

    other_identity = ShiftypadIdentity(
        openid="99999-9999999999", uid="999999999", server="jp", area_id="82",
        source="public_reference", source_url="https://example.invalid/other",
    )
    other = ShiftypadProfile(
        identity=other_identity, nickname="B", level=100, team_combat=1000,
        nikke_count=1, synchro_level=100, visibility="public", characters=(),
        fetched_at="2026-11-25T00:00:00+00:00",
    )
    rebound = readonly.bind("user-a", other)
    assert rebound.bound_at != first.bound_at
    assert rebound.sync_count == 1
