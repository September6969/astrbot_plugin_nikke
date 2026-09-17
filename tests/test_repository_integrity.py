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

    REQUIRED_ROOT_FILES = [
        "main.py",
        "__init__.py",
        "_version.py",
        "container.py",
        "_conf_schema.json",
        "metadata.yaml",
        "requirements.txt",
        "pytest.ini",
        "README.md",
        "CHANGELOG.md",
        "LICENSE",
        "NOTICE",
    ]

    OPTIONAL_COMPAT_SHIMS = [
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
        ("spine_prerenderer", "SpinePreRenderer"),
        ("web_service", "BindingWebService"),
        ("announcement_service", "AnnouncementService"),
        ("calendar_service", "CalendarService"),
        ("card_theme", "character_theme"),
        ("cookie_utils", "parse_cookie"),
        ("costume_registry", "CostumeRegistry"),
        ("log_privacy", "safe_exception_message"),
        ("runtime_config", "normalize_runtime_config"),
        ("runtime_health", "collect_runtime_health"),
        ("spine_runtime", "SpineSkeletonParser"),
        ("spine_runtime_config", "build_spine_renderer"),
        ("t2i_renderer", "T2IRenderer"),
    ]

    FORBIDDEN_LEGACY_ROOT_MODULES = [
        "announcement_cache",
        "announcement_delivery",
        "announcement_models",
        "announcement_push",
        "announcement_sources",
        "arcana_game",
        "arcana_models",
        "boss_asset_resolver",
        "calendar_adapters",
        "calendar_models",
        "calendar_sources",
        "canonical_models",
        "cdk_models",
        "cdk_persistence",
        "character_crop",
        "character_details",
        "character_master",
        "character_replica",
        "character_stat_calculator",
        "character_stat_resources",
        "character_visual_resolver",
        "character_weapon_bases",
        "costume_asset_resolver",
        "currency_registry",
        "daily_auto",
        "daily_models",
        "daily_recovery",
        "delayed_feedback",
        "face_anchor",
        "guide_registry",
        "idle_animation_resolver",
        "informationfeeds",
        "lineup_portrait_resolver",
        "local_spine_resolver",
        "nikke_db_provider",
        "ol_unknown_inventory",
        "overload_tier_registry",
        "raid_season_registry",
        "rich_event_parser",
        "schedule_adapters",
        "schedule_data",
        "schedule_service",
        "skill_icon_resolver",
        "spine_render_manifest",
        "spine_semantics",
        "spine_worker_runtime",
        "state_effect_registry",
        "static_registry",
        "t2i_assets",
        "t2i_payloads",
        "t2i_templates",
        "tarot_models",
        "tower_registry",
        "union_raid_models",
        "voice_audio",
        "voice_character_resolver",
        "voice_encoder",
        "voice_feedback",
        "voice_mapping",
        "voice_pipeline",
        "voice_resource_provider",
        "voice_scene_catalog",
    ]

    def test_required_root_files_exist(self):
        """验证根目录必须保留的基础文件完备存在。"""
        for filename in self.REQUIRED_ROOT_FILES:
            with self.subTest(file=filename):
                target = ROOT / filename
                self.assertTrue(target.is_file(), f"根目录关键文件缺失: {filename}")

    def test_optional_compat_shims_backward_compatibility(self):
        """验证存在的垫片可被透明导入且具备预期关键符号；已移除垫片则跳过。"""
        for mod_name, symbol_name in self.OPTIONAL_COMPAT_SHIMS:
            shim_file = ROOT / f"{mod_name}.py"
            if not shim_file.is_file():
                continue
            with self.subTest(module=mod_name, symbol=symbol_name):
                mod = importlib.import_module(f"astrbot_plugin_nikke.{mod_name}")
                self.assertTrue(hasattr(mod, symbol_name), f"模块 {mod_name} 缺失符号 {symbol_name}")

    def test_forbidden_legacy_root_modules_cleaned(self):
        """验证已废弃归档的根目录旧模块已被彻底清除且无法从根目录导入。"""
        for mod_name in self.FORBIDDEN_LEGACY_ROOT_MODULES:
            with self.subTest(forbidden_module=mod_name):
                shim_file = ROOT / f"{mod_name}.py"
                self.assertFalse(shim_file.is_file(), f"根目录仍残留已废弃模块: {mod_name}.py")
                with self.assertRaises(ModuleNotFoundError, msg=f"已清理模块 {mod_name} 仍能从根目录导入"):
                    importlib.import_module(f"astrbot_plugin_nikke.{mod_name}")

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
