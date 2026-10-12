# SPDX-License-Identifier: GPL-3.0-or-later
"""无持久化 Cookie 隔离与 AsyncClient 扩展。"""

from __future__ import annotations

from typing import Any
import httpx


class IsolatedCookies(httpx.Cookies):
    """永不提取或持久化响应 Set-Cookie 的 CookieJar 封装。"""

    def extract_cookies(self, response: httpx.Response) -> None:
        """回调置空，绝不将响应 Set-Cookie 存入共享客户端状态。"""
        return


class IsolatedAsyncClient(httpx.AsyncClient):
    """强制使用 IsolatedCookies 的 AsyncClient，保障请求级 Cookie 严格隔离。"""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._cookies = IsolatedCookies()
