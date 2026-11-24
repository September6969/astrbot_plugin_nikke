# SPDX-License-Identifier: GPL-3.0-or-later
"""日志中的不可信异常文本脱敏工具。"""

from __future__ import annotations

import re
from typing import Any


_MASK = "[已遮盖]"
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+")
_AUTH_RE = re.compile(
    r"(?i)(\b(?:authorization|proxy-authorization)\s*[:=]\s*)"
    r"(?:(?:bearer|basic)\s+)?[^\s,;]+"
)
_QUERY_RE = re.compile(
    r"(?i)([?&](?:access[_-]?token|refresh[_-]?token|token|cookie|authorization|api[_-]?key)\s*=)[^&#\s]+"
)
_SENSITIVE_KEYS = (
    r"access[_-]?token|refresh[_-]?token|id[_-]?token|token|cookie|"
    r"authorization|proxy-authorization|password|passwd|secret|api[_-]?key|"
    r"x-api-key|openid|game[_-]?token|game[_-]?gameid|game[_-]?uid|"
    r"game[_-]?openid|x-common-params|qq[_-]?id|user[_-]?id"
)
_JSON_SCALAR_KV_RE = re.compile(
    rf"(?i)([\"'](?:{_SENSITIVE_KEYS})[\"']\s*:\s*)"
    r"(?:\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|[^\s,}\]]+)"
)
# 先处理带引号的值（可含空格），再处理不带引号的值。
_QUOTED_KV_RE = re.compile(
    rf"(?i)(\b(?:{_SENSITIVE_KEYS})\s*[:=]\s*)(?:\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*')"
)
_UNQUOTED_KV_RE = re.compile(
    rf"(?i)(\b(?:{_SENSITIVE_KEYS})\s*[:=]\s*)[^\s,;}}]+"
)
# 完整 Cookie / Set-Cookie 头：遮盖到行尾，避免只遮盖首对而漏掉 game_channelid 等后续值。
_COOKIE_HEADER_RE = re.compile(r"(?i)(\b(?:set-)?cookie\s*:\s*)[^\r\n]*")
# 绑定页与竞技场分享链接中的一次性令牌。
_LINK_TOKEN_RE = re.compile(r"(?i)(/(?:bind|arena/open)/)[A-Za-z0-9_\-.~%]{16,}")
# 独立 Bearer 令牌与 JWT（header.payload.signature）。
_BEARER_RE = re.compile(r"(?i)(\bbearer\s+)[A-Za-z0-9\-._~+/]+=*")
_JWT_RE = re.compile(r"\beyJ[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{4,}")
_COOKIE_PAIR_RE = re.compile(
    r"(?i)(\b(?:game_token|game_uid|game_openid|game_gameid|x-common-params)\s*=\s*)"
    r"[^\s,;}&]+"
)


def sanitize_log_text(value: Any, *, max_length: int = 240) -> str:
    """将异常或外部文本压缩为可写入日志的脱敏摘要。"""

    limit = max(1, int(max_length))
    text = str(value)
    # 换行前先处理 Cookie 头，使遮盖止于原始行尾而不吞掉后续日志行。
    text = _COOKIE_HEADER_RE.sub(rf"\1{_MASK}", text)
    text = text.replace("\r", " ").replace("\n", " ")
    text = _AUTH_RE.sub(rf"\1{_MASK}", text)
    text = _BEARER_RE.sub(rf"\1{_MASK}", text)
    text = _JWT_RE.sub(_MASK, text)
    text = _LINK_TOKEN_RE.sub(rf"\1{_MASK}", text)
    text = _QUERY_RE.sub(rf"\1{_MASK}", text)
    text = _JSON_SCALAR_KV_RE.sub(rf"\1{_MASK}", text)
    text = _QUOTED_KV_RE.sub(rf"\1{_MASK}", text)
    text = _UNQUOTED_KV_RE.sub(rf"\1{_MASK}", text)
    text = _COOKIE_PAIR_RE.sub(rf"\1{_MASK}", text)
    text = _EMAIL_RE.sub("[邮箱已遮盖]", text)
    return text[:limit]


def safe_exception_message(exc: BaseException, *, max_length: int = 240) -> str:
    """返回包含异常类型但不包含原始敏感值的短日志消息。"""

    limit = max(1, int(max_length))
    message = sanitize_log_text(exc, max_length=limit)
    prefix = type(exc).__name__
    if not message:
        return prefix[:limit]
    return f"{prefix}: {message}"[:limit]
