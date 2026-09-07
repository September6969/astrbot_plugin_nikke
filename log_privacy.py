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
    r"x-api-key|openid|game[_-]?uid|game[_-]?openid|qq[_-]?id|user[_-]?id"
)
_QUOTED_KV_RE = re.compile(
    rf"(?i)([\"'](?:{_SENSITIVE_KEYS})[\"']\s*:\s*[\"'])(.*?)([\"'])"
)
_UNQUOTED_KV_RE = re.compile(
    rf"(?i)(\b(?:{_SENSITIVE_KEYS})\s*[:=]\s*)[^\s,;}}]+"
)
_COOKIE_PAIR_RE = re.compile(
    r"(?i)(\b(?:game_token|game_uid|game_openid|game_gameid|x-common-params)\s*=\s*)"
    r"[^\s,;}&]+"
)


def sanitize_log_text(value: Any, *, max_length: int = 240) -> str:
    """将异常或外部文本压缩为可写入日志的脱敏摘要。"""

    limit = max(1, int(max_length))
    text = str(value).replace("\r", " ").replace("\n", " ")
    text = _AUTH_RE.sub(rf"\1{_MASK}", text)
    text = _QUERY_RE.sub(rf"\1{_MASK}", text)
    text = _QUOTED_KV_RE.sub(rf"\1{_MASK}\3", text)
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
