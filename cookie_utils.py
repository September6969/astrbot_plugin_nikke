# SPDX-License-Identifier: GPL-3.0-or-later
"""Cookie 解析工具（与凭据无关的纯文本操作）。"""

from __future__ import annotations


def parse_cookie(cookie: str) -> dict[str, str]:
    """将 Cookie 字符串解析为 name→value 字典。

    规则：
    - 分号分隔键值对；
    - 每对用第一个 '=' 拆分，忽略没有 '=' 的片段；
    - 键名去除首尾空白，且不能为空。
    """
    result: dict[str, str] = {}
    for part in cookie.split(";"):
        if "=" not in part:
            continue
        name, value = part.strip().split("=", 1)
        if name:
            result[name] = value
    return result
