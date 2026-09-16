# SPDX-License-Identifier: GPL-3.0-or-later
"""Unit tests for BlaBla static asset mirror pipeline and utilities.

Ensures 100% offline, deterministic behavior without remote network dependencies.
"""

import asyncio
from pathlib import Path
import tempfile
import unittest
from PIL import Image

from astrbot_plugin_nikke.scripts.mirror_blablalink_assets import (
    filter_items,
    get_local_dest_path,
    verify_local_file,
)


class AssetMirrorPipelineTests(unittest.TestCase):
    def setUp(self):
        self.mock_inventory = {
            "categories": {
                "portraits_si_default": {
                    "items": [
                        {"resource_id": 10, "relative_path": "/character/si/si_c010_00_s.webp", "est_bytes": 6000},
                        {"resource_id": 82, "relative_path": "/character/si/si_c082_00_s.webp", "est_bytes": 6500},
                    ]
                },
                "portraits_si_costumes": {
                    "items": [
                        {"resource_id": 82, "costume_index": 1, "relative_path": "/character/si/si_c082_01_s.webp", "est_bytes": 6200},
                    ]
                },
                "common_icons": {
                    "items": [
                        {"name": "elem_fire", "relative_path": "icon/element/icon-code-fire.png", "est_bytes": 3500},
                    ]
                },
            }
        }

    def test_filter_items_by_category(self):
        # 筛选 portrait_si 别名（应囊括 default + costumes）
        items = filter_items(self.mock_inventory, ["portrait_si"])
        self.assertEqual(len(items), 3)

        # 筛选仅 common_icons
        icons = filter_items(self.mock_inventory, ["icons"])
        self.assertEqual(len(icons), 1)
        self.assertEqual(icons[0]["name"], "elem_fire")

    def test_get_local_dest_path(self):
        target = Path("/tmp/blabla")
        item = {"relative_path": "/character/si/si_c010_00_s.webp"}
        p = get_local_dest_path(target, item)
        self.assertEqual(p, target / "character" / "si" / "si_c010_00_s.webp")

    def test_verify_local_file(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "test.png"
            
            # 1. 不存在的文件
            valid, sha, sz = asyncio.run(verify_local_file(p))
            self.assertFalse(valid)
            self.assertEqual(sz, 0)

            # 2. 合法图片
            img = Image.new("RGBA", (32, 32), (255, 0, 0, 255))
            img.save(p, "PNG")
            valid, sha, sz = asyncio.run(verify_local_file(p))
            self.assertTrue(valid)
            self.assertGreater(sz, 0)
            self.assertEqual(len(sha), 64)

            # 3. 损坏/空文件
            corrupt = Path(td) / "corrupt.png"
            corrupt.write_bytes(b"not an image")
            valid_c, _, _ = asyncio.run(verify_local_file(corrupt))
            self.assertFalse(valid_c)


if __name__ == "__main__":
    unittest.main()
