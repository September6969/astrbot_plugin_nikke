# SPDX-License-Identifier: GPL-3.0-or-later
"""账号领域应用 provider。"""

from __future__ import annotations

from collections.abc import Callable
from secrets import token_urlsafe

from ...features.account.application import AccountApplication
from ...features.account.ports import AccountStorePort


def create_account_application(
    store: AccountStorePort,
    *,
    token_factory: Callable[[int], str] = token_urlsafe,
) -> AccountApplication:
    """以调用方提供的持久化端口创建账号应用。"""
    return AccountApplication(store, token_factory=token_factory)
