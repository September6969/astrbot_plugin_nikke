# SPDX-License-Identifier: GPL-3.0-or-later
"""26 UID 与我的妮姬：公开能力受限、私有权限不因 UID 解锁、手工资料隔离。"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from astrbot_plugin_nikke.features.identity.public_profile import (
    PUBLIC_UID_REASON,
    UidInputError,
    lookup_public_uid,
    parse_manual_profile,
    render_public_uid,
)


class MemoryStore:
    def __init__(self) -> None:
        self.values: dict[str, object] = {}

    def get_setting(self, key, default=None):
        return self.values.get(key, default)

    def set_setting(self, key, value):
        self.values[key] = value


def test_public_uid_lookup_is_limited_and_never_grants_private_access() -> None:
    result = lookup_public_uid("123456789", own_uid="999999999")
    assert result.status == "UNSUPPORTED"
    assert result.private_access is False
    assert result.own_uid_match is False
    assert result.message == PUBLIC_UID_REASON
    text = render_public_uid(result)
    assert "公开 UID 查询：不可用（上游缺失）" in text
    assert "不能证明账号归属" in text

    own = lookup_public_uid("123456789", own_uid="123456789")
    assert own.status == "OWN_BOUND_UID"
    # 即使命中自己的 UID，也不会因此扩大权限或返回他人数据。
    assert own.private_access is False
    assert "不会因为 UID" not in own.message
    assert "不构成所有权证明" in own.message


def test_uid_validation_and_manual_profile_parsing() -> None:
    for bad in ("", "abc", "12345", "1234567890123", "123 456"):
        with pytest.raises(UidInputError, match="6–12 位数字"):
            lookup_public_uid(bad)

    assert parse_manual_profile("指挥官,120,测试备注") == ("指挥官", "120", "测试备注")
    assert parse_manual_profile("指挥官") == ("指挥官", None, "")
    with pytest.raises(UidInputError, match="用法"):
        parse_manual_profile(" ,120")


def test_manual_profile_is_per_user_and_unverified() -> None:
    from astrbot_plugin_nikke.features.identity.public_profile import ManualProfileStore

    store = MemoryStore()
    clock = lambda: datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)
    profiles = ManualProfileStore(store, clock=clock)

    saved = profiles.save("user-a", name="我的昵称", level="120", note="手工")
    assert saved.verified is False
    assert profiles.load("user-a").name == "我的昵称"
    assert profiles.load("user-b") is None

    profiles.save("user-a", name="改名", level=None)
    assert profiles.load("user-a").name == "改名"
    profiles.clear("user-a")
    assert profiles.load("user-a") is None

    with pytest.raises(UidInputError, match="1–40"):
        profiles.save("user-a", name="")
    with pytest.raises(UidInputError, match="1–999"):
        profiles.save("user-a", name="昵称", level="0")
