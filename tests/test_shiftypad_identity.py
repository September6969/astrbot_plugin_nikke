# SPDX-License-Identifier: GPL-3.0-or-later
"""ShiftyPad UID/公开身份解析：数字 UID 不冒充 OpenID，精确映射与公开链接。"""

from __future__ import annotations

import base64

import pytest

from astrbot_plugin_nikke.features.shiftypad.identity import (
    UidMappingResolver,
    encode_shiftypad_uid,
    normalize_server,
    normalize_uid,
    official_share_url,
    parse_public_reference,
)
from astrbot_plugin_nikke.features.shiftypad.models import ShiftypadInputError

OPENID = "12345-1234567890"
SOURCE = "https://example.invalid/shiftypad-map.json"


def mapping_payload() -> dict:
    return {
        "schema_version": 1,
        "status": "OPERATOR_VERIFIED",
        "source_url": SOURCE,
        "checked_at": "2026-11-23",
        "entries": [
            {"uid": "123456789", "server": "na", "openid": OPENID, "area_id": "83"},
            {"uid": "222222222", "server": "jp", "openid": "54321-0987654321", "area_id": "82"},
        ],
    }


def test_numeric_uid_alone_is_not_claimed_to_be_a_shiftypad_id() -> None:
    resolver = UidMappingResolver()
    result = resolver.resolve("123456789", "na")
    assert result.status == "uid_unresolved"
    assert result.identity is None
    assert result.uid_standalone is False
    assert "不能直接查询所有" in result.reason
    assert result.fallback_url.startswith("https://www.blablalink.com/shiftyspad")


def test_trusted_mapping_requires_exact_uid_and_server_and_can_cover_multiple_servers() -> None:
    resolver = UidMappingResolver.from_payload(mapping_payload())
    na = resolver.resolve("123456789", "北美服")
    jp = resolver.resolve("222222222", "jp")
    assert na.status == "resolved"
    assert na.identity.openid == OPENID
    assert na.identity.area_id == "83"
    assert na.uid_standalone is True
    assert na.identity.source == "trusted_mapping"
    assert jp.identity.openid == "54321-0987654321"

    mismatch = resolver.resolve("123456789", "jp")
    assert mismatch.status == "uid_unresolved"

    invalid = resolver.resolve("123", "na")
    assert invalid.status == "invalid_uid"


def test_official_public_link_openid_and_encoded_uid_are_supported() -> None:
    encoded = encode_shiftypad_uid(OPENID)
    assert base64.b64decode(encoded + "=" * (-len(encoded) % 4)).decode("utf-8") == OPENID

    from_uid = parse_public_reference(
        f"https://www.blablalink.com/shiftyspad/home?uid={encoded}&area_id=83"
    )
    assert from_uid.openid == OPENID
    assert from_uid.area_id == "83"
    assert from_uid.source == "public_reference"

    from_openid = parse_public_reference(
        f"https://www.blablalink.com/shiftyspad/nikke-list/player?openid={OPENID}&server=jp"
    )
    assert from_openid.openid == OPENID
    assert from_openid.server == "jp"

    assert parse_public_reference(OPENID).openid == OPENID
    assert official_share_url(OPENID).endswith("uid=" + encode_shiftypad_uid(OPENID))


def test_public_link_rejects_untrusted_hosts_urls_and_numeric_uid() -> None:
    with pytest.raises(ShiftypadInputError, match="blablalink"):
        parse_public_reference(f"https://example.com/shiftyspad?openid={OPENID}")
    with pytest.raises(ShiftypadInputError, match="HTTPS"):
        parse_public_reference(f"http://www.blablalink.com/shiftyspad?openid={OPENID}")
    with pytest.raises(ShiftypadInputError, match="不是有效编码 ID"):
        parse_public_reference("https://www.blablalink.com/shiftyspad/home?uid=123456789")
    with pytest.raises(ShiftypadInputError, match="不是 ShiftyPad"):
        parse_public_reference(f"https://www.blablalink.com/user?openid={OPENID}")


def test_public_reference_takes_precedence_and_mapping_file_errors_are_explicit() -> None:
    resolver = UidMappingResolver.from_payload(mapping_payload())
    result = resolver.resolve("123456789", "na", public_reference=official_share_url(OPENID))
    assert result.status == "resolved"
    assert result.identity.source == "public_reference"
    assert result.uid_standalone is False

    missing = UidMappingResolver.from_file("does-not-exist.json")
    assert missing.available is False
    unresolved = missing.resolve("123456789", "na")
    assert "未配置可信 UID 映射" in unresolved.reason

    with pytest.raises(ValueError):
        UidMappingResolver.from_payload(
            {**mapping_payload(), "entries": [{"uid": "123456789", "server": "na", "openid": "bad"}]}
        )


def test_uid_and_server_normalization() -> None:
    assert normalize_uid(" 123456789 ") == "123456789"
    assert normalize_server("北美服") == "na"
    assert normalize_server("93") == "93"
    with pytest.raises(ShiftypadInputError):
        normalize_uid("123")
    with pytest.raises(ShiftypadInputError):
        normalize_server("unknown")
