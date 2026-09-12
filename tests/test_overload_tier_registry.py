import json
from pathlib import Path

from overload_tier_registry import OverloadTierRegistry


ROOT = Path(__file__).resolve().parents[1]


class TestOverloadTierRegistry:
    def test_public_registry_covers_all_ol_levels_and_groups(self):
        registry = OverloadTierRegistry.from_file(ROOT / "assets" / "overload_tiers.json")

        assert registry.is_valid
        assert registry.group_count == 9
        assert registry.record_count == 27
        assert {registry.resolve(f"70005{index:02d}").level for index in range(1, 16)} == set(range(1, 16))
        assert registry.resolve("7000611").level == 11
        assert registry.resolve("7000611").group_id == "100200"
        assert registry.resolve("7000611").label == "命中率增加"

    def test_unknown_or_non_ol_state_effect_is_unresolved(self):
        registry = OverloadTierRegistry.from_file(ROOT / "assets" / "overload_tiers.json")

        assert registry.resolve("9310101") is None
        assert registry.resolve("7000599") is None
        assert registry.resolve(None) is None

    def test_every_authoritative_group_has_t1_to_t15(self):
        registry = OverloadTierRegistry.from_file(ROOT / "assets" / "overload_tiers.json")

        grouped = {}
        for entry in registry.entries:
            grouped.setdefault(entry.group_id, []).append(entry)
        assert len(grouped) == 9
        for group_id, entries in grouped.items():
            assert {entry.level for entry in entries} == set(range(1, 16)), group_id
            for level in (1, 5, 6, 10, 11, 15):
                resolved = next(entry for entry in entries if entry.level == level)
                assert registry.resolve(resolved.state_effect_id) == resolved
                assert resolved.label

    def test_registry_rejects_duplicate_state_effects(self, tmp_path):
        data = {
            "schema_version": 1,
            "status": "PUBLIC_ALGORITHM_VERIFIED",
            "source_url": "https://example.invalid/source.json",
            "source_sha256": "a" * 64,
            "algorithm_source_url": "https://example.invalid/bundle.js",
            "algorithm_source_sha256": "b" * 64,
            "groups": [
                {
                    "id": 1001001,
                    "state_effect_group_id": 100100,
                    "description_localkey": "【攻擊力增加】",
                    "state_effect_id_list": [7000501, 7000502, 7000503, 7000504, 7000505],
                },
                {
                    "id": 1001002,
                    "state_effect_group_id": 100100,
                    "description_localkey": "【攻擊力增加】",
                    "state_effect_id_list": [7000501, 7000507, 7000508, 7000509, 7000510],
                },
            ],
        }
        path = tmp_path / "overload_tiers.json"
        path.write_text(json.dumps(data), encoding="utf-8")

        registry = OverloadTierRegistry.from_file(path)

        assert not registry.is_valid
        assert any("重复" in error for error in registry.errors)
