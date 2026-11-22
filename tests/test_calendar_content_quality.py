# SPDX-License-Identifier: GPL-3.0-or-later
"""Calendar Content Quality v1 的离线行为测试。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from astrbot_plugin_nikke.features.calendar.canonical_models import CanonicalEvent
from astrbot_plugin_nikke.features.calendar.content_quality import (
    DisplayTier,
    classify_explicit_title,
    classify_category,
    canonical_event_title,
    get_display_relevance,
    score_display_relevance,
)
from astrbot_plugin_nikke.features.calendar.schedule_service import ScheduleService


UTC = timezone.utc
START = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)


def _event(event_id: str, title: str, category: str = "event", **kwargs) -> CanonicalEvent:
    return CanonicalEvent(
        id=event_id,
        title=title,
        event_type=category,
        start_at=kwargs.pop("start_at", START),
        end_at=kwargs.pop("end_at", START + timedelta(days=2)),
        primary_source=kwargs.pop("primary_source", "gamekee"),
        sources=kwargs.pop("sources", ["gamekee"]),
        banner_url=kwargs.pop("banner_url", "https://cdn.example/visual.png"),
        metadata=kwargs.pop("metadata", {}),
        **kwargs,
    )



def test_category_aliases_and_description_guard():
    assert classify_category("Solo Raid Season 10") == "solo_raid"
    assert classify_category("联盟突袭 第45期") == "union_raid"
    assert classify_category("Special Arena") == "special_arena"
    assert classify_category("SSR Guilty", tag="special recruit") == "recruit"
    assert classify_category("COIN RUSH", activity_kind="double drop") == "double_reward"
    assert classify_category("Version Update") == "update"
    assert classify_category("September Mission Pass") == "pass"
    assert classify_category("Rewards", description="updated rewards are available") == "event"


def test_explicit_title_taxonomy_wins_over_wrong_supporting_fields():
    assert classify_explicit_title("Limited Costume: Viper - Toxic Rabbit")[0] == "limited_costume"
    assert classify_category(
        "Limited Costume: Viper - Toxic Rabbit",
        tag="coop",
        activity_kind="coordinated operation",
    ) == "limited_costume"
    assert classify_category("Costume Gacha: Sugar - Killer Rabbit", tag="recruit") == "costume_gacha"
    assert classify_category("Mini Game: THREE COMPANY RUMBLE", tag="coop") == "mini_game"
    assert classify_category("September Mission Pass", tag="coop") == "pass"
    assert classify_category("SSR Guilty: Mighty Bunny", tag="coop") == "recruit"
    assert classify_category("[限时通关] Trail Marker", tag="coop") == "limited_stage"



def test_canonical_event_title_removes_packaging_without_erasing_identity():
    assert canonical_event_title("[活动PASS] LET'S DRINK PASS") == "let s drink pass"
    assert canonical_event_title("LET'S DRINK PASS") == "let s drink pass"
    assert canonical_event_title("Trail Marker Event") == "trail marker"
    assert canonical_event_title("[限时通关] Trail Marker") == "trail marker"
    assert canonical_event_title("SSR Anne: Miracle Fairy") != canonical_event_title("SSR Mica: Snow Buddy")
    assert canonical_event_title("Limited Costume: Alice - Sweet Home") != canonical_event_title(
        "Limited Costume: Mary - Medical Rabbit"
    )
    assert canonical_event_title("Simulation Room Overclock Mode Season 10") != canonical_event_title(
        "Simulation Room Overclock Mode Season 11"
    )


def test_canonical_event_title_keeps_bracketed_wrapper_variants_equal():
    assert canonical_event_title("[活动] Mission Pass Foo") == canonical_event_title(
        "Mission Pass Foo"
    )
    assert canonical_event_title("[招募] SSR Anne: Miracle Fairy") == canonical_event_title(
        "SSR Anne: Miracle Fairy"
    )
    assert canonical_event_title("[时装] Limited Costume: Alice - Sweet Home") == canonical_event_title(
        "Limited Costume: Alice - Sweet Home"
    )



def test_relevance_tiers_and_relative_ordering():
    core = _event("gk:core", "Solo Raid Season 10", "solo_raid")
    supporting = _event("gk:event", "Trail Marker Event", "event")
    meta = _event(
        "gk:meta",
        "Character Package",
        "event",
        metadata={"description": "New character packages will be available after maintenance."},
    )

    core_rel = score_display_relevance(core)
    supporting_rel = score_display_relevance(supporting)
    meta_rel = score_display_relevance(meta)
    assert core_rel.tier == DisplayTier.CORE
    assert core_rel.score > supporting_rel.score > meta_rel.score
    assert "descriptive_package:-20" in meta_rel.reasons



def test_merge_datasets_does_not_reduce_simultaneous_different_events(tmp_path):
    service = ScheduleService(tmp_path, visual_cache=False)
    service._source_datasets = {
        "gamekee": [_event("gk:alice", "Special Recruit Alice", "recruit")],
        "official": [
            _event(
                "official:rapi",
                "Special Recruit Rapi",
                "recruit",
                primary_source="official",
                sources=["official"],
            )
        ],
    }

    merged = service._merge_datasets()

    # PR-6B G5-calendar-a3：按事件 ID 单遍聚合，不同 ID 的同时段活动绝不合并；
    # 跨源身份计数诊断已随模糊去重删除。
    assert len(merged) == 2



def test_canonical_dataset_is_lossless_while_feed_can_deprioritize_meta(tmp_path):
    service = ScheduleService(tmp_path, visual_cache=False)
    events = []
    for index in range(10):
        category = "solo_raid" if index == 0 else "maintenance" if index == 9 else "event"
        if index == 9:
            events.append(
                _event(
                    f"gk:{index}",
                    f"Event {index}",
                    category,
                    banner_url="",
                    start_precision="UNKNOWN",
                    end_precision="UNKNOWN",
                )
            )
        else:
            events.append(_event(f"gk:{index}", f"Event {index}", category))
    service._source_datasets = {"gamekee": events}
    service._merge_datasets()
    service._sync_internal_stores(service._base_events)
    service._has_snapshot = True

    assert len(service.list_canonical()) == 10
    assert service.quality_diagnostics["canonical_total"] == 10
    assert service.quality_diagnostics["display_selected"] == 10
    assert service.quality_diagnostics["display_deprioritized"] >= 1
    feed = service.list_window(14, now=START)
    assert len(feed) == 10
    assert feed[0].display_tier == DisplayTier.CORE.value


