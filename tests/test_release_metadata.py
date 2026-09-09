# SPDX-License-Identifier: GPL-3.0-or-later

import json
import re
import unittest
from pathlib import Path

from astrbot_plugin_nikke._version import PLUGIN_VERSION


ROOT = Path(__file__).resolve().parents[1]


class ReleaseMetadataTests(unittest.TestCase):
    def test_runtime_and_manifest_versions_match(self):
        metadata = (ROOT / "metadata.yaml").read_text(encoding="utf-8")
        match = re.search(r"^version:\s*([^\s#]+)\s*$", metadata, re.MULTILINE)

        self.assertIsNotNone(match)
        self.assertEqual(match.group(1), PLUGIN_VERSION)

    def test_schema_defaults_and_configuration_document_are_complete(self):
        schema = json.loads((ROOT / "_conf_schema.json").read_text(encoding="utf-8"))
        expected = {
            "public_base_url": ("string", "https://nikke.irises777.xyz"),
            "web_host": ("string", "0.0.0.0"),
            "web_port": ("int", 6210),
            "binding_api_key": ("string", ""),
            "allow_group_bind": ("bool", False),
            "daily_hour": ("int", 8),
            "daily_minute": ("int", 10),
            "summary_hour": ("int", 8),
            "summary_minute": ("int", 30),
            "request_timeout": ("int", 20),
            "max_concurrency": ("int", 2),
            "spine_worker_path": ("string", ""),
            "spine_runtime_version": ("string", "4.0"),
            "spine_worker_timeout": ("int", 4),
            "voice_dynamic_enabled": ("bool", True),
            "enable_daily_actions": ("bool", False),
            "enable_announcement_push": ("bool", False),
            "enable_cdk_redemption": ("bool", False),
        }

        self.assertEqual(set(schema), set(expected))
        self.assertEqual(
            {
                key: (value["type"], value["default"])
                for key, value in schema.items()
            },
            expected,
        )
        config_doc = (ROOT / "docs" / "CONFIGURATION_ACCEPTANCE.md").read_text(encoding="utf-8")
        for key, (_, default) in expected.items():
            with self.subTest(key=key):
                self.assertIn(f"`{key}`", config_doc)
                self.assertIn(str(default).lower() if isinstance(default, bool) else str(default), config_doc)

    def test_changelog_is_scoped_to_current_baseline(self):
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

        self.assertIn(f"## {PLUGIN_VERSION}（当前 main 基线）", changelog)
        self.assertIn("未合并的 Draft PR 不计入当前版本", changelog)


if __name__ == "__main__":
    unittest.main()
