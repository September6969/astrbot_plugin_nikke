# SPDX-License-Identifier: GPL-3.0-or-later
"""BlaBlaLink 请求可跨越网络适配层传递的错误类型。"""


class BlaBlaError(RuntimeError):
    def __init__(self, message: str, code: str = "", endpoint: str = ""):
        super().__init__(message)
        self.code = str(code)
        self.endpoint = endpoint


class CookieExpired(BlaBlaError):
    """账号凭据已失效，需要由账号入口处理。"""
