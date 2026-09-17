# SPDX-License-Identifier: GPL-3.0-or-later
"""Issue #82 架构收敛与仓库完整性验收测试。"""

import importlib
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class RepositoryIntegrityTests(unittest.TestCase):
    """验证 Issue #82 重构后架构分层、模块导出、根目录存根与元数据一致性。"""

    def test_package_root_import_and_version(self):
        """验证包根级导入成功且版本号三向对齐。"""
        import astrbot_plugin_nikke
        from astrbot_plugin_nikke._version import PLUGIN_VERSION

        self.assertIsNotNone(astrbot_plugin_nikke)
        self.assertTrue(PLUGIN_VERSION)

        # 检查 metadata.yaml
        metadata = (ROOT / "metadata.yaml").read_text(encoding="utf-8")
        match = re.search(r"^version:\s*([^\s#]+)\s*$", metadata, re.MULTILINE)
        self.assertIsNotNone(match)
        self.assertEqual(match.group(1), PLUGIN_VERSION)

        # 检查 CHANGELOG.md
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn(f"## {PLUGIN_VERSION}（当前 main 基线）", changelog)

    def test_architectural_directories_exist(self):
        """验证所有核心架构分层目录均已建立且含有 __init__.py。"""
        expected_dirs = [
            ROOT / "ui",
            ROOT / "ui" / "renderers",
            ROOT / "features",
            ROOT / "features" / "character",
            ROOT / "features" / "profile",
            ROOT / "features" / "raid",
            ROOT / "features" / "campaign",
            ROOT / "features" / "daily",
            ROOT / "features" / "tarot",
            ROOT / "features" / "cdk",
            ROOT / "features" / "voice",
            ROOT / "features" / "calendar",
            ROOT / "features" / "announcement",
            ROOT / "features" / "tower",
            ROOT / "features" / "guide",
            ROOT / "core",
            ROOT / "integrations",
            ROOT / "integrations" / "blablalink",
            ROOT / "integrations" / "spine",
            ROOT / "integrations" / "nikke_db",
            ROOT / "integrations" / "web",
            ROOT / "assets" / "data",
            ROOT / "assets" / "fonts",
            ROOT / "assets" / "icons",
            ROOT / "docs" / "architecture",
            ROOT / "docs" / "acceptance",
        ]
        for d in expected_dirs:
            with self.subTest(dir=str(d.relative_to(ROOT))):
                self.assertTrue(d.is_dir(), f"目录缺失: {d}")
                if "assets" not in d.parts and "docs" not in d.parts:
                    self.assertTrue((d / "__init__.py").is_file(), f"缺失 __init__.py: {d}")

    def test_root_shims_backward_compatibility(self):
        """验证根目录下各模块垫片可透明导入且正确导出关键符号。"""
        shim_checks = [
            ("renderer", "CardRenderer"),
            ("character_card_renderer", "CharacterCardRenderer"),
            ("profile_card_renderer", "ProfileCardRenderer"),
            ("union_raid_renderer", "UnionRaidRenderer"),
            ("campaign_history_renderer", "CampaignHistoryRenderer"),
            ("card_builder", "CharacterCardBuilder"),
            ("profile_builder", "ProfileBuilder"),
            ("union_raid_builder", "UnionRaidBuilder"),
            ("campaign_history_builder", "CampaignHistoryBuilder"),
            ("daily_runner", "DailyRunner"),
            ("tarot_service", "TarotService"),
            ("cdk_service", "CdkService"),
            ("asset_manager", "AssetManager"),
            ("container", "ServiceContainer"),
            ("storage", "NikkeStore"),
            ("client", "BlaBlaClient"),
            ("spine_renderer", "SpineRenderer"),
            ("nikke_db_provider", "NikkeDbProvider"),
            ("web_service", "BindingWebService"),
        ]
        for mod_name, symbol_name in shim_checks:
            with self.subTest(module=mod_name, symbol=symbol_name):
                mod = importlib.import_module(f"astrbot_plugin_nikke.{mod_name}")
                self.assertTrue(hasattr(mod, symbol_name), f"模块 {mod_name} 缺失符号 {symbol_name}")

    def test_assets_structured_registries_exist(self):
        """验证 assets/data 中的 21 个核心结构化数据表均真实存在且可解析。"""
        data_dir = ROOT / "assets" / "data"
        self.assertTrue(data_dir.is_dir())
        json_files = list(data_dir.glob("*.json"))
        self.assertGreaterEqual(len(json_files), 15, "assets/data 结构化 JSON 数量不足")
        for jf in json_files:
            with self.subTest(file=jf.name):
                content = json.loads(jf.read_text(encoding="utf-8"))
                self.assertIsNotNone(content)

    def test_docs_readme_index_complete(self):
        """验证 docs/README.md 索引文件存在且包含分类导航。"""
        docs_readme = ROOT / "docs" / "README.md"
        self.assertTrue(docs_readme.is_file(), "docs/README.md 缺失")
        text = docs_readme.read_text(encoding="utf-8")
        self.assertIn("architecture/", text)
        self.assertIn("acceptance/", text)
        self.assertIn("evidence/", text)


if __name__ == "__main__":
    unittest.main()
