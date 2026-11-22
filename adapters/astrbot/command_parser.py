# SPDX-License-Identifier: GPL-3.0-or-later
"""从 AstrBot 原始消息解析 /妮姬 命令，保留多词与换行尾参。"""

from __future__ import annotations

import re
from dataclasses import dataclass

# 前缀后必须是空白或结尾，避免 "#妮姬我的"、"/nikkeX" 被误吞；英文前缀不区分大小写。
_PREFIX_RE = re.compile(r"^\s*(?P<sigil>[/#]?)(?P<name>妮姬|nikke)(?=\s|$)", re.IGNORECASE)
# 插件级 #妮姬 / #nikke 入口：只匹配本插件命令，不修改宿主 wake_prefix。
HASH_PREFIX_PATTERN = re.compile(r"^\s*#(?:妮姬|nikke)(?:\s|$)", re.IGNORECASE)
_WHITESPACE_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class ParsedCommand:
    """命令名、第一个参数，以及保留原始空白（含换行）的其余尾参。"""

    command: str
    arg1: str
    tail: str


def _split_first(text: str) -> tuple[str, str]:
    text = text.lstrip()
    if not text:
        return "", ""
    parts = _WHITESPACE_RE.split(text, maxsplit=1)
    return parts[0], (parts[1] if len(parts) > 1 else "")


def parse_nikke_message(message: str) -> ParsedCommand | None:
    """解析 "[/|#]妮姬 <命令> <参数1> <尾参...>"；不是本插件命令时返回 None。"""
    match = _PREFIX_RE.match(message or "")
    if match is None:
        return None
    command, rest = _split_first(message[match.end():])
    arg1, tail = _split_first(rest)
    return ParsedCommand(command, arg1, tail.strip())


def normalize_nikke_prefix(text: str) -> str:
    """将 #妮姬 / #nikke 规范化为 /妮姬 / /nikke；前缀后须为空白或结尾。"""
    match = _PREFIX_RE.match(text or "")
    if match is None or match.group("sigil") != "#":
        return text
    name = "妮姬" if match.group("name") == "妮姬" else "nikke"
    return "/" + name + text[match.end():]
