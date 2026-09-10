# SPDX-License-Identifier: GPL-3.0-or-later
"""角色语音与戳一戳反馈解析器。

遵循 contracts/daily_voice_feedback.md：
1. 语言/locale 感知，不单以角色 ID 硬编码；
2. 明确 Adapter 兼容性矩阵，未确认适配器安全降级纯文本；
3. 为常见妮姬提供符合人设的互动台词。
"""

from __future__ import annotations

import random
from typing import Any


class VoiceResolver:
    # 已验证支持原生语音发送的 Adapter 矩阵（未验证 adapter 一律降级文本）
    SUPPORTED_VOICE_ADAPTERS = {"aiocqhttp", "onebot_v11"}

    @classmethod
    def is_voice_supported(cls, adapter_name: str) -> bool:
        return str(adapter_name or "").lower() in cls.SUPPORTED_VOICE_ADAPTERS

