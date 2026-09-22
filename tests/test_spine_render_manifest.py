# SPDX-License-Identifier: GPL-3.0-or-later
"""Spine pre-rendered manifest 与 AssetManager 严格校验确定性离线测试集。"""

from __future__ import annotations

import hashlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from astrbot_plugin_nikke.core.asset_manager import AssetManager
from scripts.rebuild_spine_render_manifest import (
    audit_spine_assets,
    build_manifest_dict,
    check_png_integrity,
    verify_manifest,
)


class SpineRenderManifestTests(unittest.TestCase):
    def setUp(self):
        self.repo_root = Path(__file__).resolve().parents[1]
        self.assets_dir = self.repo_root / "assets"
        self.rendered_dir = self.assets_dir / "spine-rendered"
        self.manifest_path = self.assets_dir / "spine_manifest.json"
        self.master_path = self.assets_dir / "character_master.json"
        self.costumes_path = self.assets_dir / "costumes.json"

    def test_manifest_generation_is_deterministic(self):
        """测试 manifest 生成结果在多次执行间字节完全一致。"""
        res1 = audit_spine_assets(self.rendered_dir, self.manifest_path, self.master_path, self.costumes_path)
        dict1 = build_manifest_dict(res1)
        res2 = audit_spine_assets(self.rendered_dir, self.manifest_path, self.master_path, self.costumes_path)
        dict2 = build_manifest_dict(res2)

        # 忽略动态时间戳比较
        dict1.pop("generated_at", None)
        dict2.pop("generated_at", None)
        self.assertEqual(dict1, dict2)

    def test_sha256_correctness_on_disk(self):
        """测试磁盘上的每个预渲染 PNG 真实 SHA-256 均与 manifest 声明完全吻合。"""
        self.assertTrue(self.manifest_path.is_file(), "Manifest 不存在")
        data = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        characters = data.get("characters", {})
        self.assertEqual(len(characters), data["total_characters"])
        self.assertEqual(len(characters), data["verified_count"])

        for asset_id, entry in characters.items():
            relpath = entry["local_relpath"]
            file_path = self.repo_root / relpath
            self.assertTrue(file_path.is_file(), f"文件缺失: {file_path}")
            real_bytes = file_path.read_bytes()
            real_sha = hashlib.sha256(real_bytes).hexdigest()
            self.assertEqual(entry["sha256"], real_sha, f"SHA-256 不匹配: {asset_id}")
            self.assertEqual(entry["file_size"], len(real_bytes))

    def test_valid_png_accepted(self):
        """测试合规预渲染 PNG 完整性核验。"""
        manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        for asset_id in manifest["characters"]:
            p = self.rendered_dir / f"{asset_id}.png"
            ok, msg, info = check_png_integrity(p)
            self.assertTrue(ok, f"PNG 检查未通过: {asset_id} ({msg})")
            self.assertEqual(info["mode"], "RGBA")
            self.assertGreater(info["width"], 0)
            self.assertGreater(info["height"], 0)

    def test_verify_manifest_passes_on_production_assets(self):
        """测试 scripts/rebuild_spine_render_manifest.py 的 --verify 函数成功通过。"""
        ok, errors = verify_manifest(self.manifest_path, self.rendered_dir)
        self.assertTrue(ok, f"生产 Manifest 验证失败: {errors}")
        self.assertEqual(len(errors), 0)

    def test_wrong_hash_rejected_by_asset_manager(self):
        """测试当 Manifest 中 SHA-256 被篡改或与文件不符时，AssetManager fail-closed 拒绝加载并返回 fallback。"""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            test_assets = base / "assets"
            test_rendered = test_assets / "spine-rendered"
            test_rendered.mkdir(parents=True)

            # 拷贝真实 c010.png
            shutil.copy2(self.rendered_dir / "c010.png", test_rendered / "c010.png")

            # 写入错误的 SHA-256
            tampered_manifest = {
                "schema_version": 2,
                "characters": {
                    "c010": {
                        "spine_asset_id": "c010",
                        "character_resource_id": "10",
                        "sha256": "0000000000000000000000000000000000000000000000000000000000000000",
                        "width": 425,
                        "height": 891,
                        "format": "png",
                        "file_size": 313219,
                    }
                },
            }
            (test_assets / "spine_manifest.json").write_text(json.dumps(tampered_manifest), encoding="utf-8")

            manager = AssetManager(base / "cache", test_assets, remote=False)
            try:
                with self.assertLogs("nikke.asset_manager", level="WARNING") as cm:
                    # Rapi (name_code 201001, resource_id 10) -> c010
                    img = manager.get_character_portrait(201001, "10")
                    # 必须降级为 fallback (600, 900)
                    self.assertEqual(img.size, (600, 900))
                    self.assertTrue(any("SPINE_HASH_MISMATCH" in m for m in cm.output))
            finally:
                manager.close()

    def test_missing_hash_rejected_by_asset_manager(self):
        """测试当 Manifest 条目缺少 SHA-256 时，AssetManager 严正拒绝加载。"""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            test_assets = base / "assets"
            test_rendered = test_assets / "spine-rendered"
            test_rendered.mkdir(parents=True)
            shutil.copy2(self.rendered_dir / "c010.png", test_rendered / "c010.png")

            # 缺少 sha256 字段
            no_hash_manifest = {
                "schema_version": 2,
                "characters": {
                    "c010": {
                        "spine_asset_id": "c010",
                        "character_resource_id": "10",
                        "width": 425,
                        "height": 891,
                    }
                },
            }
            (test_assets / "spine_manifest.json").write_text(json.dumps(no_hash_manifest), encoding="utf-8")

            manager = AssetManager(base / "cache", test_assets, remote=False)
            try:
                with self.assertLogs("nikke.asset_manager", level="WARNING") as cm:
                    img = manager.get_character_portrait(201001, "10")
                    self.assertEqual(img.size, (600, 900))
                    self.assertTrue(any("SPINE_MANIFEST_MISSING_HASH" in m for m in cm.output))
            finally:
                manager.close()

    def test_corrupt_file_rejected_by_asset_manager(self):
        """测试损坏的非合法 PNG 文件被识别并拒绝加载。"""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            test_assets = base / "assets"
            test_rendered = test_assets / "spine-rendered"
            test_rendered.mkdir(parents=True)

            corrupt_bytes = b"NOT_A_PNG_FILE_HEADER_CORRUPTED"
            corrupt_sha = hashlib.sha256(corrupt_bytes).hexdigest()
            (test_rendered / "c010.png").write_bytes(corrupt_bytes)

            manifest_data = {
                "schema_version": 2,
                "characters": {
                    "c010": {
                        "spine_asset_id": "c010",
                        "character_resource_id": "10",
                        "sha256": corrupt_sha,
                        "width": 425,
                        "height": 891,
                    }
                },
            }
            (test_assets / "spine_manifest.json").write_text(json.dumps(manifest_data), encoding="utf-8")

            manager = AssetManager(base / "cache", test_assets, remote=False)
            try:
                with self.assertLogs("nikke.asset_manager", level="WARNING") as cm:
                    img = manager.get_character_portrait(201001, "10")
                    self.assertEqual(img.size, (600, 900))
                    self.assertTrue(any("SPINE_ASSET_CORRUPT" in m for m in cm.output))
            finally:
                manager.close()

    def test_missing_file_rejected_by_asset_manager(self):
        """测试 Manifest 声明但物理文件缺失时，返回 fallback。"""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            test_assets = base / "assets"
            test_assets.mkdir(parents=True)

            manifest_data = {
                "schema_version": 2,
                "characters": {
                    "c010": {
                        "spine_asset_id": "c010",
                        "character_resource_id": "10",
                        "sha256": "fb05dccee549af72da59b33d6181d2f47d19302caf98ed364e3d216e2c21a0c3",
                        "width": 425,
                        "height": 891,
                    }
                },
            }
            (test_assets / "spine_manifest.json").write_text(json.dumps(manifest_data), encoding="utf-8")

            manager = AssetManager(base / "cache", test_assets, remote=False)
            try:
                with self.assertLogs("nikke.asset_manager", level="WARNING") as cm:
                    img = manager.get_character_portrait(201001, "10")
                    self.assertEqual(img.size, (600, 900))
                    self.assertTrue(any("SPINE_ASSET_FILE_MISSING" in m for m in cm.output))
            finally:
                manager.close()

    def test_path_traversal_rejected_by_asset_manager(self):
        """测试通过 local_relpath 尝试路径穿越时被拦截。"""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            test_assets = base / "assets"
            test_assets.mkdir(parents=True)

            # 制造越界文件
            evil_file = base / "evil.png"
            Image.new("RGBA", (100, 100), "red").save(evil_file)
            evil_sha = hashlib.sha256(evil_file.read_bytes()).hexdigest()

            manifest_data = {
                "schema_version": 2,
                "characters": {
                    "c010": {
                        "spine_asset_id": "c010",
                        "character_resource_id": "10",
                        "local_relpath": "../../evil.png",
                        "sha256": evil_sha,
                        "width": 100,
                        "height": 100,
                    }
                },
            }
            (test_assets / "spine_manifest.json").write_text(json.dumps(manifest_data), encoding="utf-8")

            manager = AssetManager(base / "cache", test_assets, remote=False)
            try:
                img = manager.get_character_portrait(201001, "10")
                self.assertEqual(img.size, (600, 900))
            finally:
                manager.close()

    def test_identity_conflict_rejected_by_asset_manager(self):
        """测试 Manifest 中存在相同身份冲突时 fail-closed 拒绝。"""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            test_assets = base / "assets"
            test_assets.mkdir(parents=True)

            manifest_data = {
                "schema_version": 2,
                "characters": {
                    "c010": {
                        "spine_asset_id": "c010",
                        "character_resource_id": "10",
                        "costume_id": None,
                        "sha256": "fb05dccee549af72da59b33d6181d2f47d19302caf98ed364e3d216e2c21a0c3",
                    },
                    "c010_alt": {
                        "spine_asset_id": "c010_alt",
                        "character_resource_id": "10",
                        "costume_id": None,
                        "sha256": "fb05dccee549af72da59b33d6181d2f47d19302caf98ed364e3d216e2c21a0c3",
                    },
                },
            }
            (test_assets / "spine_manifest.json").write_text(json.dumps(manifest_data), encoding="utf-8")

            manager = AssetManager(base / "cache", test_assets, remote=False)
            try:
                with self.assertLogs("nikke.asset_manager", level="WARNING") as cm:
                    img = manager.get_character_portrait(201001, "10")
                    self.assertEqual(img.size, (600, 900))
                    self.assertTrue(any("SPINE_ASSET_CONFLICT_REJECTED" in m or "SPINE_IDENTITY_CONFLICT" in m for m in cm.output))
            finally:
                manager.close()

    def test_asset_manager_real_load_known_default_characters(self):
        """测试在真实仓库环境中，AssetManager 能够直接安全加载所有已预渲染的默认角色立绘。"""
        with tempfile.TemporaryDirectory() as td:
            cache = Path(td) / "cache"
            manager = AssetManager(cache, self.assets_dir, remote=False)
            try:
                # 1. Rapi (拉毗): resource_id 10 -> c010 (425x891)
                rapi_img = manager.get_character_portrait(201001, "10")
                self.assertEqual(rapi_img.size, (425, 891))
                self.assertEqual(rapi_img.mode, "RGBA")

                # 2. Crown (皇冠): resource_id 330 -> c330 (794x885)
                crown_img = manager.get_character_portrait(433001, "330")
                self.assertEqual(crown_img.size, (794, 885))

                # 3. Anis: Star (阿尼斯：超级巨星): resource_id 17 -> c017 (348x891)
                anis_img = manager.get_character_portrait(301701, "17")
                self.assertEqual(anis_img.size, (348, 891))

                # 4. Dorothy: Serendipity (桃乐丝：机缘巧遇): resource_id 234 -> c234 (602x891)
                dorothy_img = manager.get_character_portrait(423401, "234")
                self.assertEqual(dorothy_img.size, (602, 891))

                # 5. Helm (海伦): resource_id 352 -> c352 (657x892)
                helm_img = manager.get_character_portrait(235201, "352")
                self.assertEqual(helm_img.size, (657, 892))

                # 白雪公主：重型武装使用离线重渲染的高清资源。
                sw_img = manager.get_character_portrait(447101, "471")
                self.assertEqual(sw_img.size, (2474, 3548))
            finally:
                manager.close()

    def test_asset_manager_real_load_known_costumes(self):
        """测试在真实仓库环境中，AssetManager 能够直接安全加载已核验的服装立绘。"""
        with tempfile.TemporaryDirectory() as td:
            cache = Path(td) / "cache"
            manager = AssetManager(cache, self.assets_dir, remote=False)
            try:
                # 1. Rapi - White Promise (costume_id 20001 -> c010_02, 426x892)
                costume_white_promise = manager.get_character_portrait(201001, "10", costume_id="20001")
                self.assertEqual(costume_white_promise.size, (426, 892))

                # 2. Rapi - Classic Vacation (costume_id 10005 -> c010_03, 467x892)
                costume_vacation = manager.get_character_portrait(201001, "10", costume_id="10005")
                self.assertEqual(costume_vacation.size, (467, 892))
            finally:
                manager.close()

    def test_unknown_character_safe_fallback(self):
        """测试未知角色在未预渲染时安全返回占位图。"""
        with tempfile.TemporaryDirectory() as td:
            cache = Path(td) / "cache"
            manager = AssetManager(cache, self.assets_dir, remote=False)
            try:
                fallback_img = manager.get_character_portrait(999999, "999999")
                self.assertEqual(fallback_img.size, (600, 900))
            finally:
                manager.close()

    def test_zero_network_during_character_load(self):
        """测试加载真实角色与服装素材时绝对零网络请求。"""
        with tempfile.TemporaryDirectory() as td:
            cache = Path(td) / "cache"
            manager = AssetManager(cache, self.assets_dir, remote=True)  # 即便开启 remote=True
            try:
                with patch("astrbot_plugin_nikke.core.asset_manager.httpx.stream") as stream:
                    # 默认立绘
                    img1 = manager.get_character_portrait(201001, "10")
                    self.assertEqual(img1.size, (425, 891))
                    # 服装立绘
                    img2 = manager.get_character_portrait(201001, "10", costume_id="10005")
                    self.assertEqual(img2.size, (467, 892))
                    # 绝对禁止发起网络连接
                    stream.assert_not_called()
            finally:
                manager.close()


if __name__ == "__main__":
    unittest.main()
