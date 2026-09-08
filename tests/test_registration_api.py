"""验证 AstrBot 插件自动注册和元数据合同。"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_metadata_keeps_plugin_repository():
    metadata = (REPO_ROOT / "metadata.yaml").read_text(encoding="utf-8")

    assert "name: astrbot_plugin_nikke" in metadata
    assert "repo: https://github.com/September6969/astrbot_plugin_nikke" in metadata


def test_import_uses_star_auto_registration_without_deprecated_decorator():
    script = """
import warnings

warnings.filterwarnings(
    "error",
    message=r"The 'register_star' decorator is deprecated.*",
    category=DeprecationWarning,
)

from astrbot_plugin_nikke.main import NikkePlugin
from astrbot.core.star import star_map

metadata = star_map[NikkePlugin.__module__]
assert metadata.star_cls_type is NikkePlugin
print(metadata.module_path)
"""
    environment = os.environ.copy()
    parent = str(REPO_ROOT.parent)
    existing_pythonpath = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = (
        parent
        if not existing_pythonpath
        else parent + os.pathsep + existing_pythonpath
    )

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPO_ROOT.parent,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, (
        "AstrBot 自动注册导入失败:\n"
        f"stdout={result.stdout}\n"
        f"stderr={result.stderr}"
    )
