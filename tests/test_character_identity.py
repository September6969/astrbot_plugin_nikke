import json
import tempfile
import unittest
from pathlib import Path

from astrbot_plugin_nikke.character_identity import CharacterDirectoryResolver


class CharacterDirectoryResolverTests(unittest.TestCase):
    def setUp(self):
        self.resolver = CharacterDirectoryResolver(
            Path(__file__).resolve().parents[1] / "assets" / "character_aliases.json"
        )
        self.directory = [
            {
                "name_code": "arcana",
                "name_zh_tw": "阿爾卡娜",
                "name_cn": "阿爾卡娜",
                "name_en": "ARCANA",
            },
            {
                "name_code": "alice",
                "name_zh_tw": "爱丽丝",
                "name_en": "Alice",
            },
        ]

    def test_traditional_simplified_alias_and_english_share_identity(self):
        matches = [self.resolver.find(self.directory, query) for query in ("阿爾卡娜", "阿尔卡娜", "ARCANA")]
        self.assertEqual([len(items) for items in matches], [1, 1, 1])
        self.assertEqual({items[0]["name_code"] for items in matches}, {"arcana"})
        self.assertEqual(matches[1][0]["name_zh_tw"], "阿爾卡娜")
        self.assertEqual(matches[1][0]["name_zh_cn"], "")
        self.assertEqual(matches[1][0]["name_zh_cn_alias"], "阿尔卡娜")

    def test_exact_match_wins_over_bounded_substring(self):
        result = self.resolver.find(
            self.directory + [{"name_code": "arcana-alt", "name_zh_tw": "阿爾卡娜：限定"}],
            "阿爾卡娜",
        )
        self.assertEqual([item["name_code"] for item in result], ["arcana"])

    def test_alias_registry_is_tolerant_of_missing_or_malformed_files(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "aliases.json"
            path.write_text("[]", encoding="utf-8")
            resolver = CharacterDirectoryResolver(path)
            self.assertEqual(resolver.find(self.directory, "阿尔卡娜"), [])

    def test_alias_collision_detection_raises_value_error(self):
        """测试别名冲突检测：不同角色若共享相同别名，加载时必须明确抛出 ValueError。"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "colliding_aliases.json"
            colliding_payload = {
                "schema_version": 1,
                "entries": [
                    {"name_zh_tw": "角色甲", "name_code": "char_a", "aliases": ["同名别称"]},
                    {"name_zh_tw": "角色乙", "name_code": "char_b", "aliases": ["同名别称"]},
                ]
            }
            path.write_text(json.dumps(colliding_payload, ensure_ascii=False), encoding="utf-8")
            with self.assertRaises(ValueError) as ctx:
                CharacterDirectoryResolver(path)
            self.assertIn("别名冲突", str(ctx.exception))
            self.assertIn("同名别称", str(ctx.exception))

    def test_full_200_catalog_data_driven_audit(self):
        """全量 200 角色数据驱动核验：TC、SC别名、EN、name_code 统一解析且 SC 无繁体残留。"""
        from astrbot_plugin_nikke.voice_character_resolver import VoiceCharacterResolver

        assets_dir = Path(__file__).resolve().parents[1] / "assets"
        catalog_path = assets_dir / "character_catalog.json"
        alias_path = assets_dir / "character_aliases.json"

        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        characters = catalog.get("characters", [])
        self.assertEqual(len(characters), 200, "必须覆盖全部 200 名可玩妮姬")

        alias_payload = json.loads(alias_path.read_text(encoding="utf-8"))
        self.assertIn("仅用于查询", alias_payload.get("description", ""))
        self.assertIn("非官方 zh-CN", alias_payload.get("description", ""))

        t2s_traditional_keys = {
            '亞', '侶', '俠', '倫', '僕', '兒', '務', '勞', '嚇', '夥', '奧', '寶', '師', '戰', '暫', '楊',
            '極', '樂', '機', '櫻', '殺', '潔', '瀧', '灣', '烏', '爾', '產', '盜', '稱', '紀', '紅', '納',
            '純', '級', '終', '絆', '絲', '維', '綸', '綻', '緣', '罰', '羅', '羈', '與', '華', '萊', '蓮',
            '藍', '蘭', '蘿', '術', '裝', '視', '諾', '貝', '購', '蹟', '車', '軌', '進', '遊', '運', '達',
            '銀', '鎖', '鏈', '鐘', '長', '閃', '陽', '靜', '餅', '馬', '驚', '髮', '魚', '魯', '鳴', '鶴',
            '麗', '麥', '愛', '瑪', '乾'
        }

        # 验证别名库中没有任何已知繁体残留字符
        for entry in alias_payload.get("entries", []):
            for alias in entry.get("aliases", []):
                for ch in alias:
                    self.assertNotIn(
                        ch, t2s_traditional_keys,
                        f"别名 {alias!r} (对应 {entry.get('name_zh_tw')}) 中存在未转换的繁体字 {ch!r}"
                    )

        voice_resolver = VoiceCharacterResolver(assets_dir)

        # 5 个重点关注的用例验证
        key_cases = [
            ("米蘭達", "米兰达"),
            ("布麗德：靜默軌道", "布丽德：静默轨道"),
            ("艾瑪：戰術升級", "艾玛：战术升级"),
            ("麥斯威爾", "麦斯威尔"),
            ("德雷克：終極反派", "德雷克：终极反派"),
        ]
        for tc, sc in key_cases:
            tc_key = voice_resolver.resolve(tc)
            sc_key = voice_resolver.resolve(sc)
            self.assertIsNotNone(tc_key, f"繁中 {tc} 解析失败")
            self.assertIsNotNone(sc_key, f"简中 {sc} 解析失败")
            self.assertEqual(tc_key, sc_key, f"{tc} 与 {sc} 解析的角色键不一致")

        aliases_by_tw = {e["name_zh_tw"]: e.get("aliases", []) for e in alias_payload.get("entries", [])}

        # 200 角色全量遍历
        for char in characters:
            char_key = char["character_key"]
            resource_id = char["resource_id"]
            name_zh_tw = char["name_zh_tw"]
            name_en = char["name_en"]
            spine_asset_id = char["spine_asset_id"]

            with self.subTest(character=char_key):
                # 1. 繁中解析
                self.assertEqual(voice_resolver.resolve(name_zh_tw), char_key)
                # 2. 简中受控别名解析
                for alias in aliases_by_tw.get(name_zh_tw, []):
                    self.assertEqual(voice_resolver.resolve(alias), char_key)
                # 3. 英文解析（当英文名称唯一时精准匹配；官方同名英文如 Rei / Sakura 则解析到合法同名角色）
                resolved_en = voice_resolver.resolve(name_en)
                self.assertIsNotNone(resolved_en)
                if name_en.lower() not in {"rei", "sakura"}:
                    self.assertEqual(resolved_en, char_key)
                else:
                    self.assertIn(resolved_en, {"rei", "rei_abnormal", "sakura", "sakura_abnormal"})
                # 4. 规范键解析
                self.assertEqual(voice_resolver.resolve(char_key), char_key)
                # 5. Spine 资产号解析
                self.assertEqual(voice_resolver.resolve(spine_asset_id), char_key)
                # 6. resource_id 解析
                self.assertEqual(voice_resolver.resolve(str(resource_id)), char_key)


if __name__ == "__main__":
    unittest.main()
