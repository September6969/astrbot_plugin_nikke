"""公开塔层查询不需要绑定账号，并安全处理未知层数与损坏快照。"""
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from astrbot_plugin_nikke.tower_registry import TowerRegistry
from astrbot_plugin_nikke.main import NikkePlugin


class TowerTests(IsolatedAsyncioTestCase):
    @staticmethod
    def _snapshot() -> dict:
        return {
            "source": "https://example.invalid/tower.json",
            "retrieved_at": "2026-09-05",
            "normalized_source_sha256": "a" * 64,
            "floors": {
                "tribe:1": {"stage_id": 10001, "standard_battle_power": 1260},
            },
        }

    @staticmethod
    def _write_snapshot(root: Path, data: object) -> Path:
        path = root / "tower_floors.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def test_snapshot_and_unknown(self):
        registry = TowerRegistry(Path(__file__).resolve().parents[1] / "assets/tower_floors.json")
        self.assertIn("7,740", registry.describe("极乐净土", "1"))
        self.assertIn("未收录", registry.describe("elysion", "9999"))
        self.assertIn("用法", registry.describe("other", "1"))
        self.assertIn("用法", registry.describe("tribe", "-1"))

    def test_snapshot_contract_rejects_invalid_metadata_and_records(self):
        cases = (
            ("blank source", lambda data: data.update(source=" ")),
            ("noncanonical date", lambda data: data.update(retrieved_at="2026-9-5")),
            ("invalid hash", lambda data: data.update(normalized_source_sha256="A" * 64)),
            ("invalid key", lambda data: data.update(floors={"tribe:01": {"stage_id": 1, "standard_battle_power": 1}})),
            ("boolean power", lambda data: data.update(floors={"tribe:1": {"stage_id": 1, "standard_battle_power": True}})),
            ("duplicate stage", lambda data: data.update(floors={"tribe:1": {"stage_id": 1, "standard_battle_power": 1}, "elysion:1": {"stage_id": 1, "standard_battle_power": 2}})),
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for label, mutate in cases:
                with self.subTest(label=label):
                    data = self._snapshot()
                    mutate(data)
                    with self.assertRaises(ValueError):
                        TowerRegistry(self._write_snapshot(root, data))

    def test_describe_rejects_noncanonical_input_without_guessing(self):
        with tempfile.TemporaryDirectory() as directory:
            registry = TowerRegistry(self._write_snapshot(Path(directory), self._snapshot()))
            self.assertIn("1,260", registry.describe("部落", "1"))
            for tower, floor in ((None, "1"), ("tribe", None), ("tribe", "01"), ("tribe", "+1"), ("tribe", "１")):
                with self.subTest(tower=tower, floor=floor):
                    self.assertIn("用法", registry.describe(tower, floor))

    async def test_command_does_not_need_account(self):
        plugin = NikkePlugin.__new__(NikkePlugin)
        plugin.plugin_dir = Path(__file__).resolve().parents[1]
        event = SimpleNamespace(plain_result=lambda x: x)
        result = [x async for x in plugin.nikke(event, "塔层", "极乐净土", "1")]
        self.assertEqual(len(result), 1)
        self.assertIn("7,740", result[0])

    async def test_command_fails_closed_for_a_corrupt_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            plugin = NikkePlugin.__new__(NikkePlugin)
            plugin.plugin_dir = Path(directory)
            assets = plugin.plugin_dir / "assets"
            assets.mkdir()
            self._write_snapshot(assets, {"floors": {}})
            event = SimpleNamespace(plain_result=lambda value: value)
            result = [value async for value in plugin.nikke(event, "塔层", "部落", "1")]
            self.assertEqual(result, ["塔层静态资料暂不可用。"])
