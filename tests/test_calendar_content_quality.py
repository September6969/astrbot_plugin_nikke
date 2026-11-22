# SPDX-License-Identifier: GPL-3.0-or-later
"""Calendar Content Quality v1 的离线行为测试。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from astrbot_plugin_nikke.features.calendar.canonical_models import CanonicalEvent
from astrbot_plugin_nikke.features.calendar.content_quality import (
    DisplayTier,
    IdentityDecision,
    canonical_identity_match,
    classify_explicit_title,
    classify_category,
    canonical_event_title,
    get_display_relevance,
    normalize_title,
    score_display_relevance,
    score_identity,
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


def test_title_normalization_keeps_season_and_numbers():
    normalized = normalize_title("[NEW] 单人突袭 第10期 Deadline")
    assert "solo_raid" in normalized
    assert "season" in normalized
    assert "10" in normalized
    assert "new" not in normalized
    assert "deadline" not in normalized


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


def test_canonical_identity_matches_packaging_variants_without_relaxing_gate():
    left = _event(
        "gk:7828",
        "[活动PASS] LET'S DRINK PASS",
        "pass",
        detail_url="https://www.gamekee.com/nikke/721020.html",
    )
    right = _event(
        "official:pass",
        "LET'S DRINK PASS",
        "event",
        primary_source="official",
        sources=["official"],
        detail_url="https://official.example/lets-drink-pass",
    )

    assert score_identity(left, right).decision != IdentityDecision.MATCH
    result = canonical_identity_match(left, right)
    assert result is not None
    assert result.decision == IdentityDecision.MATCH
    assert "canonical_title_exact:+100" in result.reasons


def test_explicit_identity_conflict_blocks_same_window_detail_reuse():
    alice = _event(
        "gk:alice",
        "SSR Anne: Miracle Fairy",
        "recruit",
        detail_url="https://example.test/shared-detail",
    )
    mica = _event(
        "official:mica",
        "SSR Mica: Snow Buddy",
        "recruit",
        primary_source="official",
        sources=["official"],
        detail_url="https://example.test/shared-detail",
    )

    result = score_identity(alice, mica)

    assert result.decision == IdentityDecision.DISTINCT
    assert "explicit_identity_conflict:-100" in result.reasons


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


def test_identity_match_ambiguous_and_distinct():
    left = _event("gk:1", "协同作战", "coop")
    right = _event(
        "official:1",
        "Coordinated Operation Notice",
        "coop",
        primary_source="official",
        sources=["official"],
        start_at=START + timedelta(minutes=5),
        end_at=START + timedelta(days=2),
    )
    assert score_identity(left, right).decision == IdentityDecision.MATCH

    ambiguous_left = _event("gk:2", "活动", "event", start_at=None, end_at=None)
    ambiguous_right = _event("official:2", "活动", "event", start_at=None, end_at=None, primary_source="official", sources=["official"])
    assert score_identity(ambiguous_left, ambiguous_right).decision == IdentityDecision.AMBIGUOUS

    distinct_left = _event("gk:3", "Solo Raid Season 9", "solo_raid", cycle_id="season_9")
    distinct_right = _event("official:3", "Solo Raid Season 10", "solo_raid", cycle_id="season_10", primary_source="official", sources=["official"])
    assert score_identity(distinct_left, distinct_right).decision == IdentityDecision.DISTINCT


def test_identity_gate_keeps_different_named_same_window_events_distinct():
    alice = _event(
        "gk:alice",
        "Special Recruit Alice",
        "recruit",
        start_at=START,
        end_at=START + timedelta(days=2),
    )
    rapi = _event(
        "official:rapi",
        "Special Recruit Rapi",
        "recruit",
        primary_source="official",
        sources=["official"],
        start_at=START,
        end_at=START + timedelta(days=2),
    )

    result = score_identity(alice, rapi)

    assert result.decision != IdentityDecision.MATCH
    assert "strong_identity_gate:missing" in result.reasons


def test_identity_gate_accepts_similar_bilingual_title_with_exact_window():
    left = _event(
        "gk:alice",
        "Special Recruit Alice",
        "recruit",
        start_at=START,
        end_at=START + timedelta(days=2),
    )
    right = _event(
        "official:alice",
        "特殊招募 Alice 公告",
        "recruit",
        primary_source="official",
        sources=["official"],
        start_at=START + timedelta(minutes=5),
        end_at=START + timedelta(days=2),
    )

    result = score_identity(left, right)

    assert result.decision == IdentityDecision.MATCH
    assert "strong_title_time" in result.reasons


def test_identity_gate_accepts_exact_cycle_even_when_titles_are_rewritten():
    left = _event("gk:season-9", "Solo Raid Season 9", "solo_raid", cycle_id="season_9")
    right = _event(
        "official:season-9",
        "Season 9 battle notice",
        "solo_raid",
        cycle_id="season_9",
        primary_source="official",
        sources=["official"],
    )

    result = score_identity(left, right)

    assert result.decision == IdentityDecision.MATCH
    assert "cycle_exact:+45" in result.reasons


def test_identity_gate_accepts_exact_detail_reference():
    left = _event("gk:1", "Alice recruit", "recruit", detail_url="https://example.test/activity/1")
    right = _event(
        "official:1",
        "Character notice",
        "event",
        detail_url="https://example.test/activity/1",
        primary_source="official",
        sources=["official"],
        start_at=None,
        end_at=None,
    )

    result = score_identity(left, right)

    assert result.decision == IdentityDecision.MATCH
    assert "detail_reference:+50" in result.reasons


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

    assert len(merged) == 2
    assert service.quality_diagnostics["identity_matches"] == 0


def test_merge_datasets_uses_canonical_title_evidence_for_packaging_variants(tmp_path):
    service = ScheduleService(tmp_path, visual_cache=False)
    left = _event(
        "gk:7828",
        "[活动PASS] LET'S DRINK PASS",
        "pass",
        detail_url="https://www.gamekee.com/nikke/721020.html",
    )
    right = _event(
        "official:pass",
        "LET'S DRINK PASS",
        "event",
        primary_source="official",
        sources=["official"],
        detail_url="https://official.example/lets-drink-pass",
    )
    service._source_datasets = {"gamekee": [left], "official": [right]}

    merged = service._merge_datasets()

    assert len(merged) == 1
    assert service.quality_diagnostics["identity_matches"] == 1
    assert service.quality_diagnostics["canonical_title_matches"] == 1


def test_merge_datasets_reconciles_exact_business_title_with_meta_category(tmp_path):
    service = ScheduleService(tmp_path, visual_cache=False)
    business = _event(
        "gk:lets-drink-pass",
        "【活动PASS】LET'S DRINK PASS",
        "pass",
        detail_url="https://www.gamekee.com/nikke/721020.html",
    )
    package = _event(
        "official:lets-drink-pass",
        "LET'S DRINK PASS",
        "package",
        primary_source="official",
        sources=["official"],
        detail_url="https://official.example/lets-drink-pass",
    )
    service._source_datasets = {"gamekee": [business], "official": [package]}

    merged = list(service._merge_datasets().values())

    assert len(merged) == 1
    assert merged[0].event_type == "pass"
    reasons = merged[0].metadata["identity_match"]["reasons"]
    assert "canonical_title_exact_meta_reconciled" in reasons


def test_merge_datasets_accepts_exact_title_long_interval_high_overlap(tmp_path):
    service = ScheduleService(tmp_path, visual_cache=False)
    utc8 = timezone(timedelta(hours=8))
    gamekee = _event(
        "gk:trail-marker",
        "Trail Marker Event",
        "limited_stage",
        start_at=datetime(2026, 8, 13, 3, 0, tzinfo=utc8),
        end_at=datetime(2026, 10, 8, 3, 59, tzinfo=utc8),
    )
    official = _event(
        "official:trail-marker",
        "【限时通关】Trail Marker",
        "limited_stage",
        primary_source="official",
        sources=["official"],
        start_at=datetime(2026, 8, 13, 0, 0, tzinfo=utc8),
        end_at=datetime(2026, 10, 8, 4, 59, tzinfo=utc8),
    )
    service._source_datasets = {"gamekee": [gamekee], "official": [official]}

    merged = list(service._merge_datasets().values())

    assert len(merged) == 1
    reasons = merged[0].metadata["identity_match"]["reasons"]
    assert "canonical_title_exact_high_overlap" in reasons


def test_schedule_service_deduplicates_live_regression_pairs_before_pagination(tmp_path):
    utc8 = timezone(timedelta(hours=8))
    service = ScheduleService(tmp_path, visual_cache=False)
    service._source_datasets = {
        "gamekee": [
            _event("gk:drink", "【活动PASS】LET'S DRINK PASS", "pass"),
            _event(
                "gk:trail",
                "Trail Marker Event",
                "limited_stage",
                start_at=datetime(2026, 8, 13, 3, 0, tzinfo=utc8),
                end_at=datetime(2026, 10, 8, 3, 59, tzinfo=utc8),
            ),
        ],
        "official": [
            _event(
                "official:drink",
                "LET'S DRINK PASS",
                "package",
                primary_source="official",
                sources=["official"],
            ),
            _event(
                "official:trail",
                "【限时通关】Trail Marker",
                "limited_stage",
                primary_source="official",
                sources=["official"],
                start_at=datetime(2026, 8, 13, 0, 0, tzinfo=utc8),
                end_at=datetime(2026, 10, 8, 4, 59, tzinfo=utc8),
            ),
        ],
    }

    canonical = list(service._merge_datasets().values())
    titles = [canonical_event_title(event.title) for event in canonical]

    assert titles.count("let s drink pass") == 1
    assert titles.count("trail marker") == 1
    assert next(event for event in canonical if canonical_event_title(event.title) == "let s drink pass").event_type == "pass"
    assert service.quality_diagnostics["identity_matches"] == 2


def test_canonical_title_high_overlap_does_not_merge_distinct_periods_or_short_events():
    first_period = _event(
        "gk:trail-marker-aug",
        "Trail Marker",
        "limited_stage",
        start_at=datetime(2026, 8, 13, tzinfo=UTC),
        end_at=datetime(2026, 10, 8, tzinfo=UTC),
    )
    later_period = _event(
        "official:trail-marker-nov",
        "【限时通关】Trail Marker",
        "limited_stage",
        primary_source="official",
        sources=["official"],
        start_at=datetime(2026, 11, 1, tzinfo=UTC),
        end_at=datetime(2027, 1, 1, tzinfo=UTC),
    )
    short_left = _event(
        "gk:short",
        "Trail Marker",
        "limited_stage",
        start_at=START,
        end_at=START + timedelta(hours=2),
    )
    short_right = _event(
        "official:short",
        "Trail Marker Event",
        "limited_stage",
        primary_source="official",
        sources=["official"],
        start_at=START + timedelta(minutes=90),
        end_at=START + timedelta(hours=3, minutes=30),
    )

    assert canonical_identity_match(first_period, later_period) is None
    assert canonical_identity_match(short_left, short_right) is None


def test_canonical_meta_reconciliation_preserves_specific_business_categories(tmp_path):
    cases = (
        ("Mission Pass Foo", "pass", "package"),
        ("Trail Marker", "limited_stage", "announcement"),
        ("Alice", "recruit", "package"),
    )
    for index, (title, business_type, meta_type) in enumerate(cases):
        service = ScheduleService(tmp_path / str(index), visual_cache=False)
        business = _event(f"gk:{index}", title, business_type)
        meta = _event(
            f"official:{index}",
            title,
            meta_type,
            primary_source="official",
            sources=["official"],
        )
        service._source_datasets = {"gamekee": [business], "official": [meta]}

        merged = list(service._merge_datasets().values())

        assert len(merged) == 1
        assert merged[0].event_type == business_type


def test_canonical_exact_title_does_not_reconcile_different_business_families():
    recruit = _event("gk:alice", "Alice", "recruit")
    costume = _event(
        "official:alice-costume",
        "Alice",
        "limited_costume",
        primary_source="official",
        sources=["official"],
    )

    assert canonical_identity_match(recruit, costume) is None


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


