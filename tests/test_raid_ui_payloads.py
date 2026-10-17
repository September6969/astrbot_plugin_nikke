"""联盟突袭 T2I 概览字段的安全展示回归。"""

from jinja2 import Environment

from astrbot_plugin_nikke.features.raid.models import (
    BossStatus,
    PreviousSeasonSummary,
    RaidBossData,
    RaidResponseCoverage,
    RaidState,
    UnionRaidOverviewData,
)
from astrbot_plugin_nikke.features.raid.participants import RaidRankingData
from astrbot_plugin_nikke.features.raid.experience import analyze, paginate
from astrbot_plugin_nikke.tests.test_raid_participants import attack
from astrbot_plugin_nikke.ui.payloads.raid_overview import UnionOverviewT2IPayloadBuilder
from astrbot_plugin_nikke.ui.payloads.raid_member import UnionMemberT2IPayloadBuilder
from astrbot_plugin_nikke.ui.payloads.raid_records import UnionRecordsT2IPayloadBuilder
from astrbot_plugin_nikke.ui.t2i_templates import T2ITemplateLoader


def overview_data():
    return UnionRaidOverviewData(
        guild_name="样例联盟",
        difficulty=2,
        level=7,
        total_progress=None,
        total_current_hp=None,
        total_max_hp=None,
        bosses=[
            RaidBossData("101", "已击破 Boss", 0, 1000, 0.0, 1.0, BossStatus.DEFEATED),
            RaidBossData("102", "血量未知 Boss", None, 1000, None, None, BossStatus.UNKNOWN),
        ],
        season_end="2026-10-30T00:00:00+08:00",
        fetched_at="2026-10-16 12:00",
        plugin_version="test",
        response_coverage=RaidResponseCoverage.UNKNOWN_COVERAGE,
        partial_boss_records=True,
        raid_state=RaidState.ACTIVE,
        current_season_name="第 7 季",
    )


def render(payload):
    template = T2ITemplateLoader().load("union_overview")
    return Environment(autoescape=True).from_string(template).render(**payload)


def test_boss_slots_distinguish_unknown_hp_and_explicit_placeholders():
    data = overview_data()
    payload = UnionOverviewT2IPayloadBuilder().build(data)
    payload["bosses"][0]["name"] = "Boss 记录未返回"
    payload["bosses"][2]["name"] = "手工改名的占位槽"

    assert len(payload["bosses"]) == 5
    assert [item["placeholder"] for item in payload["bosses"]] == [False, False, True, True, True]
    assert payload["bosses"][0]["status_label"] == "已击破"
    assert payload["bosses"][1]["status_label"] == "Boss 状态待确认"
    assert payload["bosses"][1]["hp"] == "Unknown / 1,000"
    assert payload["bosses"][1]["percent"] == "Unknown"
    assert payload["bosses"][1]["bar"] is None
    assert all(item["bar"] is None for item in payload["bosses"][2:])

    html = render(payload)
    assert html.count('class="boss boss-placeholder"') == 3
    assert "手工改名的占位槽" in html
    assert html.count("Boss 记录未返回") == 3
    assert "Boss 状态待确认" in html
    assert "剩余生命比例待确认" in html
    assert "width:None%" not in html
    assert "难度 2" in html and "层级 7" in html


def test_previous_season_summary_requires_historical_ranking_data():
    data = overview_data()
    data.raid_state = RaidState.OFFSEASON
    data.previous_season = PreviousSeasonSummary(
        season_id="1000007",
        season_number=7,
        start_at="2026-10-01T00:00:00+08:00",
        end_at="2026-10-10T00:00:00+08:00",
    )
    data.ranking = RaidRankingData([], scope="CURRENT_RESPONSE", total_damage=0, total_records=0)
    builder = UnionOverviewT2IPayloadBuilder()

    assert builder.build(data)["previous_season_summary"] is None

    data.ranking = RaidRankingData(
        [], scope="LAST_SEASON", season_id="1000007", total_damage=12345,
        total_records=3, incomplete=True, excluded_records=1,
    )
    payload = builder.build(data)
    summary = payload["previous_season_summary"]
    assert summary["season_name"] == "第 7 季"
    assert summary["records"] == 3
    assert summary["damage"] == "12,345"
    assert summary["partial"] is True
    assert summary["excluded"] == 1
    html = render(payload)
    assert "有效返回记录" in html
    assert "仅显示可核实的部分返回记录" in html
    assert "返回记录伤害" in html


def test_boss_hp_track_distinguishes_zero_full_and_low_hp_without_portraits():
    data = overview_data()
    data.bosses = [
        RaidBossData("201", "零 HP", 0, 1000, 0.0, 1.0, BossStatus.DEFEATED),
        RaidBossData("202", "满 HP", 1000, 1000, 1.0, 0.0, BossStatus.UNKNOWN),
        RaidBossData("203", "低 HP", 1, 1000, 0.001, 0.999, BossStatus.UNKNOWN),
    ]
    payload = UnionOverviewT2IPayloadBuilder().build(data)
    html = render(payload)

    assert [boss["bar"] for boss in payload["bosses"][:3]] == [0.0, 100.0, 0.1]
    assert [boss["status_label"] for boss in payload["bosses"][:3]] == ["已击破", "Boss 状态待确认", "Boss 状态待确认"]
    assert html.count('class="bar"') == 3
    assert html.count('<span class="badge">Boss</span>') == 3
    assert "width:0.0%" in html and "width:100.0%" in html and "width:0.1%" in html


def test_offseason_without_qualified_history_states_that_summary_is_unavailable():
    data = overview_data()
    data.raid_state = RaidState.OFFSEASON
    data.previous_season = None
    data.ranking = RaidRankingData([], scope="CURRENT_RESPONSE", total_damage=123, total_records=1)
    html = render(UnionOverviewT2IPayloadBuilder().build(data))

    assert "暂无历史摘要" in html
    assert "有效返回记录" not in html
    assert "返回记录伤害" not in html


def test_ranking_share_uses_full_range_denominator_and_keeps_ties_across_pages():
    rows = [attack(f"member-{index}", 1000 - index * 10) for index in range(20)]
    rows[0]["nickname"] = "这是一个用于检验排行列宽的中文长昵称样例"
    rows[15]["total_damage"] = rows[14]["total_damage"]
    data = analyze({"participate_data": rows}, season_id="1000007")
    assert [item.rank for item in data.participants][14:16] == [15, 15]

    builder = UnionRecordsT2IPayloadBuilder()
    first = builder.build(paginate(data, 1))
    second = builder.build(paginate(data, 2))
    assert first["total_damage"] == second["total_damage"] == f"{data.total_damage:,}"
    assert first["rows"][-1]["rank"] == second["rows"][0]["rank"] == "15"
    assert first["rows"][-1]["share_ratio"] == data.participants[14].total_damage / data.total_damage
    assert second["rows"][0]["share_ratio"] == data.participants[15].total_damage / data.total_damage


def test_zero_total_has_no_share_bar_but_zero_damage_with_positive_total_is_zero_percent():
    builder = UnionRecordsT2IPayloadBuilder()
    all_zero = analyze({"participate_data": [attack("zero-a", 0)]})
    zero_payload = builder.build(all_zero)
    assert zero_payload["rows"][0]["share"] == "—"
    assert zero_payload["rows"][0]["share_ratio"] is None
    assert zero_payload["rows"][0]["share_bar"] is None

    mixed = analyze({"participate_data": [attack("zero-b", 0), attack("positive", 100)]})
    mixed_payload = builder.build(mixed)
    assert mixed_payload["rows"][0]["share"] == "100.0%"
    assert mixed_payload["rows"][1]["share"] == "0.0%"
    assert mixed_payload["rows"][1]["share_ratio"] == 0
    assert mixed_payload["rows"][1]["share_bar"] == 0


def test_ranking_template_keeps_exact_damage_next_to_the_share_bar():
    huge = 1_234_567_890_123_456_789
    data = analyze({"participate_data": [attack("huge", huge), attack("zero", 0)]})
    payload = UnionRecordsT2IPayloadBuilder().build(data)
    template = T2ITemplateLoader().load("union_records")
    html = Environment(autoescape=True).from_string(template).render(**payload)

    assert f"{huge:,}" in html
    assert html.count('class="share-track"') == 2
    assert '<td><td class="share-cell">' not in html
    assert "width:100.0%" in html
    assert "width:0.0%" in html


def test_overview_top_five_share_keeps_full_ranking_scope_denominator():
    ranking = analyze({"participate_data": [attack(f"member-{value}", value) for value in range(1, 7)]})
    data = overview_data()
    data.ranking = ranking
    payload = UnionOverviewT2IPayloadBuilder().build(data)
    rows = payload["ranking"]["rows"]
    html = render(payload)

    assert len(rows) == 5
    assert rows[0]["share_ratio"] == 6 / 21
    assert payload["ranking"]["total_damage"] == "21"
    assert "width:28.57%" in html
    assert html.count('class="share-track"') == 5


def test_member_report_distinguishes_true_false_and_unknown_final_hit():
    class EmptyResolver:
        @staticmethod
        def encode(_source):
            return None

    known_tail = attack("member", 300)
    known_tail["is_final_hit"] = True
    known_tail["day"] = 0
    known_non_tail = attack("member", 200)
    known_non_tail["is_final_hit"] = False
    known_non_tail["day"] = 1
    unknown_tail = attack("member", 100)
    unknown_tail["is_final_hit"] = "unknown"
    unknown_tail["day"] = "unknown"
    unknown_tail["squad"] = []
    data = paginate(analyze({"participate_data": [known_tail, known_non_tail, unknown_tail]}, member_id="member"), 1, member=True)
    payload = UnionMemberT2IPayloadBuilder(None, EmptyResolver()).build(data)
    rows = payload["participants"][0]["rows"]
    template = T2ITemplateLoader().load("union_member")
    html = Environment(autoescape=True).from_string(template).render(**payload)

    assert [row["final_hit"] for row in rows] == [True, False, None]
    assert [row["final_hit_label"] for row in rows] == [" · 尾刀", "", " · 尾刀状态待确认"]
    assert rows[2]["day"] == "未知"
    assert rows[2]["damage"] == "100"
    assert "记录 01 · 尾刀</p>" in html
    assert "记录 02 · 尾刀" not in html
    assert "记录 03 · 尾刀状态待确认" in html
    assert "游戏日 未知" in html


def test_member_payload_keeps_five_slots_long_identity_and_missing_portrait():
    class EmptyResolver:
        @staticmethod
        def encode(_source):
            return None

    row = attack("member", 500)
    row["nickname"] = "用于验证五槽位与长昵称显示边界的中文成员名称"
    row["squad"][0]["tid"] = "231301"
    row["squad"][1]["tid"] = "999999"
    data = paginate(analyze({"participate_data": [row]}, member_id="member"), 1, member=True)
    payload = UnionMemberT2IPayloadBuilder(None, EmptyResolver()).build(data)
    members = payload["participants"][0]["rows"][0]["members"]

    assert [member["slot"] for member in members] == ["1", "2", "3", "4", "5"]
    assert members[0]["name"] == "普丽瓦蒂：不友善的女仆"
    assert members[1]["name"] == "身份未确认"
    assert all(member["portrait_data_uri"] is None for member in members)
    assert [member["level"] for member in members] == ["LV.100"] * 5
