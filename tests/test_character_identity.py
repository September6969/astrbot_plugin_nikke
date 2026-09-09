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


if __name__ == "__main__":
    unittest.main()
