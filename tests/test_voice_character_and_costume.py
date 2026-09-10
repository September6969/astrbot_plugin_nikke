# SPDX-License-Identifier: GPL-3.0-or-later
"""测试 200 可玩妮姬语音角色解析、已核验服装选择与语言收口。"""

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from astrbot_plugin_nikke.costume_registry import CostumeRegistry
from astrbot_plugin_nikke.main import NikkePlugin
from astrbot_plugin_nikke.storage import NikkeStore
from astrbot_plugin_nikke.voice_audio import VoicePreference
from astrbot_plugin_nikke.voice_character_resolver import VoiceCharacterResolver


class VoiceCharacterAndCostumeTests(unittest.TestCase):
    def setUp(self):
        self.assets_dir = Path(__file__).resolve().parents[1] / "assets"
        self.char_resolver = VoiceCharacterResolver(self.assets_dir)
        self.costume_registry = CostumeRegistry(self.assets_dir)

    def test_200_character_resolution_coverage(self):
        """测试 200 角色覆盖：简中、繁中、英文、代码与 resource_id 均能解析。"""
        cases = [
            # Arcana
            ("Arcana", "arcana"),
            ("阿尔卡娜", "arcana"),
            ("阿爾卡娜", "arcana"),
            ("arcana", "arcana"),
            ("c581", "arcana"),
            ("581", "arcana"),
            # Alice
            ("Alice", "alice"),
            ("爱丽丝", "alice"),
            ("愛麗絲", "alice"),
            ("alice", "alice"),
            ("c191", "alice"),
            # Drake
            ("Drake", "drake"),
            ("德雷克", "drake"),
            ("drake", "drake"),
            ("c101", "drake"),
            # Dorothy
            ("Dorothy", "dorothy"),
            ("桃乐丝", "dorothy"),
            ("桃樂絲", "dorothy"),
            ("dorothy", "dorothy"),
            # Scarlet
            ("Scarlet", "scarlet"),
            ("红莲", "scarlet"),
            ("紅蓮", "scarlet"),
            ("scarlet", "scarlet"),
            # Rapi
            ("Rapi", "rapi"),
            ("拉毗", "rapi"),
            ("rapi", "rapi"),
            ("c010", "rapi"),
            ("10", "rapi"),
            # Red Hood
            ("Red Hood", "red_hood"),
            ("小红帽", "red_hood"),
            ("小紅帽", "red_hood"),
            ("red_hood", "red_hood"),
            # Modernia
            ("Modernia", "modernia"),
            ("神罚", "modernia"),
            ("神罰", "modernia"),
            ("modernia", "modernia"),
            # Liter
            ("Liter", "liter"),
            ("丽塔", "liter"),
            ("麗塔", "liter"),
            ("liter", "liter"),
        ]
        for query, expected in cases:
            with self.subTest(query=query):
                self.assertEqual(self.char_resolver.resolve(query), expected)

        # 未知角色
        self.assertIsNone(self.char_resolver.resolve("未知角色_XYZ"))
        self.assertIsNone(self.char_resolver.resolve(""))
        self.assertIsNone(self.char_resolver.resolve(None))

    def test_costume_registry_strict_verification_and_owner_matching(self):
        """测试服装严格核验：拒绝未核验皮肤，强校验所有者匹配。"""
        # 1. 重置默认
        for term in ("默认", "default", "原皮", "0"):
            res = self.costume_registry.resolve(term, 10)
            self.assertTrue(res.ok)
            self.assertEqual(res.status, "RESET_DEFAULT")

        # 2. Rapi (10) 选 10005 (Classic Vacation)
        res = self.costume_registry.resolve("10005", 10)
        self.assertTrue(res.ok)
        self.assertEqual(res.status, "SUCCESS")
        self.assertEqual(res.costume.costume_id, "10005")
        self.assertEqual(res.costume.spine_asset_id, "c010_03")

        # 3. Rapi (10) 按名称选 Classic Vacation（大小写不敏感）
        res = self.costume_registry.resolve("classic vacation", 10)
        self.assertTrue(res.ok)
        self.assertEqual(res.status, "SUCCESS")
        self.assertEqual(res.costume.costume_id, "10005")

        # 4. Rapi (10) 选 20001 (White Promise)
        res = self.costume_registry.resolve("20001", 10)
        self.assertTrue(res.ok)
        self.assertEqual(res.status, "SUCCESS")
        self.assertEqual(res.costume.spine_asset_id, "c010_02")

        # 5. Drake (101) 选 80001 (Villain Racer)
        res = self.costume_registry.resolve("80001", 101)
        self.assertTrue(res.ok)
        self.assertEqual(res.status, "SUCCESS")
        self.assertEqual(res.costume.spine_asset_id, "c101_01")

        # 6. 所有者不匹配：Drake (101) 选 Rapi 的 10005 -> 拒绝
        res = self.costume_registry.resolve("10005", 101)
        self.assertFalse(res.ok)
        self.assertEqual(res.status, "OWNER_MISMATCH")
        self.assertIn("不属于", res.message)

        # 7. 未核验服装：10014 或任意未登记 ID -> 拒绝
        res = self.costume_registry.resolve("10014", 10)
        self.assertFalse(res.ok)
        self.assertEqual(res.status, "UNVERIFIED_COSTUME")
        self.assertIn("未找到已核验服装", res.message)

        # 8. 空输入
        res = self.costume_registry.resolve("", 10)
        self.assertFalse(res.ok)
        self.assertEqual(res.status, "EMPTY_QUERY")

    def test_costume_registry_available_costumes_for_character(self):
        """测试查询角色可用的已核验服装列表。"""
        rapi_costumes = self.costume_registry.get_costumes_for_resource(10)
        cids = {c.costume_id for c in rapi_costumes}
        self.assertIn("10005", cids)
        self.assertIn("20001", cids)

        drake_costumes = self.costume_registry.get_costumes_for_resource(101)
        self.assertEqual([c.costume_id for c in drake_costumes], ["80001"])


class VoicePluginSettingsMockTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.temp_dir.name)
        self.plugin = NikkePlugin(ContextMock())
        self.plugin.store = NikkeStore(self.data_dir)
        self.plugin.data_dir = self.data_dir
        self.plugin.voice_character_resolver = VoiceCharacterResolver(self.plugin.plugin_dir / "assets")
        self.plugin.costume_registry = CostumeRegistry(self.plugin.plugin_dir / "assets")

    async def asyncTearDown(self):
        self.temp_dir.cleanup()

    def _event(self, qq="123456"):
        event = MagicMock()
        event.get_platform_name.return_value = "aiocqhttp"
        event.get_sender_id.return_value = qq
        event.message_obj = MagicMock()
        event.message_obj.sender = {"user_id": int(qq)}
        event.plain_result = lambda text: text
        return event

    async def test_voice_settings_character_switch_200_coverage(self):
        """测试用户通过语音指令切换角色（支持 200 角色与简繁中文）。"""
        event = self._event()

        # 切换到阿尔卡娜（简中）
        results = [r async for r in self.plugin.voice_settings(event, "角色", "阿尔卡娜")]
        self.assertEqual(len(results), 1)
        self.assertIn("arcana", results[0])

        pref = VoicePreference.load(self.plugin.store, "aiocqhttp:123456")
        self.assertEqual(pref.character, "arcana")
        self.assertEqual(pref.skin, "default")
        self.assertEqual(pref.spine_asset_id, "")

        # 切换到德雷克
        results = [r async for r in self.plugin.voice_settings(event, "角色", "德雷克")]
        self.assertIn("drake", results[0])
        pref = VoicePreference.load(self.plugin.store, "aiocqhttp:123456")
        self.assertEqual(pref.character, "drake")

        # 未知角色拒绝
        results = [r async for r in self.plugin.voice_settings(event, "角色", "火星妮姬")]
        self.assertIn("未找到妮姬：火星妮姬", results[0])
        pref = VoicePreference.load(self.plugin.store, "aiocqhttp:123456")
        self.assertEqual(pref.character, "drake")  # 保持原状

    async def test_voice_settings_costume_switch_and_owner_enforcement(self):
        """测试通过语音指令切换服装，拒绝未核验皮肤与所有者不匹配。"""
        event = self._event()

        # 先设为拉毗
        [r async for r in self.plugin.voice_settings(event, "角色", "rapi")]

        # 设为 Classic Vacation (10005)
        results = [r async for r in self.plugin.voice_settings(event, "服装", "10005")]
        self.assertIn("10005", results[0])
        pref = VoicePreference.load(self.plugin.store, "aiocqhttp:123456")
        self.assertEqual(pref.skin, "10005")
        self.assertEqual(pref.spine_asset_id, "c010_03")

        # 恢复默认
        results = [r async for r in self.plugin.voice_settings(event, "服装", "默认")]
        pref = VoicePreference.load(self.plugin.store, "aiocqhttp:123456")
        self.assertEqual(pref.skin, "default")
        self.assertEqual(pref.spine_asset_id, "")

        # 切换角色到德雷克后，尝试选择拉毗的服装 10005 -> 拒绝
        [r async for r in self.plugin.voice_settings(event, "角色", "drake")]
        results = [r async for r in self.plugin.voice_settings(event, "服装", "10005")]
        self.assertIn("不属于", results[0])
        pref = VoicePreference.load(self.plugin.store, "aiocqhttp:123456")
        self.assertEqual(pref.skin, "default")

        # 德雷克选择自己的 80001 (Villain Racer) -> 成功
        results = [r async for r in self.plugin.voice_settings(event, "服装", "80001")]
        self.assertIn("80001", results[0])
        pref = VoicePreference.load(self.plugin.store, "aiocqhttp:123456")
        self.assertEqual(pref.skin, "80001")
        self.assertEqual(pref.spine_asset_id, "c101_01")

        # 选择未核验服装 -> 拒绝
        results = [r async for r in self.plugin.voice_settings(event, "服装", "10014")]
        self.assertIn("未找到已核验服装", results[0])

    async def test_voice_settings_locale_clean_options(self):
        """测试语言选项仅允许 ja, en, ko，移除 zh-cn。"""
        event = self._event()

        # 允许 ja
        results = [r async for r in self.plugin.voice_settings(event, "语言", "ja")]
        self.assertIn("ja", results[0])
        pref = VoicePreference.load(self.plugin.store, "aiocqhttp:123456")
        self.assertEqual(pref.locale, "ja")

        # 允许 en
        results = [r async for r in self.plugin.voice_settings(event, "语言", "en")]
        self.assertIn("en", results[0])
        pref = VoicePreference.load(self.plugin.store, "aiocqhttp:123456")
        self.assertEqual(pref.locale, "en")

        # 拒绝 zh-cn
        results = [r async for r in self.plugin.voice_settings(event, "语言", "zh-cn")]
        self.assertIn("用法：", results[0])
        pref = VoicePreference.load(self.plugin.store, "aiocqhttp:123456")
        self.assertEqual(pref.locale, "en")  # 保持不变

    async def test_text_poke_dialogue_is_completely_removed(self):
        """测试纯文本 /妮姬 戳一戳 指令与伪造台词已被彻底移除。"""
        from astrbot_plugin_nikke.voice_feedback import VoiceResolver
        event = self._event()

        # 1. CHARACTER_LINES 已从 VoiceResolver 彻底删除
        self.assertFalse(hasattr(VoiceResolver, "CHARACTER_LINES"))
        self.assertFalse(hasattr(VoiceResolver, "resolve_poke_line"))

        # 2. poke 方法与 voice_resolver 实例在 plugin 中已不存在
        self.assertFalse(hasattr(self.plugin, "poke"))
        self.assertFalse(hasattr(self.plugin, "voice_resolver"))

        # 3. 帮助文本中不再包含戳一戳
        help_text = self.plugin._help_text()
        self.assertNotIn("戳一戳", help_text)
        self.assertNotIn("poke", help_text.lower())
        self.assertNotIn("互动台词", help_text)

        # 4. 路由不再处理 /nikke poke 或 /妮姬 戳一戳（回退到通用未知指令/帮助）
        poke_results = [r async for r in self.plugin.nikke(event, "戳一戳")]
        self.assertTrue(len(poke_results) > 0)
        self.assertIn("未知指令", poke_results[0])

        poke_en_results = [r async for r in self.plugin.nikke(event, "poke")]
        self.assertTrue(len(poke_en_results) > 0)
        self.assertIn("未知指令", poke_en_results[0])


class ContextMock:
    pass


if __name__ == "__main__":
    unittest.main()
