"""整仓重构门禁；初始红灯记录旧结构，后续按卡片逐项转绿。"""

from __future__ import annotations

import ast
from pathlib import Path

from scripts.architecture_metrics import (
    PLAN_THRESHOLDS,
    PUBLIC_METHOD_MAX_LOGICAL_STATEMENTS,
    classify_module_shape,
    collect_metrics,
    compare_metrics,
)


ROOT = Path(__file__).resolve().parents[1]
METRICS = collect_metrics(ROOT)
EXPECTED_PLAN_THRESHOLDS = {
    "main.py": 700,
    "core/asset_manager.py": 300,
    "ui/t2i_payloads.py": 100,
    "features/calendar/schedule_service.py": 450,
    "features/announcement/service.py": 450,
    "core/container.py": 350,
}


def _violations(category: str) -> list[dict[str, object]]:
    return [item for item in METRICS["gate_violations"] if item["category"] == category]


def test_metrics_cover_plan_hotspots_and_public_import_inventory() -> None:
    assert PLAN_THRESHOLDS == EXPECTED_PLAN_THRESHOLDS
    assert PUBLIC_METHOD_MAX_LOGICAL_STATEMENTS == 20
    assert set(METRICS["hotspots"]) == set(EXPECTED_PLAN_THRESHOLDS)
    assert METRICS["source_file_count"] >= 100
    assert "core/__init__.py" in METRICS["public_imports"]
    assert isinstance(METRICS["functions_by_complexity"], list)
    assert isinstance(METRICS["import_edges"], list)


def test_plan_hotspot_size_limits() -> None:
    violations = _violations("hotspot_size")
    assert not violations, f"超出 PLAN.md 热点行数门槛：{violations}"


def test_main_plugin_methods_are_thin_delegates() -> None:
    violations = _violations("main_command_size")
    assert not violations, f"main.py 中存在超过 20 个 AST 逻辑语句的方法：{violations}"
    assert not _violations("main_business_import"), METRICS["main_business_imports"]


def test_feature_and_ui_dependency_directions() -> None:
    feature_violations = _violations("feature_dependency_direction")
    ui_violations = _violations("ui_dependency_direction")
    assert not feature_violations, f"features 越过领域端口依赖边界：{feature_violations}"
    assert not ui_violations, f"ui 依赖存储或业务网络：{ui_violations}"


def test_shared_container_and_resource_owners_are_unique() -> None:
    assert METRICS["container_definitions"] == {
        "ServiceContainer": ["core/container.py"],
        "create_container": ["core/container.py"],
    }
    violations = _violations("duplicate_resource_owner")
    assert not violations, f"共享资源存在多个生产所有者：{violations}"


def test_no_default_off_profile_route() -> None:
    assert not _violations("default_off_or_legacy_route"), METRICS[
        "profile_route_flag_references"
    ]


def test_dynamic_module_forwarders_are_removed() -> None:
    assert not _violations("empty_forwarder_module"), METRICS[
        "empty_forwarder_modules"
    ]
    assert not _violations("star_import"), METRICS["star_imports"]
    assert not _violations("dynamic_module_forwarder"), METRICS[
        "dynamic_module_getattrs"
    ]


def test_internal_import_cycles_are_removed() -> None:
    assert not METRICS["import_cycles"], METRICS["import_cycles"]


def test_empty_wrapper_and_dynamic_forwarder_are_detected() -> None:
    wrapper = ast.parse("from package.large_module import execute\n")
    wrapper_shape = classify_module_shape(wrapper, "features/example/application.py")
    assert wrapper_shape["empty_forwarder"] is True

    star_wrapper = ast.parse("from package.large_module import *\n")
    star_shape = classify_module_shape(star_wrapper, "features/example/bridge.py")
    assert star_shape["empty_forwarder"] is True
    assert star_shape["star_import_lines"] == [1]

    dynamic_module = ast.parse(
        "def __getattr__(name):\n    return getattr(target, name)\n"
    )
    dynamic_shape = classify_module_shape(dynamic_module, "features/example/bridge.py")
    assert dynamic_shape["module_getattr_lines"] == [1]

    metadata_module = ast.parse("PLUGIN_VERSION = '0.2.0'\n")
    metadata_shape = classify_module_shape(metadata_module, "_version.py")
    assert metadata_shape["empty_forwarder"] is False


def test_comparison_format_keeps_hotspot_before_after_values() -> None:
    comparison = compare_metrics(METRICS, METRICS)
    assert set(comparison["hotspot_line_deltas"]) == set(PLAN_THRESHOLDS)
    assert all(
        item["delta_lines"] == 0
        for item in comparison["hotspot_line_deltas"].values()
    )
    assert comparison["cycles_added"] == []
    assert comparison["cycles_removed"] == []
    assert comparison["gate_violation_count_deltas"] == {
        category: 0 for category in METRICS["gate_violation_counts"]
    }
