# SPDX-License-Identifier: GPL-3.0-or-later
"""数字游戏 UID、区服与 ShiftyPad 公开身份（OpenID/编码 UID）的解析。

已核对的公开行为：
- 官方 ShiftyPad 前端把长账号标识放在 ``openid`` 查询参数，或用
  ``uid=base64(encodeURIComponent(openid))`` 传递；数字游戏 UID 是页面展示字段，
  未发现可用未登录接口把它转换为 OpenID。
- 因此本模块**默认不把数字 UID 当作可查询所有账号的钥匙**。只有运营者提供明确
  来源的可信映射（``data/nikke/shiftypad-uid-map.json``）时，UID+区服才解析为
  公开只读身份；否则要求用户提供官方 ShiftyPad 公开链接/OpenID，并明确说明
  数字 UID 不能独立使用。
"""

from __future__ import annotations

import base64
import binascii
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import parse_qs, unquote, urlparse

from .models import (
    SERVER_ALIASES,
    Resolution,
    ShiftypadIdentity,
    ShiftypadInputError,
)

OPENID_RE = re.compile(r"^[0-9]{5}-[0-9]{9,30}$")
UID_RE = re.compile(r"^[0-9]{5,12}$")
AREA_RE = re.compile(r"^[0-9]{1,4}$")
OFFICIAL_HOSTS = frozenset({"www.blablalink.com", "blablalink.com"})
OFFICIAL_FALLBACK = "https://www.blablalink.com/shiftyspad/home"


def normalize_uid(value: Any) -> str:
    text = str(value or "").strip()
    if not UID_RE.fullmatch(text):
        raise ShiftypadInputError("游戏 UID 必须是 5–12 位数字")
    return text


def normalize_server(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    key = text.casefold()
    if key in SERVER_ALIASES:
        return SERVER_ALIASES[key]
    if AREA_RE.fullmatch(text):
        return text
    raise ShiftypadInputError("区服必须是国际服/日服/韩服/北美/东南亚/国服或数字区服 ID")


def encode_shiftypad_uid(openid: str) -> str:
    """与官方前端一致的 uid 参数编码，用于生成公开链接。"""
    value = str(openid or "").strip()
    if not OPENID_RE.fullmatch(value):
        raise ShiftypadInputError("ShiftyPad OpenID 格式不符")
    return base64.b64encode(unquote(value).encode("utf-8")).decode("ascii")


def official_share_url(openid: str) -> str:
    return f"{OFFICIAL_FALLBACK}?uid={encode_shiftypad_uid(openid)}"


def _decode_uid_param(value: str) -> str:
    raw = str(value or "").strip()
    if OPENID_RE.fullmatch(raw):
        return raw
    padded = raw + "=" * (-len(raw) % 4)
    try:
        decoded = base64.b64decode(padded, validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError) as exc:
        raise ShiftypadInputError("官方链接中的 uid 参数不是有效编码 ID") from exc
    decoded = unquote(decoded).strip()
    if not OPENID_RE.fullmatch(decoded):
        raise ShiftypadInputError("官方链接中的 uid 不是受支持的 ShiftyPad OpenID")
    return decoded


def parse_public_reference(value: Any) -> ShiftypadIdentity:
    """解析用户直接提供的官方 ShiftyPad 公开链接或 OpenID。"""
    text = str(value or "").strip()
    if not text:
        raise ShiftypadInputError("请提供官方 ShiftyPad 公开链接或 OpenID")
    if len(text) > 512:
        raise ShiftypadInputError("公开链接过长")
    if OPENID_RE.fullmatch(text):
        return ShiftypadIdentity(
            openid=text, source="public_reference", source_url=official_share_url(text)
        )
    parsed = urlparse(text)
    if parsed.scheme != "https" or parsed.hostname not in OFFICIAL_HOSTS:
        raise ShiftypadInputError("只接受 blablalink.com 的 HTTPS ShiftyPad 公开链接")
    if parsed.username or parsed.password:
        raise ShiftypadInputError("公开链接不能包含账号信息")
    if not parsed.path.startswith("/shiftyspad"):
        raise ShiftypadInputError("链接不是 ShiftyPad 页面")
    query = parse_qs(parsed.query, keep_blank_values=False)
    openid = ""
    if query.get("openid"):
        candidate = str(query["openid"][-1]).strip()
        if OPENID_RE.fullmatch(candidate):
            openid = candidate
    if not openid and query.get("uid"):
        openid = _decode_uid_param(str(query["uid"][-1]))
    if not openid:
        raise ShiftypadInputError("公开链接缺少受支持的 openid/uid 参数")
    area = ""
    for key in ("area_id", "area", "server"):
        if query.get(key):
            try:
                area = normalize_server(str(query[key][-1]))
            except ShiftypadInputError:
                area = ""
            break
    area_id = area if area.isdigit() else ""
    server = area if area and not area.isdigit() else ""
    return ShiftypadIdentity(
        openid=openid,
        area_id=area_id,
        server=server,
        source="public_reference",
        source_url=official_share_url(openid),
    )


@dataclass(frozen=True, slots=True)
class MappingEntry:
    uid: str
    server: str
    openid: str
    area_id: str = ""
    source_url: str = ""


class UidMappingResolver:
    """只使用运营者提供的精确 UID+区服映射；不做范围猜测或模糊转换。"""

    def __init__(self, entries: tuple[MappingEntry, ...] = (), *, error: str = "") -> None:
        self._entries = {(item.uid, item.server): item for item in entries}
        self.error = error

    @property
    def available(self) -> bool:
        return bool(self._entries) and not self.error

    @classmethod
    def from_file(cls, path: str | Path) -> "UidMappingResolver":
        target = Path(path)
        if not target.is_file():
            return cls(error=f"未配置可信 UID 映射：{target.name}")
        try:
            payload = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return cls(error="可信 UID 映射不是合法 UTF-8 JSON")
        try:
            return cls.from_payload(payload)
        except (ValueError, TypeError) as exc:
            return cls(error=f"可信 UID 映射无效：{exc}")

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "UidMappingResolver":
        if not isinstance(payload, Mapping) or payload.get("schema_version") != 1:
            raise ValueError("schema_version 必须为 1")
        if str(payload.get("status") or "") not in {"OPERATOR_VERIFIED", "PUBLIC_VERIFIED"}:
            raise ValueError("status 必须是 OPERATOR_VERIFIED 或 PUBLIC_VERIFIED")
        source = str(payload.get("source_url") or "").strip()
        parsed = urlparse(source)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("source_url 必须是无凭据 HTTPS")
        checked_at = str(payload.get("checked_at") or "").strip()
        if not checked_at:
            raise ValueError("checked_at 缺失")
        rows = payload.get("entries")
        if not isinstance(rows, list) or not rows:
            raise ValueError("entries 必须是非空数组")
        entries: list[MappingEntry] = []
        for index, row in enumerate(rows):
            if not isinstance(row, Mapping):
                raise ValueError(f"entries[{index}] 必须是对象")
            uid = normalize_uid(row.get("uid"))
            server = normalize_server(row.get("server"))
            if not server:
                raise ValueError(f"entries[{index}].server 缺失")
            openid = str(row.get("openid") or "").strip()
            if not OPENID_RE.fullmatch(openid):
                raise ValueError(f"entries[{index}].openid 格式不符")
            row_source = str(row.get("source_url") or source)
            row_url = urlparse(row_source)
            if row_url.scheme != "https" or not row_url.netloc:
                raise ValueError(f"entries[{index}].source_url 必须是 HTTPS")
            entries.append(
                MappingEntry(
                    uid=uid,
                    server=server,
                    openid=openid,
                    area_id=str(row.get("area_id") or "").strip(),
                    source_url=row_source,
                )
            )
        return cls(tuple(entries))

    def resolve(
        self,
        uid: Any = "",
        server: Any = "",
        *,
        public_reference: Any = "",
    ) -> Resolution:
        """优先用户直接提供的公开链接；否则仅查精确可信映射。"""
        if str(public_reference or "").strip():
            try:
                identity = parse_public_reference(public_reference)
            except ShiftypadInputError as exc:
                return Resolution("invalid_reference", reason=str(exc), uid_standalone=False)
            return Resolution("resolved", identity=identity, uid_standalone=False)

        try:
            normalized_uid = normalize_uid(uid)
            normalized_server = normalize_server(server)
        except ShiftypadInputError as exc:
            return Resolution("invalid_uid", reason=str(exc), uid_standalone=False)
        if not normalized_server:
            return Resolution(
                "needs_server",
                reason="请选择区服；数字 UID 需要区服才能匹配可信映射。",
                uid_standalone=False,
            )
        entry = self._entries.get((normalized_uid, normalized_server))
        if entry is None:
            reason = (
                "数字 UID 不能直接查询所有 ShiftyPad 账号。当前未找到该 UID+区服的可信映射；"
                "请粘贴本人 ShiftyPad 公开链接或 OpenID，或用运营者导入的可信映射。"
            )
            if self.error:
                reason += "（" + self.error + "）"
            return Resolution(
                "uid_unresolved",
                reason=reason,
                fallback_url=OFFICIAL_FALLBACK,
                uid_standalone=False,
            )
        identity = ShiftypadIdentity(
            openid=entry.openid,
            uid=entry.uid,
            server=entry.server,
            area_id=entry.area_id,
            source="trusted_mapping",
            source_url=entry.source_url,
        )
        return Resolution("resolved", identity=identity, uid_standalone=True)


__all__ = [
    "AREA_RE",
    "MappingEntry",
    "OFFICIAL_FALLBACK",
    "OFFICIAL_HOSTS",
    "OPENID_RE",
    "UID_RE",
    "UidMappingResolver",
    "encode_shiftypad_uid",
    "normalize_server",
    "normalize_uid",
    "official_share_url",
    "parse_public_reference",
]
