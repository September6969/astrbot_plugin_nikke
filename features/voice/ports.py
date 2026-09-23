# SPDX-License-Identifier: GPL-3.0-or-later
"""语音偏好持久化端口。"""

from __future__ import annotations

from typing import Any, Protocol


class VoiceSettingsStore(Protocol):
    """只暴露语音偏好读写能力。"""

    def get_setting(self, key: str, default: Any = None) -> Any:
        """读取由语音 feature 管理的偏好。"""

    def set_setting(self, key: str, value: Any) -> None:
        """保存由语音 feature 管理的偏好。"""
