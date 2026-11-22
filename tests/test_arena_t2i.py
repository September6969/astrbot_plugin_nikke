"""竞技场卡片共享 DTO、可信模板及本地头像回退。"""

from dataclasses import replace

import pytest
from jinja2 import Environment, StrictUndefined

from astrbot_plugin_nikke.application.commands.arena import ArenaCommandHandler
from astrbot_plugin_nikke.application.commands.contracts import CommandContext, ImageReply, TextReply
from astrbot_plugin_nikke.features.arena.models import MatchupEvidence
from astrbot_plugin_nikke.ui.payloads.arena import ArenaT2IPayloadBuilder
from astrbot_plugin_nikke.ui.renderers.t2i import T2IRenderer
from astrbot_plugin_nikke.ui.t2i_templates import T2ITemplateLoader
from astrbot_plugin_nikke.features.arena.optimizer import ThreeTeamOptimizer
from test_arena_core import arena


def test_single_template_contains_all_positions_and_escapes_names(arena):
    team = arena.directory.parse_team("红莲/豺狼/布兰儿/桑迪/特蕾娜")
    analysis = arena.analyzer.analyze(team)
    payload = ArenaT2IPayloadBuilder().build(analysis)
    assert analysis.snapshot_date in payload["source"]
    assert analysis.data_status.version[:7] in payload["source"]
    payload["matches"][0]["team"][0]["name"] = "<script>bad</script>"
    template = T2ITemplateLoader().load("arena_matchup")
    markup = Environment(undefined=StrictUndefined).from_string(template).render(**payload)
    assert "<script>bad</script>" not in markup
    assert "&lt;script&gt;" in markup
    assert markup.count("敌方 P1–P5") == 1
    assert markup.count("我方 P1–P5") == len(payload["matches"])
    assert all("P" + str(index) in markup for index in range(1, 6))
    assert "unknown" not in payload["matches"][0]["speed"]


def test_three_template_uses_one_plan_without_recomputing(arena):
    teams = tuple(arena.directory.parse_team(text) for text in (
        "红莲/豺狼/布兰儿/桑迪/特蕾娜", "诺雅/饼干/爱丽丝/丽塔/普丽瓦蒂",
        "阿妮斯/拉毗/尼恩/露菲/哈兰"))
    plan = ThreeTeamOptimizer(arena.analyzer).solve(teams)
    payload = ArenaT2IPayloadBuilder().build(plan)
    markup = Environment(undefined=StrictUndefined).from_string(T2ITemplateLoader().load("arena_three_teams")).render(**payload)
    assert len(payload["matches"]) == 3
    assert "竞技场三队排阵" in markup
    assert markup.count("敌方 P1–P5") == len(payload["matches"])
    assert "onclick" not in markup


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_second", [False, True])
async def test_long_result_pages_publish_together_or_fall_back(arena, fail_second):
    teams = tuple(arena.directory.parse_team(text) for text in (
        "红莲/豺狼/布兰儿/桑迪/特蕾娜", "诺雅/饼干/爱丽丝/丽塔/普丽瓦蒂",
        "阿妮斯/拉毗/尼恩/露菲/哈兰"))
    plan = ThreeTeamOptimizer(arena.analyzer).solve(teams)
    # AUD-017：分页改用与模板逐项对齐的高度模型（无头像时阵容更矮），
    # 原 22 倍说明在单页 2200px 预算内即可放下，故加长到确实需要分页的长度。
    historical = MatchupEvidence("statistic", "历史对位与站位差异说明" * 40,
                                 arena.analyzer.provenance)
    plan = replace(plan, teams=tuple(replace(item, evidence=(*item.evidence, historical))
                                     for item in plan.teams))
    pages = ArenaT2IPayloadBuilder().pages(plan)
    assert len(pages) > 1
    assert [match["label"] for page in pages for match in page["matches"]] == [
        "第 1 场对位", "第 2 场对位", "第 3 场对位",
    ]
    rendered = []

    async def html_render(_template, payload, *, options):
        assert options["viewport"]["width"] == 1000
        rendered.append(payload["title"])
        return "" if fail_second and len(rendered) == 2 else f"test-{len(rendered)}.png"

    class SavedResult:
        def active(self):
            return True

        def latest(self, _actor):
            return plan

    renderer = T2IRenderer(html_render, assets=None)
    handler = ArenaCommandHandler(arena, enabled=True, web_routes=SavedResult(), render=renderer.render_view)
    result = await handler.handle(CommandContext(
        actor_id="test", is_private_chat=True, parameters={"action": "结果"},
    ))
    if fail_second:
        reply, = result.messages
        assert isinstance(reply, TextReply) and "第 3 场对位" in reply.text
    else:
        assert result.messages == tuple(ImageReply(f"test-{index}.png") for index in range(1, len(pages) + 1))
