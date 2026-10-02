"""真实文件落盘失败、来源隐藏更新和跨文件发布恢复合同。"""

import json
import subprocess
import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone

import pytest

from astrbot_plugin_nikke.features.calendar.canonical_models import CanonicalEvent, FetchOutcome
from astrbot_plugin_nikke.features.calendar.schedule_adapters import BaseScheduleAdapter, FetchResult
from astrbot_plugin_nikke.features.calendar.schedule_service import ScheduleService


class Source(BaseScheduleAdapter):
    source_name = "gamekee"

    def __init__(self, title="A"):
        self.title = title

    async def fetch_result(self):
        now = datetime(2026, 9, 29, tzinfo=timezone.utc)
        return FetchResult(FetchOutcome.SUCCESS_DATA, [CanonicalEvent(
            id="event", title=self.title, event_type="event", start_at=now,
            end_at=now + timedelta(days=4), primary_source=self.source_name, sources=[self.source_name],
        )], source=self.source_name)


@pytest.mark.asyncio
async def test_disk_failure_keeps_memory_then_identical_refresh_recovers_and_restarts(tmp_path, monkeypatch):
    service = ScheduleService(tmp_path)
    source = Source()
    service.adapters = [source]
    assert (await service.refresh_schedule_data())[0]
    old_disk = service.events_path.read_bytes()
    source.title = "B"
    with monkeypatch.context() as patch:
        patch.setattr(service, "_save_cache", lambda **kw: (_ for _ in ()).throw(OSError("disk full")))
        ok, message = await service.refresh_schedule_data()
    assert not ok and "persist" in message
    assert service.list_canonical()[0].title == "B"
    assert service.events_path.read_bytes() == old_disk
    assert service.snapshot_state.dirty
    assert service.snapshot_state.durability_error
    assert service.snapshot_diagnostics["dirty"]
    assert (await service.refresh_schedule_data())[0]
    assert not service.snapshot_state.dirty
    restarted = ScheduleService(tmp_path)
    assert restarted.list_canonical()[0].title == "B"
    assert not restarted.snapshot_state.dirty
    # 独立进程只依赖磁盘快照，不继承当前实例的内存状态。
    program = (
        "import sys; from astrbot_plugin_nikke.features.calendar.schedule_service import ScheduleService; "
        "service = ScheduleService(sys.argv[1]); print(service.list_canonical()[0].title)"
    )
    result = subprocess.run([sys.executable, "-X", "utf8", "-c", program, str(tmp_path)],
                            cwd=Path(__file__).resolve().parents[2], capture_output=True,
                            text=True, encoding="utf-8", check=True)
    assert result.stdout.strip() == "B"


@pytest.mark.asyncio
async def test_hidden_source_update_survives_restart_and_override_removal(tmp_path):
    service = ScheduleService(tmp_path)
    source = Source()
    service.adapters = [source]
    service.overrides_path.write_text(json.dumps([{"event_id": "event", "field": "title", "value": "fixed"}]), encoding="utf-8")
    assert (await service.refresh_schedule_data())[0]
    display = service._last_batch_hash
    source.title = "B"
    assert (await service.refresh_schedule_data())[0]
    assert service._last_batch_hash == display
    restarted = ScheduleService(tmp_path)
    restarted.overrides_path.unlink()
    restarted.reload_overrides()
    assert restarted.list_canonical()[0].title == "B"


@pytest.mark.asyncio
@pytest.mark.parametrize("newer", ["events", "health"])
async def test_generation_mismatch_is_detected_and_snapshot_is_authority(tmp_path, newer):
    service = ScheduleService(tmp_path)
    source = Source()
    service.adapters = [source]
    await service.refresh_schedule_data()
    old_events = service.events_path.read_bytes()
    old_health = service.health_path.read_bytes()
    source.title = "B"
    await service.refresh_schedule_data()
    if newer == "events":
        service.health_path.write_bytes(old_health)
    else:
        service.events_path.write_bytes(old_events)
    restarted = ScheduleService(tmp_path)
    assert restarted.list_canonical()[0].title == ("B" if newer == "events" else "A")
    assert restarted.snapshot_state.dirty
    assert "generation" in restarted.snapshot_state.durability_error
    assert restarted.last_success_at is None


@pytest.mark.asyncio
async def test_schema_four_is_readable_and_upgraded_without_deleting_cache(tmp_path):
    service = ScheduleService(tmp_path)
    service.adapters = [Source()]
    await service.refresh_schedule_data()
    payload = json.loads(service.events_path.read_text(encoding="utf-8"))
    payload["schema"] = 4
    payload.pop("generation", None)
    service.events_path.write_text(json.dumps(payload), encoding="utf-8")
    restarted = ScheduleService(tmp_path)
    assert restarted.list_canonical()[0].title == "A"
    restarted.adapters = [Source()]
    assert (await restarted.refresh_schedule_data())[0]
    assert json.loads(restarted.events_path.read_text(encoding="utf-8"))["schema"] == 5


@pytest.mark.asyncio
async def test_nonwinning_source_updates_are_durable(tmp_path):
    service = ScheduleService(tmp_path)
    primary = Source("winner")
    secondary = Source("loser-A")
    secondary.source_name = "official"
    # 同一期次显式身份，使标题由 gamekee 胜出。
    original = secondary.fetch_result
    async def fetch():
        result = await original()
        result.events[0].cycle_id = "cycle"
        return result
    secondary.fetch_result = fetch
    original_primary = primary.fetch_result
    async def fetch_primary():
        result = await original_primary()
        result.events[0].cycle_id = "cycle"
        return result
    primary.fetch_result = fetch_primary
    service.adapters = [primary, secondary]
    await service.refresh_schedule_data()
    before = service.snapshot_state.active_source_revision
    secondary.title = "loser-B"
    await service.refresh_schedule_data()
    assert service.list_canonical()[0].title == "winner"
    assert service.snapshot_state.active_source_revision != before
    restarted = ScheduleService(tmp_path)
    assert restarted._source_datasets["official"][0].title == "loser-B"


@pytest.mark.asyncio
async def test_health_publish_failure_is_detectable_on_restart_and_retry(tmp_path, monkeypatch):
    service = ScheduleService(tmp_path)
    source = Source()
    service.adapters = [source]
    await service.refresh_schedule_data()
    before = service.snapshot_state.persisted_source_revision
    source.title = "B"
    original = service.snapshot_repository._atomic_write
    def write(path, payload):
        if path == service.health_path:
            raise OSError("health publication failed")
        original(path, payload)
    with monkeypatch.context() as patch:
        patch.setattr(service.snapshot_repository, "_atomic_write", write)
        # 实际发布使用静态 owner 的方法。
        patch.setattr(type(service.snapshot_repository), "_atomic_write", staticmethod(write))
        assert not (await service.refresh_schedule_data())[0]
    assert service.snapshot_state.persisted_source_revision == before
    restarted = ScheduleService(tmp_path)
    assert restarted.list_canonical()[0].title == "B"
    assert restarted.snapshot_state.dirty
    assert (await service.refresh_schedule_data())[0]
    assert not ScheduleService(tmp_path).snapshot_state.dirty


@pytest.mark.asyncio
async def test_identical_source_refresh_does_not_rewrite_events(tmp_path, monkeypatch):
    service = ScheduleService(tmp_path)
    service.adapters = [Source()]
    await service.refresh_schedule_data()
    before = service.events_path.read_bytes()
    generation = service.snapshot_state.generation
    await service.refresh_schedule_data()
    assert service.events_path.read_bytes() == before
    assert service.snapshot_state.generation == generation


@pytest.mark.asyncio
async def test_source_dataset_version_is_not_health_attempt_noise(tmp_path):
    service = ScheduleService(tmp_path)
    service.adapters = [Source()]
    await service.refresh_schedule_data()
    before = service.snapshot_state.active_source_revision
    service._source_health["gamekee"].dataset_version += 1
    await service.refresh_schedule_data()
    assert service.snapshot_state.active_source_revision != before
    restarted = ScheduleService(tmp_path)
    assert restarted._source_health["gamekee"].dataset_version == 2
    assert not restarted.snapshot_state.dirty
