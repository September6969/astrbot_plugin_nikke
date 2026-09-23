import unittest
from importlib.metadata import PackageNotFoundError
from unittest.mock import patch

from astrbot.api.star import Star

from astrbot_plugin_nikke.adapters.astrbot.compatibility import (
    AstrBotCompatibilityError,
    require_supported_astrbot_version,
)
from astrbot_plugin_nikke.main import NikkePlugin


class AstrBotCompatibilityTests(unittest.TestCase):
    def test_accepts_supported_astrbot_release_range(self):
        for supported in ("4.24.0", "4.28.0", "4.99.0"):
            with self.subTest(version=supported):
                with patch(
                    "astrbot_plugin_nikke.adapters.astrbot.compatibility.version",
                    return_value=supported,
                ):
                    self.assertEqual(require_supported_astrbot_version(), supported)

    def test_rejects_astrbot_outside_declared_release_range(self):
        for unsupported in ("4.23.9", "5.0.0"):
            with self.subTest(version=unsupported):
                with patch(
                    "astrbot_plugin_nikke.adapters.astrbot.compatibility.version",
                    return_value=unsupported,
                ):
                    with self.assertRaisesRegex(
                        AstrBotCompatibilityError, r">=4\.24,<5"
                    ):
                        require_supported_astrbot_version()

    def test_reports_unknown_astrbot_installation(self):
        with patch(
            "astrbot_plugin_nikke.adapters.astrbot.compatibility.version",
            side_effect=PackageNotFoundError("AstrBot"),
        ):
            with self.assertRaisesRegex(AstrBotCompatibilityError, "无法确定 AstrBot 版本"):
                require_supported_astrbot_version()

    def test_reports_malformed_astrbot_version(self):
        with patch(
            "astrbot_plugin_nikke.adapters.astrbot.compatibility.version",
            return_value="not-a-version",
        ):
            with self.assertRaisesRegex(AstrBotCompatibilityError, "无法解析 AstrBot 版本"):
                require_supported_astrbot_version()

    def test_plugin_rejects_unsupported_astrbot_before_host_initialization(self):
        with patch(
            "astrbot_plugin_nikke.main.require_supported_astrbot_version",
            side_effect=AstrBotCompatibilityError("AstrBot 4.23.9 is unsupported"),
        ):
            with patch.object(Star, "__init__") as host_init:
                with self.assertRaises(AstrBotCompatibilityError):
                    NikkePlugin(object())
                host_init.assert_not_called()


if __name__ == "__main__":
    unittest.main()
