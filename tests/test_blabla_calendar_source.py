import copy
import json
from pathlib import Path
import httpx
import pytest
from astrbot_plugin_nikke.integrations.calendar.blabla_source import BlablaCalendarAdapter
from astrbot_plugin_nikke.features.calendar.service import CalendarService

def sample():
    return json.loads((Path(__file__).parent/"fixtures/blabla_calendar_public.json").read_text(encoding="utf-8"))

def test_real_public_sample():
    result=BlablaCalendarAdapter.parse(sample())
    assert len(result.events)==9
    assert len([e for e in result.events if e.event_type=="login"])==2
    assert {e.primary_source for e in result.events}=={"blabla"}
    assert all(e.start_precision==e.end_precision=="EXACT" for e in result.events)
    assert all(e.banner_url.startswith("https://sg-tools-cdn.blablalink.com/") for e in result.events if e.banner_url)
    assert not any(e.event_type in {"arena","simulation_room"} for e in result.events)

def test_parallel_story_and_recruit_remain_distinct():
    payload=sample();row=copy.deepcopy(payload["data"]["version_event"]["items"][0]);row["name"]="第二个剧情活动";payload["data"]["version_event"]["items"].append(row)
    result=BlablaCalendarAdapter.parse(payload)
    assert len([e for e in result.events if e.event_type=="story_event"])==2
    assert len([e for e in result.events if e.event_type=="recruit"])==2

def test_invalid_row_is_partial_and_never_zero_time():
    payload=sample();payload["data"]["raid"]["items"][0]["end_time"]="unknown"
    result=BlablaCalendarAdapter.parse(payload)
    assert result.completeness=="PARTIAL"
    assert not any(e.event_type=="union_raid" for e in result.events)

@pytest.mark.parametrize("payload", [{},{"code":1,"data":{}},{"code":0,"data":{}}])
def test_bad_contract_fails_closed(payload):
    with pytest.raises(ValueError):BlablaCalendarAdapter.parse(payload)

def test_only_blabla_no_legacy_data(tmp_path):
    service=CalendarService(tmp_path,source_mode="blabla")
    assert [a.source_name for a in service.adapters]==["blabla"]
    assert service.list_canonical()==[]

@pytest.mark.asyncio
async def test_public_request_no_credentials():
    def handler(request):
        assert request.method=="POST"
        assert "cookie" not in request.headers
        assert request.headers["X-Language"]=="zh-TW"
        return httpx.Response(200,json=sample())
    result=await BlablaCalendarAdapter(transport=httpx.MockTransport(handler)).fetch_result()
    assert len(result.events)==9


def test_disabled_sources_are_removed_from_persisted_snapshot(tmp_path):
    from astrbot_plugin_nikke.features.calendar.canonical_models import CanonicalEvent
    from datetime import datetime, timezone, timedelta
    now=datetime.now(timezone.utc)
    old=CalendarService(tmp_path)
    old._source_datasets={"gamekee":[CanonicalEvent(id="old",title="旧事件",event_type="story_event",start_at=now,end_at=now+timedelta(days=1),sources=["gamekee"],primary_source="gamekee")]}
    old._sync_internal_stores(old._merge_datasets());old._has_snapshot=True;old._save_cache(force_events=True)
    new=CalendarService(tmp_path,source_mode="blabla")
    assert new.list_canonical()==[]
    assert "gamekee" not in new._source_datasets
    assert not new.has_snapshot()


@pytest.mark.asyncio
async def test_manual_refresh_never_calls_disabled_announcement_source(tmp_path):
    from unittest.mock import AsyncMock
    from types import SimpleNamespace
    announcement=SimpleNamespace(sync_from_source=AsyncMock())
    service=CalendarService(tmp_path,source_mode="blabla",announcement_service=announcement)
    service.adapters=[BlablaCalendarAdapter(transport=httpx.MockTransport(lambda request:httpx.Response(200,json=sample())))]
    result=await service.application.refresh_schedule()
    assert result.success
    announcement.sync_from_source.assert_not_called()
    assert service.activity_count()==9
    await service.aclose()
