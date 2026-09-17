from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

from astrbot_plugin_nikke.features.tarot.models import DrawnTarotCard
from astrbot_plugin_nikke.features.tarot.service import TarotDeckRepository, TarotService


SOURCE_DATA = Path(__file__).resolve().parents[1] / "assets" / "tarot" / "tarot_cards.json"


class TarotBackendTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        target = self.root / "assets" / "tarot"
        target.mkdir(parents=True)
        shutil.copy2(SOURCE_DATA, target / "tarot_cards.json")
        self.runtime = self.root / "runtime"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_data_contains_full_78_but_auto_starts_major_only(self) -> None:
        deck = TarotDeckRepository(self.root)
        self.assertEqual(len(deck.cards), 78)
        self.assertEqual(len(deck.active_cards()), 22)
        status = deck.status()
        self.assertEqual(status.major_data_cards, 22)
        self.assertEqual(status.minor_data_cards, 56)
        self.assertFalse(status.minor_enabled)

    def test_three_card_draw_has_unique_cards_and_positions(self) -> None:
        service = TarotService(self.root, self.runtime)
        reading = service.draw_three()
        self.assertEqual(len(reading.cards), 3)
        self.assertEqual(len({item.card.key for item in reading.cards}), 3)
        self.assertEqual(
            [item.position for item in reading.cards],
            ["situation", "obstacle", "advice"],
        )
        self.assertTrue(all(item.orientation in {"upright", "reversed"} for item in reading.cards))

    def test_daily_draw_is_stable_and_persisted(self) -> None:
        when = datetime(2026, 9, 14, 3, 0, tzinfo=timezone.utc)
        service1 = TarotService(self.root, self.runtime)
        one = service1.draw_daily("aiocqhttp:123456", now=when)
        service2 = TarotService(self.root, self.runtime)
        two = service2.draw_daily("aiocqhttp:123456", now=when)
        self.assertEqual(one.cards[0].card.key, two.cards[0].card.key)
        self.assertEqual(one.cards[0].orientation, two.cards[0].orientation)

    def test_minor_arcana_activates_only_when_all_56_images_exist(self) -> None:
        payload = json.loads(SOURCE_DATA.read_text(encoding="utf-8"))
        minor = [item for item in payload["cards"] if item["arcana"] == "minor"]
        self.assertEqual(len(minor), 56)
        # 55/56 must remain Major-only.
        for item in minor[:-1]:
            path = self.root / item["image"]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()
        deck = TarotDeckRepository(self.root)
        self.assertEqual(len(deck.active_cards()), 22)
        # 56/56 atomically enables the full deck.
        final_path = self.root / minor[-1]["image"]
        final_path.parent.mkdir(parents=True, exist_ok=True)
        final_path.touch()
        self.assertEqual(len(deck.active_cards()), 78)
        self.assertTrue(deck.status().minor_enabled)

    def test_reversed_image_is_physically_rotated(self) -> None:
        data = json.loads((self.root / "assets" / "tarot" / "tarot_cards.json").read_text(encoding="utf-8"))
        major = next(item for item in data["cards"] if item["arcana"] == "major")
        source = self.root / major["image"]
        source.parent.mkdir(parents=True, exist_ok=True)
        image = Image.new("RGB", (2, 2), "black")
        image.putpixel((0, 0), (255, 0, 0))
        image.putpixel((1, 1), (0, 0, 255))
        image.save(source)

        service = TarotService(self.root, self.runtime)
        card = service.deck.card_by_key(major["key"])
        assert card is not None
        reversed_path = service.images.image_for(DrawnTarotCard(card, "reversed"))
        self.assertIsNotNone(reversed_path)
        with Image.open(reversed_path) as rotated:
            self.assertEqual(rotated.convert("RGB").getpixel((1, 1)), (255, 0, 0))
            self.assertEqual(rotated.convert("RGB").getpixel((0, 0)), (0, 0, 255))


class DummyTarotEvent:
    def __init__(self, sender_id: str = "123456", platform: str = "aiocqhttp"):
        self.sender_id = sender_id
        self.platform = platform

    def plain_result(self, text: str):
        return ("plain", text)

    def image_result(self, path: str):
        return ("image", path)

    def get_platform_name(self) -> str:
        return self.platform

    def get_sender_id(self) -> str:
        return self.sender_id

    def is_admin(self) -> bool:
        return False


class TestTarotCommandIntegration(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        target = self.root / "assets" / "tarot"
        target.mkdir(parents=True)
        shutil.copy2(SOURCE_DATA, target / "tarot_cards.json")
        self.runtime = self.root / "runtime"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    async def test_tarot_command_help_and_status(self) -> None:
        from astrbot_plugin_nikke.main import NikkePlugin

        plugin = NikkePlugin.__new__(NikkePlugin)
        plugin.plugin_dir = self.root
        plugin.data_dir = self.runtime
        plugin.tarot = TarotService(self.root, self.runtime)

        # Help
        results = [r async for r in plugin.tarot_command(DummyTarotEvent(), "帮助")]
        self.assertEqual(len(results), 1)
        self.assertIn("【NIKKE 塔罗】", results[0][1])
        self.assertIn("单抽", results[0][1])

        # Status
        results = [r async for r in plugin.tarot_command(DummyTarotEvent(), "状态")]
        self.assertEqual(len(results), 1)
        self.assertIn("【塔罗牌库状态】", results[0][1])
        self.assertIn("大阿尔卡那", results[0][1])

    async def test_tarot_command_draw_single(self) -> None:
        from astrbot_plugin_nikke.main import NikkePlugin

        plugin = NikkePlugin.__new__(NikkePlugin)
        plugin.plugin_dir = self.root
        plugin.data_dir = self.runtime
        plugin.tarot = TarotService(self.root, self.runtime)

        results = [r async for r in plugin.tarot_command(DummyTarotEvent(), "单抽")]
        # May have 0 or 1 image depending on whether asset exists on disk in temp dir,
        # but the last result must be plain text reading.
        self.assertTrue(len(results) >= 1)
        text_result = results[-1]
        self.assertEqual(text_result[0], "plain")
        self.assertIn("【塔罗单抽】", text_result[1])

    async def test_tarot_command_draw_three(self) -> None:
        from astrbot_plugin_nikke.main import NikkePlugin

        plugin = NikkePlugin.__new__(NikkePlugin)
        plugin.plugin_dir = self.root
        plugin.data_dir = self.runtime
        plugin.tarot = TarotService(self.root, self.runtime)

        results = [r async for r in plugin.tarot_command(DummyTarotEvent(), "三张")]
        self.assertTrue(len(results) >= 1)
        text_result = results[-1]
        self.assertEqual(text_result[0], "plain")
        self.assertIn("【三张牌阵｜现状 · 阻碍 · 建议】", text_result[1])
        self.assertIn("现状", text_result[1])
        self.assertIn("阻碍", text_result[1])
        self.assertIn("建议", text_result[1])

    async def test_tarot_command_draw_daily(self) -> None:
        from astrbot_plugin_nikke.main import NikkePlugin

        plugin = NikkePlugin.__new__(NikkePlugin)
        plugin.plugin_dir = self.root
        plugin.data_dir = self.runtime
        plugin.tarot = TarotService(self.root, self.runtime)

        event = DummyTarotEvent("999888")
        results1 = [r async for r in plugin.tarot_command(event, "今日")]
        results2 = [r async for r in plugin.tarot_command(event, "今日")]
        self.assertEqual(results1[-1][1], results2[-1][1])
        self.assertIn("【今日塔罗】", results1[-1][1])

    async def test_tarot_command_unknown_action(self) -> None:
        from astrbot_plugin_nikke.main import NikkePlugin

        plugin = NikkePlugin.__new__(NikkePlugin)
        plugin.plugin_dir = self.root
        plugin.data_dir = self.runtime
        plugin.tarot = TarotService(self.root, self.runtime)

        results = [r async for r in plugin.tarot_command(DummyTarotEvent(), "未知动作")]
        self.assertEqual(len(results), 1)
        self.assertIn("用法：/妮姬 塔罗", results[0][1])

    async def test_nikke_command_dispatches_tarot(self) -> None:
        from astrbot_plugin_nikke.main import NikkePlugin

        plugin = NikkePlugin.__new__(NikkePlugin)
        plugin.plugin_dir = self.root
        plugin.data_dir = self.runtime
        plugin.tarot = TarotService(self.root, self.runtime)

        # Dispatch via nikke(event, "塔罗", "单抽")
        results = [r async for r in plugin.nikke(DummyTarotEvent(), "塔罗", "单抽")]
        self.assertTrue(len(results) >= 1)
        self.assertIn("【塔罗单抽】", results[-1][1])

        # Dispatch via nikke(event, "tarot", "status")
        results = [r async for r in plugin.nikke(DummyTarotEvent(), "tarot", "status")]
        self.assertEqual(len(results), 1)
        self.assertIn("【塔罗牌库状态】", results[0][1])


if __name__ == "__main__":
    unittest.main()

