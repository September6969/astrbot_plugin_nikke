# SPDX-License-Identifier: GPL-3.0-or-later
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from PIL import Image

from astrbot_plugin_nikke.core.asset_manager import AssetManager
from astrbot_plugin_nikke.features.character.registries.static import StaticDataRegistry
from astrbot_plugin_nikke.features.character.replica import replica_font
from astrbot_plugin_nikke.features.profile.currency_registry import CurrencyRegistry


class AssetsRefactorIntegrityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[1]
        cls.assets_dir = cls.root / "assets"
        cls.fonts_dir = cls.assets_dir / "fonts"

    def test_canonical_fonts_structure(self):
        """验证 assets/fonts/ 包含全套所需字体与许可证。"""
        self.assertTrue(self.fonts_dir.is_dir(), "fonts 目录必须存在")

        # PR-6A G2-fonts-license-a：未被运行时使用的 NotoSansHans-*.otf 已删除。
        expected_fonts = [
            "ReplicaSans.otf",
            "NotoSansSC-ReplicaSubset-700.woff2",
            "NotoSansSC-ReplicaSubset-800.woff2",
        ]
        for font_name in expected_fonts:
            root_font = self.fonts_dir / font_name
            self.assertTrue(root_font.is_file(), f"fonts/{font_name} 必须存在")
        for removed in ("NotoSansHans-Medium.otf", "NotoSansHans-Regular.otf"):
            self.assertFalse((self.fonts_dir / removed).exists(), f"fonts/{removed} 不应重新引入")

        # 验证许可证完整保留（ReplicaSans.otf 为 Apache 2.0 修改版，G2-fonts-license-b）
        for lic in ["OFL-BarlowCondensed.txt", "OFL-NotoSansSC.txt", "OFL-Rajdhani.txt", "LICENSE-Apache-2.0.txt"]:
            self.assertTrue((self.fonts_dir / lic).is_file(), f"许可证 {lic} 必须随分发保留")

        # NOTICE 必须登记第三方字体、Nikke-db 归属与 Spine runtime，且引用的许可证文件存在。
        notice = (self.root / "NOTICE").read_text(encoding="utf-8")
        for token in ("Nikke-db", "a2358b72bd1335c30737e46482a99947f3788bc7", "Spine Runtimes License", "ReplicaSans.otf"):
            self.assertIn(token, notice)
        for lic in ("OFL-NotoSansSC.txt", "OFL-BarlowCondensed.txt", "OFL-Rajdhani.txt", "LICENSE-Apache-2.0.txt"):
            self.assertIn(f"assets/fonts/{lic}", notice)

        # 根目录不再保存重复内置字体。
        self.assertFalse((self.root / "fonts").exists())

    def test_evidence_fonts_prefer_bundled_cjk_before_latin_only(self):
        """PR-6A：离线证据脚本字体候选中，所有支持中文的字体排在纯拉丁字体之前。"""
        from PIL import ImageFont

        from astrbot_plugin_nikke.scripts.shared.evidence_fonts import evidence_font_candidates, get_evidence_font

        for bold in (False, True):
            names = [path.name for path in evidence_font_candidates(bold=bold)]
            self.assertTrue(names[0].startswith("NotoSansSC-ReplicaSubset-"))
            self.assertEqual(names[1], "ReplicaSans.otf")
            latin_first = min(names.index(n) for n in names if n.startswith(("BarlowCondensed", "arial", "DejaVu")))
            cjk_last = max(names.index(n) for n in names if n in {"msyh.ttc", "simhei.ttf", "NotoSansCJK-Regular.ttc", "PingFang.ttc", "Arial Unicode.ttf"})
            self.assertLess(cjk_last, latin_first)
            font = get_evidence_font(24, bold=bold)
            self.assertIsInstance(font, ImageFont.FreeTypeFont)
            self.assertIn(Path(font.path).parent, {self.fonts_dir})
            self.assertIsNotNone(font.getmask("拉毗：小红帽").getbbox())

    def test_assets_data_structure(self):
        """验证 assets/data/ 包含所有已规范化的数据清单，且已完成单一来源治理（根目录无重复）。"""
        data_dir = self.assets_dir / "data"
        self.assertTrue(data_dir.is_dir(), "assets/data 目录必须存在")

        expected_data_files = [
            "campaign_stages.json",
            "campaign_stages.source.json",
            "character_aliases.json",
            "character_catalog.json",
            "character_master.json",
            "character_weapon_bases.json",
            "costumes.json",
            "cubes.json",
            "equipment.json",
            "face_anchors.json",
            "favorite_items.json",
            "overload_tiers.json",
            "raid_raid_list.json",
            "registry_manifest.json",
            "remote_sources.json",
            "sources.json",
            "spine_manifest.json",
            "spine_manifest.schema.json",
            "state_effects.json",
            "tower_floors.json",
            "voice_poke_map.json",
        ]
        for name in expected_data_files:
            data_file = data_dir / name
            self.assertTrue(data_file.is_file(), f"assets/data/{name} 必须存在")
            legacy_file = self.assets_dir / name
            self.assertFalse(legacy_file.is_file(), f"assets/{name} 不应在根 assets 存在重复副本")

    def test_assets_icons_structure(self):
        """验证 assets/icons/ 是 cube, favorite, currency 的唯一内置位置（PR-6A G1-icons-a）。"""
        icons_dir = self.assets_dir / "icons"
        self.assertTrue(icons_dir.is_dir(), "assets/icons 目录必须存在")
        for sub in ("cube", "favorite", "currency"):
            sub_dir = icons_dir / sub
            self.assertTrue(sub_dir.is_dir(), f"assets/icons/{sub} 必须存在")
            self.assertGreater(len(list(sub_dir.iterdir())), 0, f"assets/icons/{sub} 不可为空")
            # 旧顶层副本已删除，不得重新引入。
            self.assertFalse((self.assets_dir / sub).exists(), f"assets/{sub} 不应作为重复副本存在")

        data_dir = self.assets_dir / "data"
        for sub, data_name in (("cube", "cubes.json"), ("favorite", "favorite_items.json")):
            expected = set(json.loads((data_dir / data_name).read_text(encoding="utf-8")))
            stems = {path.stem for path in (icons_dir / sub).glob("*.png")}
            self.assertEqual(stems, expected, f"assets/icons/{sub} 必须与 {data_name} 一一对应")

        currency_dir = icons_dir / "currency"
        self.assertTrue((currency_dir / "README.md").is_file())
        readme = (currency_dir / "README.md").read_text(encoding="utf-8")
        for definition in CurrencyRegistry.DEFINITIONS.values():
            if not definition.icon_key:
                continue
            matches = [currency_dir / f"{definition.icon_key}{suffix}" for suffix in (".png", ".webp")]
            existing = [path for path in matches if path.is_file()]
            self.assertEqual(len(existing), 1, f"货币图标 {definition.icon_key} 必须且仅有一个文件")
            digest = hashlib.sha256(existing[0].read_bytes()).hexdigest()
            self.assertEqual(digest, definition.source_sha256)
            # README 表格行与 registry 一致（type | 文件 | SHA-256）。
            self.assertIn(
                f"| {definition.type} | `{existing[0].name}` | `{definition.source_sha256}` |",
                readme,
            )

    def test_no_unexpected_byte_identical_assets(self):
        """PR-6A：assets/ 下不得新增逐字节重复文件；仅保留已核查的重复组。

        直接遍历文件系统（发行 zip 没有 .git），先按大小分组再哈希。
        """
        ignored = {"fonts/NotoSansSC-wght.ttf"}  # .gitignore：按需下载的完整可变字体
        by_size: dict[int, list[Path]] = {}
        for path in self.assets_dir.rglob("*"):
            if path.is_file() and path.relative_to(self.assets_dir).as_posix() not in ignored:
                by_size.setdefault(path.stat().st_size, []).append(path)
        groups: dict[str, list[str]] = {}
        for paths in by_size.values():
            if len(paths) < 2:
                continue
            for path in paths:
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                groups.setdefault(digest, []).append(path.relative_to(self.assets_dir).as_posix())

        def allowed(members: list[str]) -> bool:
            dirs = {str(Path(member).parent) for member in members}
            names = {Path(member).name for member in members}
            # G1-icons-e：收藏品 tid 别名（1001x1 / 1001x2）共用上游资源。
            if dirs == {"icons/favorite"}:
                return True
            # G1-icons-f：技能图标为不同上游名称，按名称引用。
            if dirs == {"skills"}:
                return True
            # G1-icons-g：服装身份键控的上游复用。
            if set(members) == {
                "blablalink/character/si/si_c810_00_s.webp",
                "blablalink/character/si/si_c810_01_s.webp",
            }:
                return True
            # 所有者决定：boss 与 icon/monster_full 镜像暂不去重。
            if dirs == {"blablalink/boss", "blablalink/icon/monster_full"} and len(names) == 1:
                return True
            # 所有者决定：raid_raid_list.json 两份副本暂不处理。
            if set(members) == {"data/raid_raid_list.json", "manifests/blablalink/raid_raid_list.json"}:
                return True
            return False

        unexpected = sorted(sorted(members) for members in groups.values() if len(members) > 1 and not allowed(members))
        self.assertEqual(unexpected, [], f"发现未登记的逐字节重复资产: {unexpected}")

    def test_asset_audit_gate_covers_bundled_icons(self):
        """PR-6A G1-icons-j：audit_assets 必须检查内置魔方/收藏品/货币图标，缺失时门禁失败。"""
        import contextlib
        import io
        import shutil

        from astrbot_plugin_nikke.scripts.audit.audit_assets import audit_gate_passed, run_asset_audit

        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            (base / "assets").symlink_to(self.assets_dir, target_is_directory=True)
            with contextlib.redirect_stdout(io.StringIO()):
                report = run_asset_audit(base)
            summary = report["summary"]
            self.assertEqual(summary["cubes_local_hit"], summary["cubes_total"])
            self.assertEqual(summary["favorite_items_local_hit"], summary["favorite_items_total"])
            self.assertEqual(summary["currency_icons_local_hit"], summary["currency_icons_total"])
            self.assertTrue(audit_gate_passed(report))

            # 仅保留数据与映射、去掉内置图标后，门禁必须失败。
            broken = base / "broken"
            (broken / "assets").mkdir(parents=True)
            for sub in ("data", "mappings"):
                shutil.copytree(self.assets_dir / sub, broken / "assets" / sub)
            with contextlib.redirect_stdout(io.StringIO()):
                broken_report = run_asset_audit(broken)
            self.assertFalse(audit_gate_passed(broken_report))
            self.assertEqual(broken_report["summary"]["cubes_local_hit"], 0)

    def test_static_registry_loads_from_data_and_fallback(self):
        """验证 StaticDataRegistry 优先从 data/ 读取，并在无 data/ 时平滑 fallback。"""
        # 1. 正常从规范目录加载
        reg = StaticDataRegistry(self.assets_dir)
        self.assertTrue(reg.is_valid, f"StaticDataRegistry 加载失败: {reg.errors}")

        # 2. 从仅包含 data/ 子目录的临时目录加载
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            td_data = td_path / "data"
            td_data.mkdir(parents=True)
            for f in ("registry_manifest.json", "equipment.json", "cubes.json", "favorite_items.json", "costumes.json"):
                (td_data / f).write_bytes((self.assets_dir / "data" / f).read_bytes())
            reg_isolated = StaticDataRegistry(td_path)
            self.assertTrue(reg_isolated.is_valid, f"仅 data/ 结构下 StaticDataRegistry 应当有效: {reg_isolated.errors}")


    def test_replica_font_resolution(self):
        """验证 replica_font 能正常读取 ReplicaSans.otf 并返回 data URI。"""
        uri = replica_font()
        self.assertIsNotNone(uri)
        self.assertTrue(uri.startswith("data:font/otf;base64,"))

    def test_asset_manager_loads_icons_from_structured_path(self):
        """验证 AssetManager 能够从 assets/icons/ 载入图标。"""
        with tempfile.TemporaryDirectory() as td:
            am = AssetManager(cache_dir=td, asset_dir=self.assets_dir)
            icon = am.get_currency_icon(2000)
            self.assertIsNotNone(icon)
            self.assertIsInstance(icon, Image.Image)


if __name__ == "__main__":
    unittest.main()
