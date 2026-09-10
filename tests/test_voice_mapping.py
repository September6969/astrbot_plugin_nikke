"""验证语音映射的精确身份合同，不把未知角色或服装借给默认项。"""

import json
import tempfile
from pathlib import Path
from unittest import TestCase

from astrbot_plugin_nikke.voice_mapping import VoiceMapRegistry


class VoiceMappingTests(TestCase):
    def test_repository_map_is_valid_and_resolves_verified_rapi_without_fallback(self):
        path = Path(__file__).resolve().parents[1] / "assets" / "voice_poke_map.json"
        registry = VoiceMapRegistry(path)
        self.assertTrue(registry.is_valid)
        rapi_ja = registry.resolve("rapi", "default", "ja")
        self.assertIsNotNone(rapi_ja)
        self.assertEqual(rapi_ja.speech_id, "c010_Lobby_Touch_1")
        self.assertEqual(rapi_ja.line_kind, "Lobby_Touch")
        self.assertEqual(rapi_ja.line_index, 1)
        self.assertEqual(rapi_ja.map_key, "roledata_10")
        self.assertEqual(rapi_ja.spine_asset_id, "c010")

        # Multi-line resolution
        rapi_ja_2 = registry.resolve("rapi", "default", "ja", line_index=2)
        self.assertIsNotNone(rapi_ja_2)
        self.assertEqual(rapi_ja_2.speech_id, "c010_Lobby_Touch_2")

        # Multi-locale resolution
        self.assertIsNotNone(registry.resolve("rapi", "default", "en"))
        self.assertIsNotNone(registry.resolve("rapi", "default", "ko"))

        # Spine asset resolution
        spine_match = registry.resolve_by_spine_asset("c010", "ja")
        self.assertIsNotNone(spine_match)
        self.assertEqual(spine_match.speech_id, "c010_Lobby_Touch_1")

        # Costume resolution: c010_02 is 20001 (White Promise), c010_03 is 10005 (Classic Vacation)
        white_promise = registry.resolve_by_spine_asset("c010_02", "ja")
        self.assertIsNotNone(white_promise)
        self.assertEqual(white_promise.character, "rapi")
        self.assertEqual(white_promise.costume, "20001")

        classic_vacation = registry.resolve_by_spine_asset("c010_03", "ja")
        self.assertIsNotNone(classic_vacation)
        self.assertEqual(classic_vacation.character, "rapi")
        self.assertEqual(classic_vacation.costume, "10005")

        # Independent costume voice resolution (Drake Villain Racer)
        drake_costume = registry.resolve_by_spine_asset("c101_01", "ja")
        self.assertIsNotNone(drake_costume)
        self.assertEqual(drake_costume.speech_id, "c101_01_Lobby_Touch_1")

        # Rejection of non-Lobby_Touch lines for Poke
        self.assertIsNone(registry.resolve("rapi", "default", "ja", line_kind="story"))
        self.assertIsNone(registry.resolve_by_spine_asset("c010", "ja", line_kind="story"))

        # Unknown character/costume rejection
        self.assertIsNone(registry.resolve("rapi", "other", "ja"))
        self.assertIsNone(registry.resolve("unknown", "default", "en"))
        self.assertIsNone(registry.resolve("alice", "summer", "en"))

    def test_verified_entry_requires_exact_character_costume_and_locale(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "voice_poke_map.json"
            path.write_text(json.dumps({
                "schema_version": 3,
                "entries": [{
                    "character": "alice",
                    "costume": "default",
                    "spine_asset_id": "c191",
                    "locale": "en",
                    "line_kind": "Lobby_Touch",
                    "line_index": 1,
                    "map_key": "roledata_191",
                    "speech_id": "c191_Lobby_Touch_1",
                    "source": "https://example.invalid/source.mp3",
                    "source_ref": "https://example.invalid/roledata.json",
                    "checked_at": "2026-09-08",
                }],
            }), encoding="utf-8")

            registry = VoiceMapRegistry(path)

            mapping = registry.resolve("alice", "default", "en")
            self.assertEqual(mapping.map_key, "roledata_191")
            self.assertEqual(mapping.speech_id, "c191_Lobby_Touch_1")
            self.assertIsNone(registry.resolve("alice", "other", "en"))
            self.assertIsNone(registry.resolve("alice", "default", "ja"))
            self.assertIsNone(registry.resolve("unknown", "default", "en"))

    def test_invalid_or_duplicate_entries_disable_registry(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "voice_poke_map.json"
            row = {
                "character": "alice", "costume": "default", "spine_asset_id": "c191", "locale": "en",
                "line_kind": "Lobby_Touch", "line_index": 1,
                "map_key": "map", "speech_id": "line", "source": "https://example.invalid/source",
                "source_ref": "https://example.invalid/map", "checked_at": "2026-09-08",
            }
            path.write_text(json.dumps({"schema_version": 3, "entries": [row, row]}), encoding="utf-8")
            registry = VoiceMapRegistry(path)
            self.assertFalse(registry.is_valid)
            self.assertIsNone(registry.resolve("alice", "default", "en"))

    def test_resolve_poke_selects_all_registered_lines_and_never_unregistered(self):
        path = Path(__file__).resolve().parents[1] / "assets" / "voice_poke_map.json"
        registry = VoiceMapRegistry(path)
        self.assertTrue(registry.is_valid)

        # Rapi has 3 Lobby_Touch lines
        candidates = registry.resolve_candidates("rapi", "default", "ja")
        self.assertEqual(len(candidates), 3)
        self.assertEqual({c.line_index for c in candidates}, {1, 2, 3})

        observed_indices = set()
        for _ in range(100):
            selected = registry.resolve_poke("rapi", "default", "ja")
            self.assertIsNotNone(selected)
            self.assertIn(selected.line_index, {1, 2, 3})
            self.assertTrue(selected.speech_id.startswith("c010_Lobby_Touch_"))
            observed_indices.add(selected.line_index)

        # In 100 trials with uniform random choice, P(missing any of 3) = 3 * (2/3)^100 ~= 7.3e-18
        self.assertEqual(observed_indices, {1, 2, 3})

    def test_resolve_poke_single_line_characters_remain_stable(self):
        path = Path(__file__).resolve().parents[1] / "assets" / "voice_poke_map.json"
        registry = VoiceMapRegistry(path)
        self.assertTrue(registry.is_valid)

        # Test mass-produced R-grade characters with only Lobby_Touch_1
        for char in ("soldier_eg", "soldier_fa", "product_08", "product_12", "idoll_flower"):
            with self.subTest(character=char):
                candidates = registry.resolve_candidates(char, "default", "ja")
                self.assertEqual(len(candidates), 1)
                self.assertEqual(candidates[0].line_index, 1)

                observed = {registry.resolve_poke(char, "default", "ja").line_index for _ in range(30)}
                self.assertEqual(observed, {1})

    def test_resolve_poke_supports_custom_selector(self):
        path = Path(__file__).resolve().parents[1] / "assets" / "voice_poke_map.json"
        registry = VoiceMapRegistry(path)

        # Selector always picks the last candidate (line 3)
        selected = registry.resolve_poke("rapi", "default", "ja", selector=lambda c: c[-1])
        self.assertIsNotNone(selected)
        self.assertEqual(selected.line_index, 3)
