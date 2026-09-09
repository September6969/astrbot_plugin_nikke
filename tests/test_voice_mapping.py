"""验证语音映射的精确身份合同，不把未知角色或服装借给默认项。"""

import json
import tempfile
from pathlib import Path
from unittest import TestCase

from astrbot_plugin_nikke.voice_mapping import VoiceMapRegistry


class VoiceMappingTests(TestCase):
    def test_empty_repository_map_is_valid_and_has_no_fallback(self):
        path = Path(__file__).resolve().parents[1] / "assets" / "voice_poke_map.json"
        registry = VoiceMapRegistry(path)
        self.assertTrue(registry.is_valid)
        self.assertIsNone(registry.resolve("alice", "default", "en"))
        self.assertIsNone(registry.resolve("unknown", "default", "en"))
        self.assertIsNone(registry.resolve("alice", "summer", "en"))

    def test_verified_entry_requires_exact_character_costume_and_locale(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "voice_poke_map.json"
            path.write_text(json.dumps({
                "schema_version": 2,
                "entries": [{
                    "character": "alice",
                    "costume": "default",
                    "spine_asset_id": "c191",
                    "locale": "en",
                    "map_key": "alice_poke",
                    "speech_id": "alice_poke_01",
                    "source": "https://example.invalid/source",
                    "source_ref": "https://example.invalid/voice-map",
                    "checked_at": "2026-09-08",
                }],
            }), encoding="utf-8")

            registry = VoiceMapRegistry(path)

            mapping = registry.resolve("alice", "default", "en")
            self.assertEqual(mapping.map_key, "alice_poke")
            self.assertIsNone(registry.resolve("alice", "other", "en"))
            self.assertIsNone(registry.resolve("alice", "default", "ja"))
            self.assertIsNone(registry.resolve("unknown", "default", "en"))

    def test_invalid_or_duplicate_entries_disable_registry(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "voice_poke_map.json"
            row = {
                "character": "alice", "costume": "default", "spine_asset_id": "c191", "locale": "en",
                "map_key": "map", "speech_id": "line", "source": "https://example.invalid/source",
                "source_ref": "https://example.invalid/map", "checked_at": "2026-09-08",
            }
            path.write_text(json.dumps({"schema_version": 2, "entries": [row, row]}), encoding="utf-8")
            registry = VoiceMapRegistry(path)
            self.assertFalse(registry.is_valid)
            self.assertIsNone(registry.resolve("alice", "default", "en"))
