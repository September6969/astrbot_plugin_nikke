# SPDX-License-Identifier: GPL-3.0-or-later
"""命令处理器共享的用户可见错误文案，不暴露 Python 类名或凭据。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ...core.privacy import sanitize_log_text

CREDENTIAL_EXPIRED_TEXT = "登录状态已失效，请私聊发送 /妮姬 账号 绑定 重新绑定。"


def user_error_message(exc: BaseException, *, fallback: str = "请稍后重试") -> str:
    """返回脱敏后的异常说明（不含异常类名）；为空时使用兜底文案。"""
    message = sanitize_log_text(exc, max_length=160).strip()
    return message or fallback


def invalidate_credentials(
    actor_id: str,
    *,
    store: Any = None,
    client: Any = None,
    invalidate: Callable[[str], None] | None = None,
) -> None:
    """凭据失效时标记账号并清理客户端内存缓存；任一步骤缺失时跳过。"""
    if invalidate is not None:
        invalidate(actor_id)
        return
    mark = getattr(store, "mark_cookie_invalid", None)
    if callable(mark):
        mark(actor_id)
    clear = getattr(client, "invalidate_cache", None)
    if callable(clear):
        clear(actor_id)
