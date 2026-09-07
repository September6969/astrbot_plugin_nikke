import unittest
from pathlib import Path
from unittest.mock import patch, sentinel

from astrbot_plugin_nikke.main import NikkePlugin


class CampaignResourceWiringTests(unittest.TestCase):
    def test_campaign_renderer_reuses_plugin_asset_manager(self):
        plugin = NikkePlugin.__new__(NikkePlugin)
        plugin.data_dir = Path("data/nikke")
        plugin.plugin_dir = Path("plugin")
        plugin.asset_manager = sentinel.shared_assets

        with patch("astrbot_plugin_nikke.main.CampaignHistoryRenderer") as renderer:
            plugin._build_campaign_renderer()

        renderer.assert_called_once_with(
            Path("data/nikke/cards"),
            Path("plugin/fonts"),
            sentinel.shared_assets,
        )
