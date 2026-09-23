# SPDX-License-Identifier: GPL-3.0-or-later
"""账号绑定 Web integration provider。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ...features.account.ports import AccountStorePort
from ...integrations.blablalink.client import BlaBlaClient
from ...integrations.web.service import BindingWebService


def create_binding_web_service(
    store: AccountStorePort,
    client: BlaBlaClient,
    extension_zip: Path,
    config: dict[str, Any],
) -> BindingWebService:
    """创建唯一绑定 Web 服务并显式传入共享端口和运行参数。"""
    public_base_url = str(
        config.get("public_base_url", "https://nikke.irises777.xyz")
    ).rstrip("/")
    return BindingWebService(
        store,
        client,
        extension_zip,
        str(config.get("binding_api_key", "")),
        public_base_url=public_base_url,
    )
