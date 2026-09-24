# SPDX-License-Identifier: GPL-3.0-or-later
"""游戏资源 CDN 的稳定路径编码合同。"""

from __future__ import annotations

import hashlib
from pathlib import Path


def game_resource_url(path: str) -> str:
    """按官网资源路径合同生成 CDN 地址。"""
    path = path.lstrip("/")
    buckets = []
    for seed in (224737, 1000639, 2654435761, 2654435769, 1000621, 4294967291)[:path.count("/")]:
        value = seed
        for char in path:
            value = (value * 33 + ord(char)) & 0xFFFFFFFF
        signed = value if value < 0x80000000 else value - 0x100000000
        modulo = signed % seed
        buckets.append(f"{chr(97 + modulo // 26 % 26)}{chr(97 + modulo % 26)}-{modulo % 99:02d}")
    filename = hashlib.md5(path.encode("utf-8")).hexdigest() + Path(path).suffix
    return "https://sg-tools-cdn.blablalink.com/" + "/".join([*buckets, filename])
