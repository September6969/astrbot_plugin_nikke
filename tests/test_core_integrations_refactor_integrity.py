# SPDX-License-Identifier: GPL-3.0-or-later
"""验证 Core 与 Integrations 模块隔离及根目录兼容性 shim 的完整性与一致性。"""

import pytest


def test_core_modules_importable():
    from astrbot_plugin_nikke.core.asset_manager import AssetManager
    from astrbot_plugin_nikke.core.config import normalize_runtime_config
    from astrbot_plugin_nikke.core.cookie_utils import parse_cookie
    from astrbot_plugin_nikke.core.feedback import DelayedFeedbackManager
    from astrbot_plugin_nikke.core.health import collect_runtime_health
    from astrbot_plugin_nikke.core.privacy import safe_exception_message
    from astrbot_plugin_nikke.core.storage import NikkeStore

    assert AssetManager is not None
    assert normalize_runtime_config is not None
    assert parse_cookie is not None
    assert DelayedFeedbackManager is not None
    assert collect_runtime_health is not None
    assert safe_exception_message is not None
    assert NikkeStore is not None


def test_integrations_modules_importable():
    from astrbot_plugin_nikke.integrations.blablalink.client import BlaBlaClient
    from astrbot_plugin_nikke.integrations.nikke_db.provider import NikkeDbProvider
    from astrbot_plugin_nikke.integrations.web.service import BindingWebService
    from astrbot_plugin_nikke.integrations.spine.config import build_spine_renderer
    from astrbot_plugin_nikke.integrations.spine.prerenderer import SpinePreRenderer
    from astrbot_plugin_nikke.integrations.spine.worker_caller import SpineWorkerRuntime

    assert BlaBlaClient is not None
    assert NikkeDbProvider is not None
    assert BindingWebService is not None
    assert build_spine_renderer is not None
    assert SpinePreRenderer is not None
    assert SpineWorkerRuntime is not None


def test_core_integrations_root_isolation():
    # 验证旧根目录垫片已被彻底收敛，不再暴露于包根
    legacy_core_shims = [
        "asset_manager",
        "storage",
        "client",
        "spine_prerenderer",
        "spine_renderer",
        "spine_runtime",
        "spine_runtime_config",
        "runtime_config",
        "runtime_health",
        "cookie_utils",
        "log_privacy",
        "web_service",
    ]
    for shim in legacy_core_shims:
        with pytest.raises(ModuleNotFoundError):
            __import__(f"astrbot_plugin_nikke.{shim}")

