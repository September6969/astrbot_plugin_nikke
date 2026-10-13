"""用户确认的日程类别与公告阶段抓取回归。"""
from types import SimpleNamespace
import pytest
from astrbot_plugin_nikke.features.announcement.deadlines import DeadlineParser
from astrbot_plugin_nikke.features.calendar.content_quality import classify_category
from astrbot_plugin_nikke.features.calendar.schedule_adapters import OfficialAnnouncementScheduleAdapter

@pytest.mark.parametrize("title,expected", [
    ("14-Day Login Event – HAPPY DAYS", "login"),
    ("【签到】每日奖励", "login"),
    ("Free Recruit Event", "free_reward"),
    ("免费领取 SSR 角色", "free_reward"),
    ("Story Event: TEST", "story_event"),
    ("个人突袭", "solo_raid"),
    ("Special Recruit SSR Alice", "recruit"),
])
def test_required_categories(title, expected):
    assert classify_category(title, description="Recruit vouchers and new character packages") == expected

BODY = """1. Story Event: TEST
1.1 Story 1
2026-10-08 05:00 ~ 2026-10-28 04:59 (UTC+9)
1.2 Story 2
2026-10-15 05:00 ~ 2026-10-28 04:59 (UTC+9)
1.3 Hard
2026-10-22 05:00 ~ 2026-10-28 04:59 (UTC+9)
2. 14-Day Login Event: HAPPY DAYS
2026-10-08 05:00 ~ 2026-10-28 04:59 (UTC+9)
3. Free Recruit Event
2026-10-08 05:00 ~ 2026-10-28 04:59 (UTC+9)
4. New Character Packages
Available after maintenance. Cancel old package.
2026-10-08 05:00 ~ 2026-10-28 04:59 (UTC+9)
"""

def test_parent_story_title_survives_without_own_dates():
    rows = DeadlineParser.parse_deadlines("Update", BODY, "sample")
    assert len(rows) == 6
    assert [r.name for r in rows[:3]] == [f"Story Event: TEST · {stage}" for stage in ("Story 1", "Story 2", "Hard")]
    assert rows[1].start_at.day == 14
    assert "Packages" not in rows[0].description


def test_time_first_range_is_not_dropped():
    rows = DeadlineParser.parse_deadlines("Free Recruit", "05:00 October 8, 2026 ~ 04:59 October 28, 2026 (UTC+9)")
    assert len(rows) == 1
    assert rows[0].start_at.hour == 20

@pytest.mark.asyncio
async def test_official_sections_do_not_inherit_sibling_category_or_cancellation():
    record = SimpleNamespace(title="Update", body=BODY, content_id="sample", category="event", source_url="")
    service = SimpleNamespace(_records={"sample": record}, list_deadlines=lambda: [])
    result = await OfficialAnnouncementScheduleAdapter(service).fetch_result()
    assert len(result.events) == 6
    assert [r.event_type for r in result.events[:5]] == ["story_event"] * 3 + ["login", "free_reward"]
    assert all(not r.is_cancelled for r in result.events[:5])


def test_free_login_gift_is_not_paid_recruit_or_costume():
    assert classify_category("Cinderella Special", description="Log in during the event to receive Cinderella's limited costume.") == "free_reward"
    assert classify_category("Special Recruit", description="Use Gems (Free/Paid) to recruit.") == "recruit"


def test_two_overlapping_story_events_keep_separate_parents():
    body = BODY.split("2. 14-Day")[0] + BODY.split("2. 14-Day")[0].replace("1. Story Event: TEST", "2. Story Event: HALLOWEEN").replace("1.1 Story", "2.1 Story").replace("1.2 Story", "2.2 Story").replace("1.3 Hard", "2.3 Hard")
    rows = DeadlineParser.parse_deadlines("Update", body, "two-events")
    assert len(rows) == 6
    assert len({r.event_id for r in rows}) == 6
    assert all("TEST" in r.name for r in rows[:3])
    assert all("HALLOWEEN" in r.name for r in rows[3:])


def test_different_story_stages_do_not_merge_across_sources():
    from datetime import datetime, timezone
    from astrbot_plugin_nikke.features.calendar.canonical_models import CanonicalEvent
    from astrbot_plugin_nikke.features.calendar.merge import _is_same_identity
    def event(source, stage):
        return CanonicalEvent(id=source, title="Story Event: LITTLE WITCH TRICK · " + stage,
            event_type="story_event", sources=[source], primary_source=source,
            start_at=datetime(2026, 10, 8, tzinfo=timezone.utc),
            end_at=datetime(2026, 10, 28, tzinfo=timezone.utc), detail_url="https://example.com/update")
    assert not _is_same_identity(event("official", "Story 1"), event("gamekee", "Story 2"))
    assert _is_same_identity(event("official", "Story 1"), event("gamekee", "Story 1"))


def test_two_different_story_names_never_merge_on_shared_update_url():
    from datetime import datetime, timezone
    from astrbot_plugin_nikke.features.calendar.canonical_models import CanonicalEvent
    from astrbot_plugin_nikke.features.calendar.merge import _is_same_identity
    def event(source, name):
        return CanonicalEvent(id=source, title=name, event_type="story_event",
            sources=[source], primary_source=source,
            start_at=datetime(2026, 10, 8, tzinfo=timezone.utc),
            end_at=datetime(2026, 10, 28, tzinfo=timezone.utc), detail_url="https://example.com/update")
    assert not _is_same_identity(event("official", "LITTLE WITCH TRICK"), event("gamekee", "MOST BEAUTIFUL MAID"))


@pytest.mark.parametrize("title,category,visible", [
    ("四周年情报站", "event", False),
    ("Limited Costume: Novel", "limited_costume", False),
    ("限时时装", "event", False),
    ("Costume Gacha: Cinderella", "costume_gacha", True),
    ("免费领取皮肤", "free_reward", True),
    ("Story Event: HALLOWEEN", "story_event", True),
])
def test_user_calendar_scope(title, category, visible):
    from astrbot_plugin_nikke.features.calendar.content_quality import include_calendar_event
    assert include_calendar_event(SimpleNamespace(title=title, event_type=category)) is visible


def test_localized_calendar_labels_preserve_proper_names_and_stages():
    from astrbot_plugin_nikke.features.calendar.content_quality import calendar_display_title
    assert calendar_display_title("Union Raid") == "联盟突袭"
    assert calendar_display_title("14-Day Login Event - DAILY TRICK") == "14日签到 - DAILY TRICK"
    assert calendar_display_title("October Mission Pass") == "10月 Pass"
    assert calendar_display_title("New Story Event: LITTLE WITCH TRICK · Story 2") == "支线活动 · LITTLE WITCH TRICK · Story 2"


@pytest.mark.parametrize("local,official,category", [
    ("【签到】DAILY TRICK（14日）", "14-Day Login Event - DAILY TRICK", "login"),
    ("【活动PASS】OCCULTIST PASS（蕾贝尔）", "OCCULTIST PASS", "pass"),
    ("【支线】LITTLE WITCH TRICK", "New Story Event: LITTLE WITCH TRICK", "story_event"),
])
def test_known_bilingual_wrappers_and_date_boundary(local, official, category):
    from datetime import datetime, timezone, timedelta
    from astrbot_plugin_nikke.features.calendar.canonical_models import CanonicalEvent
    from astrbot_plugin_nikke.features.calendar.content_quality import canonical_identity_match
    start = datetime(2026,10,7,16,tzinfo=timezone.utc)
    a = CanonicalEvent(id="gamekee:1", title=local, event_type=category, primary_source="gamekee", sources=["gamekee"], start_at=start, end_at=start+timedelta(days=20))
    b = CanonicalEvent(id="official:1", title=official, event_type=category, primary_source="official", sources=["official"], start_at=start, start_precision="DATE_ONLY", end_at=start+timedelta(days=20,hours=23))
    assert canonical_identity_match(a,b) is not None
    b.title += " · Story 2"
    assert canonical_identity_match(a,b) is None
    b.title = official
    b.end_at += timedelta(days=3)
    assert canonical_identity_match(a,b) is None


@pytest.mark.parametrize("title,category", [
    ("Temporary Participation Nikkes", "recruit"),
    ("New character packages", "package"),
    ("New character packages will be available after maintenance", "maintenance"),
    ("Simulation Room - Overclock Mode (Season 10)", "event"),
])
def test_out_of_scope_calendar_rows_are_hidden(title,category):
    from astrbot_plugin_nikke.features.calendar.content_quality import include_calendar_event
    assert not include_calendar_event(SimpleNamespace(title=title,event_type=category))

@pytest.mark.asyncio
async def test_fake_dns_rechecks_public_address_and_pins_tls_host(tmp_path,monkeypatch):
    import socket, httpx
    from astrbot_plugin_nikke.integrations.calendar.visual_cache import CalendarVisualCache
    import io
    from PIL import Image
    def png():
        buffer=io.BytesIO()
        Image.new("RGB",(16,16)).save(buffer,format="PNG")
        return buffer.getvalue()
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [(socket.AF_INET,socket.SOCK_STREAM,6,"",("198.18.0.153",443))])
    seen=[]
    async def respond(request):
        seen.append(request)
        if request.url.host == "dns.google":
            return httpx.Response(200,json={"Status":0,"Answer":[{"type":1,"data":"43.174.197.47"}]})
        return httpx.Response(200,headers={"content-type":"image/png"},content=png())
    cache=CalendarVisualCache(tmp_path)
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        data,w,h=await cache._download_image(client,"https://cdnimg-v2.gamekee.com/image.png")
    assert data and w and h
    assert seen[-1].url.host == "43.174.197.47"
    assert seen[-1].headers["host"] == "cdnimg-v2.gamekee.com"
    assert seen[-1].extensions["sni_hostname"] == "cdnimg-v2.gamekee.com"

@pytest.mark.asyncio
async def test_fake_dns_never_accepts_private_answer_or_unknown_host(tmp_path,monkeypatch):
    import socket, httpx
    from astrbot_plugin_nikke.integrations.calendar.visual_cache import CalendarVisualCache
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [(socket.AF_INET,socket.SOCK_STREAM,6,"",("198.18.0.153",443))])
    cache=CalendarVisualCache(tmp_path)
    seen=[]
    def respond(request):
        seen.append(request)
        return httpx.Response(200,json={"Status":0,"Answer":[{"type":1,"data":"127.0.0.1"}]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(ValueError):
            await cache._download_image(client,"https://cdnimg-v2.gamekee.com/image.png")
        with pytest.raises(ValueError):
            await cache._download_image(client,"https://unknown.example/image.png")
    assert len(seen)==1 and seen[0].url.host=="dns.google"
