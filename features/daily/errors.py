# SPDX-License-Identifier: GPL-3.0-or-later
"""Daily 写操作的跨适配器结果错误。"""


class UnknownAfterActionError(RuntimeError):
    """写操作已尝试但结果未确认，必须禁止自动重放。"""
