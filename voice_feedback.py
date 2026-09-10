# SPDX-License-Identifier: GPL-3.0-or-later
"""语音发送与 Adapter 兼容性解析。

遵循 contracts/daily_voice_feedback.md：
明确 Adapter 原生语音支持兼容性矩阵，未确认适配器不发送语音。
"""

from __future__ import annotations


class VoiceResolver:
    # 已验证支持原生语音发送的 Adapter 矩阵
    SUPPORTED_VOICE_ADAPTERS = {"aiocqhttp", "onebot_v11"}

    @classmethod
    def is_voice_supported(cls, adapter_name: str) -> bool:
        return str(adapter_name or "").lower() in cls.SUPPORTED_VOICE_ADAPTERS

