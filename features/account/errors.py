# SPDX-License-Identifier: GPL-3.0-or-later
"""账号能力的跨适配器错误合同。"""


class CredentialExpiredError(RuntimeError):
    """认证凭据已经失效，需要停止当前账号的后续操作。"""
