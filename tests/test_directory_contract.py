import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from astrbot_plugin_nikke.client import BlaBlaClient, NIKKE_DIRECTORY_EN, NIKKE_DIRECTORY_ZH


class DirectoryContractTests(unittest.TestCase):
    def test_directory_preserves_official_class_and_weapon_type_for_stat_calculation(self):
        zh = [{
            "id": 258101,
            "resource_id": 581,
            "name_code": 5140,
            "name_localkey": {"name": "阿爾卡娜"},
            "element_id": {"element": {"element": "Electronic"}},
            "shot_id": {"element": {"weapon_type": "RL"}},
            "class": "Supporter",
            "corporation": "ELYSION",
            "original_rare": "SSR",
        }]
        en = [{
            "id": 258101,
            "name_localkey": {"name": "Arcana"},
        }]

        class Response:
            def __init__(self, payload):
                self._payload = payload

            def raise_for_status(self):
                return None

            def json(self):
                return self._payload

        class Client:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return None

            async def get(self, url):
                return Response(zh if url == NIKKE_DIRECTORY_ZH else en)

        with patch("astrbot_plugin_nikke.client.httpx.AsyncClient", return_value=Client()):
            directory = asyncio.run(BlaBlaClient().get_directory())

        self.assertEqual(directory[0]["class"], "Supporter")
        self.assertEqual(directory[0]["class_name"], "Supporter")
        self.assertEqual(directory[0]["weapon_type"], "RL")
        self.assertEqual(directory[0]["weapon"], "RL")
