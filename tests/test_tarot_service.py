from __future__ import annotations
from plugin_fixtures import inject_tarot_handler, make_plugin_shell

import json
import random
import shutil
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

from astrbot_plugin_nikke.features.tarot.models import DrawnTarotCard
from astrbot_plugin_nikke.features.tarot.service import TarotDeckRepository, TarotService
from astrbot_plugin_nikke.integrations.tarot.images import TarotImageProvider


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

    def test_injected_random_source_makes_draws_reproducible(self) -> None:
        first = TarotService(
            self.root,
            self.runtime / "first",
            random_source=random.Random(2026),
        ).draw_three()
        second = TarotService(
            self.root,
            self.runtime / "second",
            random_source=random.Random(2026),
        ).draw_three()

        self.assertEqual(
            [(item.card.key, item.orientation) for item in first.cards],
            [(item.card.key, item.orientation) for item in second.cards],
        )

    def test_daily_draw_is_stable_and_persisted(self) -> None:
        when = datetime(2026, 9, 14, 3, 0, tzinfo=timezone.utc)
        service1 = TarotService(self.root, self.runtime)
        one = service1.draw_daily("aiocqhttp:123456", now=when)
        service2 = TarotService(self.root, self.runtime)
        two = service2.draw_daily("aiocqhttp:123456", now=when)
        self.assertEqual(one.cards[0].card.key, two.cards[0].card.key)
        self.assertEqual(one.cards[0].orientation, two.cards[0].orientation)

    def test_daily_draw_uses_injected_clock_in_china_timezone(self) -> None:
        fixed_now = datetime(2026, 9, 14, 16, 0, tzinfo=timezone.utc)
        service = TarotService(
            self.root,
            self.runtime,
            clock=lambda: fixed_now,
        )

        reading = service.draw_daily("aiocqhttp:clock")

        self.assertEqual(reading.date_key, "2026-09-15")

    def test_daily_draw_uses_utc8_date_boundary(self) -> None:
        service = TarotService(self.root, self.runtime)
        before_midnight = datetime(2026, 9, 14, 15, 59, tzinfo=timezone.utc)
        after_midnight = datetime(2026, 9, 14, 16, 0, tzinfo=timezone.utc)

        first = service.draw_daily("aiocqhttp:date-boundary", now=before_midnight)
        second = service.draw_daily("aiocqhttp:date-boundary", now=after_midnight)

        self.assertEqual(first.date_key, "2026-09-14")
        self.assertEqual(second.date_key, "2026-09-15")
        saved = json.loads((self.runtime / "daily_draws.json").read_text(encoding="utf-8"))
        self.assertEqual(set(saved), {"2026-09-14", "2026-09-15"})

    def test_daily_draw_concurrent_calls_keep_one_subject_record(self) -> None:
        service = TarotService(self.root, self.runtime)
        when = datetime(2026, 9, 14, 3, 0, tzinfo=timezone.utc)

        def draw_once(_: int):
            return service.draw_daily("aiocqhttp:concurrent", now=when)

        with ThreadPoolExecutor(max_workers=8) as pool:
            readings = list(pool.map(draw_once, range(16)))

        results = {
            (reading.date_key, reading.cards[0].card.key, reading.cards[0].orientation)
            for reading in readings
        }
        self.assertEqual(results, {("2026-09-14", readings[0].cards[0].card.key, readings[0].cards[0].orientation)})
        saved = json.loads((self.runtime / "daily_draws.json").read_text(encoding="utf-8"))
        self.assertEqual(set(saved), {"2026-09-14"})
        self.assertEqual(len(saved["2026-09-14"]), 1)

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
        # PR-6A G3-media-a：牌面路径改为 .jpg；此处显式写无损 PNG 内容，
        # 以便逐像素断言旋转结果（PIL 按内容而非扩展名解码）。
        image.save(source, format="PNG")

        service = TarotService(self.root, self.runtime)
        card = service.deck.card_by_key(major["key"])
        assert card is not None
        reversed_path = TarotImageProvider(
            service.deck, self.runtime / "reversed_cache"
        ).image_for(DrawnTarotCard(card, "reversed"))
        self.assertIsNotNone(reversed_path)
        with Image.open(reversed_path) as rotated:
            self.assertEqual(rotated.convert("RGB").getpixel((1, 1)), (255, 0, 0))
            self.assertEqual(rotated.convert("RGB").getpixel((0, 0)), (0, 0, 255))


    def test_reversed_cache_keeps_source_mode_and_prunes_stale_fingerprints(self) -> None:
        """PR-6A G3-media-a-cache：RGB 源不升为 RGBA；缓存为无损 PNG；旧指纹被清理。"""
        import os

        data = json.loads((self.root / "assets" / "tarot" / "tarot_cards.json").read_text(encoding="utf-8"))
        major = next(item for item in data["cards"] if item["arcana"] == "major")
        source = self.root / major["image"]
        source.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (16, 24), (10, 200, 30)).save(source, format="JPEG", quality=95, subsampling=0)

        deck = TarotDeckRepository(self.root)
        card = deck.card_by_key(major["key"])
        assert card is not None
        cache = self.runtime / "reversed_cache"
        provider = TarotImageProvider(deck, cache)
        unrelated = cache / "major_99_reversed_0123456789ab.png"
        unrelated.write_bytes(b"other card")
        first = provider.image_for(DrawnTarotCard(card, "reversed"))
        assert first is not None
        self.assertEqual(first.suffix, ".png")
        with Image.open(first) as rotated, Image.open(source) as upright:
            self.assertEqual(rotated.format, "PNG")
            self.assertEqual(rotated.mode, "RGB")
            expected = upright.convert("RGB").transpose(Image.Transpose.ROTATE_180)
            self.assertEqual(rotated.tobytes(), expected.tobytes())

        # 牌面被替换（mtime/size 变化）后生成新指纹，旧缓存被删除，其他牌不受影响。
        Image.new("RGB", (16, 24), (200, 10, 30)).save(source, format="PNG")
        os.utime(source, ns=(1, 1))
        second = provider.image_for(DrawnTarotCard(card, "reversed"))
        assert second is not None
        self.assertNotEqual(first, second)
        self.assertFalse(first.exists())
        self.assertTrue(second.is_file())
        self.assertTrue(unrelated.is_file())

    def test_reversed_cache_preserves_alpha_sources(self) -> None:
        data = json.loads((self.root / "assets" / "tarot" / "tarot_cards.json").read_text(encoding="utf-8"))
        major = next(item for item in data["cards"] if item["arcana"] == "major")
        source = self.root / major["image"]
        source.parent.mkdir(parents=True, exist_ok=True)
        image = Image.new("RGBA", (2, 2), (0, 0, 0, 0))
        image.putpixel((0, 0), (255, 0, 0, 128))
        image.save(source, format="PNG")
        deck = TarotDeckRepository(self.root)
        card = deck.card_by_key(major["key"])
        assert card is not None
        path = TarotImageProvider(deck, self.runtime / "cache").image_for(DrawnTarotCard(card, "reversed"))
        assert path is not None
        with Image.open(path) as rotated:
            self.assertEqual(rotated.mode, "RGBA")
            self.assertEqual(rotated.getpixel((1, 1)), (255, 0, 0, 128))


class BundledTarotAssetTests(unittest.TestCase):
    """PR-6A G3-media-a：直接检查仓库内置牌面（其他测试只复制 JSON）。"""

    def test_bundled_deck_is_complete_jpeg_at_original_dimensions(self) -> None:
        root = SOURCE_DATA.parents[2]
        deck = TarotDeckRepository(root)
        status = deck.status()
        self.assertEqual(status.major_images_ready, 22)
        self.assertEqual(status.minor_images_ready, 56)
        self.assertTrue(status.minor_enabled)
        self.assertEqual(len(deck.active_cards()), 78)
        tarot_dir = root / "assets" / "tarot"
        self.assertEqual(list(tarot_dir.rglob("*.png")), [], "旧 PNG 牌面不应与 JPEG 并存")
        for card in deck.cards:
            path = deck.resolve_image(card)
            assert path is not None, card.key
            self.assertEqual(path.suffix, ".jpg")
            with Image.open(path) as image:
                self.assertEqual(image.format, "JPEG")
                self.assertEqual(image.size, (1000, 1500))
                self.assertEqual(image.mode, "RGB")
                # 基线（非渐进）JPEG，兼容 QQ/NapCat。
                self.assertFalse(image.info.get("progressive") or image.info.get("progression"))
                # 4:4:4 色度不降采样。
                self.assertEqual(image.layer[0][1:3], (1, 1))


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

        plugin = make_plugin_shell()
        plugin.plugin_dir = self.root
        plugin.data_dir = self.runtime
        plugin.services.tarot = TarotService(self.root, self.runtime)
        inject_tarot_handler(plugin)

        # Help
        # G8-main-legacy-f（PR-6C）：遗留未注册平铺方法已删除，改经 /妮姬 统一路由。
        results = [r async for r in plugin.nikke(DummyTarotEvent(), "塔罗", "帮助")]
        self.assertEqual(len(results), 1)
        self.assertIn("【NIKKE 塔罗】", results[0][1])
        self.assertIn("单抽", results[0][1])

        # Status
        results = [r async for r in plugin.nikke(DummyTarotEvent(), "塔罗", "状态")]
        self.assertEqual(len(results), 1)
        self.assertIn("【塔罗牌库状态】", results[0][1])
        self.assertIn("大阿尔卡那", results[0][1])

    async def test_tarot_command_draw_single(self) -> None:
        from astrbot_plugin_nikke.main import NikkePlugin

        plugin = make_plugin_shell()
        plugin.plugin_dir = self.root
        plugin.data_dir = self.runtime
        plugin.services.tarot = TarotService(self.root, self.runtime)
        inject_tarot_handler(plugin)

        # G8-main-legacy-f（PR-6C）：遗留未注册平铺方法已删除，改经 /妮姬 统一路由。
        results = [r async for r in plugin.nikke(DummyTarotEvent(), "塔罗", "单抽")]
        # May have 0 or 1 image depending on whether asset exists on disk in temp dir,
        # but the last result must be plain text reading.
        self.assertTrue(len(results) >= 1)
        text_result = results[-1]
        self.assertEqual(text_result[0], "plain")
        self.assertIn("【塔罗单抽】", text_result[1])

    async def test_tarot_command_draw_three(self) -> None:
        from astrbot_plugin_nikke.main import NikkePlugin

        plugin = make_plugin_shell()
        plugin.plugin_dir = self.root
        plugin.data_dir = self.runtime
        plugin.services.tarot = TarotService(self.root, self.runtime)
        inject_tarot_handler(plugin)

        # G8-main-legacy-f（PR-6C）：遗留未注册平铺方法已删除，改经 /妮姬 统一路由。
        results = [r async for r in plugin.nikke(DummyTarotEvent(), "塔罗", "三张")]
        self.assertTrue(len(results) >= 1)
        text_result = results[-1]
        self.assertEqual(text_result[0], "plain")
        self.assertIn("【三张牌阵｜现状 · 阻碍 · 建议】", text_result[1])
        self.assertIn("现状", text_result[1])
        self.assertIn("阻碍", text_result[1])
        self.assertIn("建议", text_result[1])

    async def test_tarot_command_draw_daily(self) -> None:
        from astrbot_plugin_nikke.main import NikkePlugin

        plugin = make_plugin_shell()
        plugin.plugin_dir = self.root
        plugin.data_dir = self.runtime
        plugin.services.tarot = TarotService(self.root, self.runtime)
        inject_tarot_handler(plugin)

        event = DummyTarotEvent("999888")
        # G8-main-legacy-f（PR-6C）：遗留未注册平铺方法已删除，改经 /妮姬 统一路由。
        results1 = [r async for r in plugin.nikke(event, "塔罗", "今日")]
        results2 = [r async for r in plugin.nikke(event, "塔罗", "今日")]
        self.assertEqual(results1[-1][1], results2[-1][1])
        self.assertIn("【今日塔罗】", results1[-1][1])

    async def test_tarot_command_daily_emits_one_text_result(self) -> None:
        from astrbot_plugin_nikke.main import NikkePlugin

        plugin = make_plugin_shell()
        plugin.plugin_dir = self.root
        plugin.data_dir = self.runtime
        plugin.services.tarot = TarotService(self.root, self.runtime)
        inject_tarot_handler(plugin)

        # G8-main-legacy-f（PR-6C）：遗留未注册平铺方法已删除，改经 /妮姬 统一路由。
        results = [r async for r in plugin.nikke(DummyTarotEvent("single-message"), "塔罗", "今日")]
        self.assertEqual(sum(result[0] == "plain" for result in results), 1)
        self.assertEqual(results[-1][0], "plain")

    async def test_tarot_command_unknown_action(self) -> None:
        from astrbot_plugin_nikke.main import NikkePlugin

        plugin = make_plugin_shell()
        plugin.plugin_dir = self.root
        plugin.data_dir = self.runtime
        plugin.services.tarot = TarotService(self.root, self.runtime)
        inject_tarot_handler(plugin)

        # G8-main-legacy-f（PR-6C）：遗留未注册平铺方法已删除，改经 /妮姬 统一路由。
        results = [r async for r in plugin.nikke(DummyTarotEvent(), "塔罗", "未知动作")]
        self.assertEqual(len(results), 1)
        self.assertIn("用法：/妮姬 塔罗", results[0][1])

    async def test_nikke_command_dispatches_tarot(self) -> None:
        from astrbot_plugin_nikke.main import NikkePlugin

        plugin = make_plugin_shell()
        plugin.plugin_dir = self.root
        plugin.data_dir = self.runtime
        plugin.services.tarot = TarotService(self.root, self.runtime)
        inject_tarot_handler(plugin)

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
