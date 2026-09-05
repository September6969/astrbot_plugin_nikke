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
    # 语言/Locale 台词库
    CHARACTER_LINES: dict[str, dict[str, list[str]]] = {
        "alice": {
            "zh-cn": [
                "指挥官，兔兔爱丽丝在这里哦！今天也要一起在仙境里冒险吗？",
                "呀！好痒呀指挥官～是不是在找胡萝卜？",
                "噗通噗通～指挥官的心跳声，爱丽丝听得到哦！",
            ],
            "en": [
                "Commander! Alice the bunny is here! Are we going to Wonderland today?",
                "Eek! That tickles, Commander!",
            ],
        },
        "red_hood": {
            "zh-cn": [
                "哟，指挥官！这么精神啊？要不要来听一首我的珍藏磁带？",
                "戳我干嘛？有这闲工夫不如去干翻几只莱彻！",
                "哈哈，指挥官，你这家伙还挺对我的脾气嘛。",
            ],
            "en": [
                "Yo, Commander! Looking lively today! Care for a track from my tape collection?",
            ],
        },
        "anis": {
            "zh-cn": [
                "哇啊！指挥官突然戳我干什么啦，碳酸饮料都差点洒出来了！",
                "又来找我偷懒了对吧？我就知道！",
                "给，分你半罐汽水，喝完要好好工作哦～",
            ],
            "en": [
                "Whoa! Commander, why'd you poke me? I almost spilled my soda!",
            ],
        },
        "rapi": {
            "zh-cn": [
                "指挥官，有什么新指示吗？反击部队随时待命。",
                "请专心应对作战任务，指挥官。",
                "……如果这样能让您放松的话，我并不介意。",
            ],
            "en": [
                "Commander, do you have orders for Counters?",
            ],
        },
        "scarlet": {
            "zh-cn": [
                "哈哈，指挥官！来得正好，月色尚好，何不与小女子对饮一杯？",
                "拔刀之意，存乎一心。指挥官可要试剑？",
            ],
            "en": [
                "Hahaha, Commander! You arrive just in time. Shall we share a drink under the moon?",
            ],
        },
        "dorothy": {
            "zh-cn": [
                "指挥官……请注意您的举止。不过，若是您的话，偶尔破例一次也无妨呢。",
                "乐园的钟声，您听到了吗？",
            ],
            "en": [
                "Commander... please mind your manners.",
            ],
        },
    }

    # 已验证支持原生语音发送的 Adapter 矩阵（未验证 adapter 一律降级文本）
    SUPPORTED_VOICE_ADAPTERS = {"aiocqhttp", "onebot_v11"}

    @classmethod
    def is_voice_supported(cls, adapter_name: str) -> bool:
        return str(adapter_name or "").lower() in cls.SUPPORTED_VOICE_ADAPTERS

    @classmethod
    def resolve_poke_line(
        cls,
        character_key: str = "alice",
        locale: str = "zh-cn",
    ) -> str:
        """解析戳一戳台词。"""
        char_key = str(character_key or "alice").lower()
        loc = str(locale or "zh-cn").lower()

        char_dict = cls.CHARACTER_LINES.get(char_key) or cls.CHARACTER_LINES["alice"]
        lines = char_dict.get(loc) or char_dict.get("zh-cn") or ["指挥官，有什么吩咐吗？"]
        return random.choice(lines)

