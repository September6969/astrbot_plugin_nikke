# SPDX-License-Identifier: GPL-3.0-or-later
"""绑定 Web 服务使用窄存储端口且维持现有 HTTP 合同。"""

from __future__ import annotations

import inspect
from typing import get_type_hints

from astrbot_plugin_nikke.integrations.web.ports import BindingSessionStore
from astrbot_plugin_nikke.integrations.web.service import BindingWebService


def test_binding_service_depends_on_narrow_store_protocol() -> None:
    annotation = get_type_hints(BindingWebService.__init__)["store"]

    assert annotation is BindingSessionStore
    assert getattr(BindingSessionStore, "_is_protocol", False)
    assert {
        "db_path",
        "key_path",
        "create_bind_session",
        "get_bind_session",
        "fail_bind_session",
        "consume_bind_session",
        "get_account",
    }.issubset(set(BindingSessionStore.__annotations__) | set(dir(BindingSessionStore)))

    service_module = inspect.getmodule(BindingWebService)
    assert service_module is not None
    service_source = inspect.getsource(service_module)
    assert "NikkeStore" not in service_source
    assert "core.storage" not in service_source
