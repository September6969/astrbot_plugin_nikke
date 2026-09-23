"""公告职责拆分的架构合同。"""

from __future__ import annotations

import ast
from pathlib import Path

from astrbot_plugin_nikke.features.announcement.models import AnnouncementRecord
from astrbot_plugin_nikke.features.announcement.normalization import AnnouncementVersioning

FEATURES = Path(__file__).parents[1] / "features" / "announcement"


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def test_announcement_service_is_a_compact_coordinator_facade() -> None:
    service_path = FEATURES / "service.py"
    source = service_path.read_text(encoding="utf-8")
    assert len(source.splitlines()) <= 450

    tree = _tree(service_path)
    service = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "AnnouncementService"
    )
    imported_owners = {
        alias.name
        for node in tree.body
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    assert {
        "AnnouncementNormalizer",
        "AnnouncementRepository",
        "AnnouncementSyncCoordinator",
        "AnnouncementQuery",
        "AnnouncementDiagnostics",
    } <= imported_owners
    assert len(service.body) <= 45


def test_announcement_responsibilities_have_distinct_modules() -> None:
    expected = {
        "normalization.py": "AnnouncementNormalizer",
        "repository.py": "AnnouncementRepository",
        "synchronization.py": "AnnouncementSyncCoordinator",
        "query.py": "AnnouncementQuery",
        "diagnostics.py": "AnnouncementDiagnostics",
    }
    for filename, class_name in expected.items():
        tree = _tree(FEATURES / filename)
        assert any(
            isinstance(node, ast.ClassDef) and node.name == class_name
            for node in tree.body
        ), f"{filename} must own {class_name}"
    normalizer_tree = _tree(FEATURES / "normalization.py")
    assert any(
        isinstance(node, ast.ClassDef) and node.name == "AnnouncementVersioning"
        for node in normalizer_tree.body
    )


def test_announcement_query_is_local_and_source_free() -> None:
    tree = _tree(FEATURES / "query.py")
    forbidden_modules = {"httpx", ".sources", ".application"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert not any(alias.name in forbidden_modules for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.module not in forbidden_modules
        elif isinstance(node, ast.Call):
            called_name = (
                node.func.id
                if isinstance(node.func, ast.Name)
                else node.func.attr
                if isinstance(node.func, ast.Attribute)
                else ""
            )
            assert called_name not in {"fetch", "fetch_primary", "fetch_official", "sync_from_source"}


def test_announcement_source_adapter_does_not_import_application() -> None:
    tree = _tree(FEATURES / "sources.py")
    assert not any(
        isinstance(node, ast.ImportFrom)
        and node.module is not None
        and node.module.endswith("application")
        for node in ast.walk(tree)
    )
    assert not any(
        isinstance(node, ast.Import)
        and any(alias.name.endswith("announcement.application") for alias in node.names)
        for node in ast.walk(tree)
    )


def test_announcement_versioning_keeps_stale_and_deadline_versions_distinct() -> None:
    current = AnnouncementRecord("event-1", "活动", "当前内容", "2026-09-01")
    stale = AnnouncementRecord("event-1", "活动", "旧内容", "2026-09-01")
    updated = AnnouncementRecord("event-1", "活动", "新内容", "2026-09-01")

    assert AnnouncementVersioning.classify(None, current.content_fingerprint, []) == "new"
    assert (
        AnnouncementVersioning.classify(
            current, current.content_fingerprint, [current.content_fingerprint]
        )
        == "unchanged"
    )
    assert (
        AnnouncementVersioning.classify(
            current,
            stale.content_fingerprint,
            [current.content_fingerprint, stale.content_fingerprint],
        )
        == "stale"
    )
    assert (
        AnnouncementVersioning.classify(
            current, updated.content_fingerprint, [current.content_fingerprint]
        )
        == "updated"
    )
    deadlines = [("event-1_0", None, "2026-09-10T00:00:00+00:00")]
    assert AnnouncementVersioning.next_versions(current, deadlines, deadlines) == (2, 1)
    assert AnnouncementVersioning.next_versions(current, deadlines, []) == (2, 2)
