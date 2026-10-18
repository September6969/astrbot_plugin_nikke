"""校验公开资料与日常汇总的文本化退役，以及其余 T2I 页面的回退语义。"""

import asyncio
import importlib.util
import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from astrbot_plugin_nikke.adapters.astrbot.command_presentation import (
    AstrBotCommandPresentation,
)
from astrbot_plugin_nikke.application.commands.character import CharacterCommandHandler
from astrbot_plugin_nikke.application.commands.contracts import (
    CommandContext,
    CommandResult,
    ImageReply,
    TextReply,
)
from astrbot_plugin_nikke.application.commands.daily import DailyCommandHandler
from astrbot_plugin_nikke.features.character.application import (
    CharacterInfoData,
    CharacterRosterData,
)
from astrbot_plugin_nikke.features.daily.models import DailyTaskResult, DailyTaskStatus
from astrbot_plugin_nikke.features.daily.presentation import format_daily_summary_text
from astrbot_plugin_nikke.ui.renderers.t2i import T2IRenderer
from astrbot_plugin_nikke.ui.t2i_templates import T2ITemplateLoader

REPO_ROOT = Path(__file__).resolve().parents[1]
TEXT_BUDGET = 3500
RETIRED_PAGES = ("character_info", "daily_summary")
RETIRED_PAYLOAD_MODULES = (
    "astrbot_plugin_nikke.ui.payloads.character_info",
    "astrbot_plugin_nikke.ui.payloads.daily_summary",
)
CONTINUATION = re.compile(r"【第 \d+ 条账号结果续页 \d+/\d+】\n")


def _summary_body(chunks):
    """剥离分页标题与续页标记，按原顺序还原结构化文本正文。"""
    parts = []
    for chunk in chunks:
        body = chunk.split("\n", 1)[1] if "\n" in chunk else ""
        marker = CONTINUATION.match(body)
        if marker:
            body = body[marker.end() :]
        parts.append(body)
    return "".join(parts)


def test_public_character_info_returns_structured_text_without_image_render():
    data = CharacterInfoData(
        "测试妮姬",
        "妮姬基础资料",
        (("稀有度", "SSR"), ("属性", "火力")),
        resource_id="95",
    )
    application = SimpleNamespace(info=Mock(return_value=data))
    handler = CharacterCommandHandler(
        application=application,
        directory=lambda: [],
        render_roster=Mock(),
        render_card=Mock(),
        invalidate_cookie=Mock(),
    )

    result = asyncio.run(
        handler.handle(
            CommandContext(
                actor_id="synthetic-user",
                parameters={"operation": "info", "name": "测试妮姬"},
            )
        )
    )

    assert [type(message) for message in result.messages] == [TextReply]
    assert result.messages[0].text == "妮姬基础资料\n测试妮姬\n稀有度：SSR\n属性：火力"
    application.info.assert_called_once_with("测试妮姬", [])
    assert not hasattr(handler, "_render_info")


def test_character_info_handler_rejects_retired_image_render_port():
    with pytest.raises(TypeError):
        CharacterCommandHandler(
            application=SimpleNamespace(),
            directory=lambda: [],
            render_roster=Mock(),
            render_card=Mock(),
            render_info=Mock(),
            invalidate_cookie=Mock(),
        )


def test_daily_handler_rejects_retired_image_render_port():
    with pytest.raises(TypeError):
        DailyCommandHandler(
            account_reader=SimpleNamespace(),
            store=SimpleNamespace(),
            runner=SimpleNamespace(),
            client=SimpleNamespace(),
            config={},
            render_summary=Mock(),
            send_summary=AsyncMock(),
        )


def test_presentation_drops_retired_image_renderers():
    presentation = AstrBotCommandPresentation(
        services=SimpleNamespace(asset_manager=SimpleNamespace()),
        html_render=lambda: None,
        context=SimpleNamespace(),
    )

    assert not hasattr(presentation, "render_character_info")
    assert not hasattr(presentation, "render_daily_summary")


def test_presentation_format_daily_summary_uses_the_shared_text_formatter():
    results = [DailyTaskResult("合成账号", DailyTaskStatus.SUCCESS, "签到成功")]

    formatted = AstrBotCommandPresentation.format_daily_summary(
        results, scope="管理员手动执行"
    )

    assert formatted == format_daily_summary_text(results, scope="管理员手动执行")


def test_retired_payload_modules_and_templates_are_removed():
    for module in RETIRED_PAYLOAD_MODULES:
        assert importlib.util.find_spec(module) is None
    for name in ("character_info.html", "daily_summary.html"):
        assert not (REPO_ROOT / "templates" / "t2i" / name).exists()

    loader = T2ITemplateLoader()
    for page in RETIRED_PAGES:
        with pytest.raises(ValueError):
            loader.load(page)


def test_t2i_renderer_retires_character_info_and_daily_summary_pages():
    renderer = T2IRenderer(html_render=AsyncMock(), assets=SimpleNamespace())

    for page, data in (("character_info", object()), ("daily_summary", [])):
        with pytest.raises(ValueError):
            asyncio.run(renderer.render_view(page, data))


def test_roster_render_failure_returns_top_twenty_fields_from_same_dto():
    data = CharacterRosterData(
        "合成指挥官",
        (
            {
                "name_code": "0001",
                "lv": 260,
                "combat": 100000,
                "skill1_lv": 10,
                "skill2_lv": 9,
                "ulti_skill_lv": 8,
                "grade": 3,
                "core": 1,
            },
        ),
        {"0001": "阿妮斯"},
    )
    application = SimpleNamespace(roster=AsyncMock(return_value=data))
    render_roster = AsyncMock(return_value=None)
    handler = CharacterCommandHandler(
        application=application,
        directory=lambda: [],
        render_roster=render_roster,
        render_card=AsyncMock(),
        invalidate_cookie=Mock(),
    )

    result = asyncio.run(handler.handle(CommandContext(actor_id="synthetic-user")))

    assert len(result.messages) == 1
    assert isinstance(result.messages[0], TextReply)
    assert "阿妮斯" in result.messages[0].text
    assert "等级 260" in result.messages[0].text
    assert "战力 100,000" in result.messages[0].text
    assert "技能 10/9/8" in result.messages[0].text
    application.roster.assert_awaited_once()
    render_roster.assert_awaited_once_with(data)


def test_character_card_render_failure_returns_same_card_dto_as_text():
    card = SimpleNamespace(
        name_code="0001",
        name_cn="阿妮斯",
        name_en="Anis",
        rarity="SSR",
        element="火力",
        weapon="火箭发射器",
        burst="III",
        corporation="极乐净土",
        level=260,
        combat=123456,
        skill1_level=10,
        skill2_level=9,
        burst_skill_level=8,
        grade=3,
        core=1,
        bond_level=30,
        equipment={},
        favorite_item=None,
        cube=None,
        option_totals=[],
        fetched_at="2026-10-17 12:00",
    )
    application = SimpleNamespace(build_card=AsyncMock(return_value=SimpleNamespace(card=card)))
    render_card = AsyncMock(side_effect=TimeoutError("渲染超时"))
    handler = CharacterCommandHandler(
        application=application,
        directory=lambda: [],
        render_roster=AsyncMock(),
        render_card=render_card,
        invalidate_cookie=Mock(),
    )

    result = asyncio.run(
        handler.handle(
            CommandContext(
                actor_id="synthetic-user",
                parameters={"operation": "character", "name": "阿妮斯"},
            )
        )
    )

    assert isinstance(result.messages[0], TextReply)
    assert "妮姬练度 · 阿妮斯" in result.messages[0].text
    assert "战力：123,456" in result.messages[0].text
    application.build_card.assert_awaited_once()
    render_card.assert_awaited_once_with(card)


def test_legacy_pillow_config_still_attempts_t2i_without_old_renderer():
    presentation = AstrBotCommandPresentation(
        services=SimpleNamespace(asset_manager=SimpleNamespace()),
        html_render=lambda: None,
        context=SimpleNamespace(),
    )
    renderer = SimpleNamespace(render_view=AsyncMock(return_value="t2i.png"))
    presentation._t2i_renderer = renderer

    path = asyncio.run(presentation.try_t2i("profile", object()))

    assert path == "t2i.png"
    renderer.render_view.assert_awaited_once()


def test_daily_summary_text_preserves_order_and_all_41_and_47_results():
    for count in (41, 47):
        results = []
        for index in range(count):
            status = DailyTaskStatus.SUCCESS
            detail = f"签到成功-{index + 1:02d}"
            if index == 40:
                status = DailyTaskStatus.UNKNOWN_AFTER_ACTION
                detail = "第 41 个账号结果待确认，不得重试"
            if index == 46:
                status = DailyTaskStatus.FAILED
                detail = "第 47 个账号签到失败，具体原因保留"
            results.append(DailyTaskResult(f"合成账号{index + 1:02d}", status, detail))

        chunks = format_daily_summary_text(results, scope="管理员手动执行")

        assert all(len(chunk) <= TEXT_BUDGET for chunk in chunks)
        text = "\n".join(chunks)
        for result in results:
            assert text.count(result.account_name) == 1
            assert result.detail in text
        positions = [text.index(result.account_name) for result in results]
        assert positions == sorted(positions)
        assert "合成账号41｜结果待确认" in text
        assert "第 41 个账号结果待确认，不得重试" in text
        if count == 47:
            assert "合成账号47｜失败" in text
            assert "第 47 个账号签到失败，具体原因保留" in text


def test_daily_summary_text_chunks_respect_character_budget_and_keep_rewards():
    results = [
        DailyTaskResult(
            account_name=f"长文本账号{index + 1:02d}",
            status=(
                DailyTaskStatus.UNKNOWN_AFTER_ACTION
                if index == 40
                else DailyTaskStatus.FAILED
                if index == 46
                else DailyTaskStatus.SUCCESS
            ),
            detail=f"账号结果详情{index + 1:02d}，状态字段必须完整保留。",
            items=tuple(
                {
                    "name": f"账号{index + 1:02d}奖励{reward_index + 1}",
                    "status": "failed" if index == 46 and reward_index == 4 else "success",
                    "detail": f"奖励领取状态{reward_index + 1}，失败与成功不能混淆。" * 2,
                }
                for reward_index in range(8)
            ),
        )
        for index in range(47)
    ]

    chunks = format_daily_summary_text(results, scope="自动任务完整执行摘要")
    text = "\n".join(chunks)

    assert all(len(chunk) <= TEXT_BUDGET for chunk in chunks)
    assert all(text.count(result.account_name) == 1 for result in results)
    assert all(result.detail in text for result in results)
    assert "账号41奖励8：领取成功" in text
    assert "账号47奖励5：领取失败" in text
    assert "长文本账号41｜结果待确认" in text
    assert "长文本账号47｜失败" in text


def test_daily_summary_text_splits_one_oversized_result_with_explicit_continuations():
    detail = "单账号详情字段连续跨消息，字符必须原样保留。" * 1200
    reward_detail = "奖励状态详情不省略。" * 300
    result = DailyTaskResult(
        "超长详情账号",
        DailyTaskStatus.UNKNOWN_AFTER_ACTION,
        detail,
        items=(
            {"name": "周常奖励", "status": "failed", "detail": reward_detail},
        ),
    )

    chunks = format_daily_summary_text([result], scope="超长详情合成回退")

    assert len(chunks) > 1
    assert all(len(chunk) <= TEXT_BUDGET for chunk in chunks)
    assert all("账号结果续页" in chunk for chunk in chunks)
    assert _summary_body(chunks) == (
        f"超长详情账号｜结果待确认\n  详情：{detail}\n"
        f"  周常奖励：领取失败；{reward_detail}"
    )


def test_daily_summary_text_keeps_wide_latin_and_many_rewards_within_budget():
    detail = ("WARNING " + "W" * 32 + " ") * 100
    rewards = tuple(
        {"name": f"短奖励{index}", "status": "success", "detail": "已领取"}
        for index in range(1, 6)
    )
    english_detail = (
        "The daily task request timed out; its final status remains unconfirmed. "
    ) * 80
    results = [
        DailyTaskResult(
            "宽拉丁字符合成账号",
            DailyTaskStatus.UNKNOWN_AFTER_ACTION,
            detail,
            items=rewards,
        ),
        DailyTaskResult("English timeout account", DailyTaskStatus.FAILED, english_detail),
    ]

    chunks = format_daily_summary_text(results, scope="合成回退")

    assert all(len(chunk) <= TEXT_BUDGET for chunk in chunks)
    body = _summary_body(chunks)
    assert detail in body
    assert english_detail in body
    for reward in rewards:
        assert f"{reward['name']}：领取成功；已领取" in body


def test_manual_daily_summary_returns_text_without_repeating_the_batch():
    result = DailyTaskResult(
        "合成账号", DailyTaskStatus.UNKNOWN_AFTER_ACTION, "签到结果待确认；未自动重发"
    )
    runner = SimpleNamespace(run_all_daily=AsyncMock(return_value=[result]))
    format_summary = Mock(return_value=("合成账号｜结果待确认｜签到结果待确认；未自动重发",))
    handler = DailyCommandHandler(
        account_reader=SimpleNamespace(),
        store=SimpleNamespace(),
        runner=runner,
        client=SimpleNamespace(),
        config={},
        format_summary=format_summary,
        send_summary=AsyncMock(),
    )

    response = asyncio.run(handler.render_manual_summary())

    assert isinstance(response, CommandResult)
    assert response.messages == (
        TextReply("合成账号｜结果待确认｜签到结果待确认；未自动重发"),
    )
    runner.run_all_daily.assert_awaited_once()
    format_summary.assert_called_once_with([result], scope="管理员手动执行")


def test_manual_daily_summary_default_formatter_is_text_only():
    result = DailyTaskResult("合成账号", DailyTaskStatus.SUCCESS, "签到成功")
    runner = SimpleNamespace(run_all_daily=AsyncMock(return_value=[result]))
    handler = DailyCommandHandler(
        account_reader=SimpleNamespace(),
        store=SimpleNamespace(),
        runner=runner,
        client=SimpleNamespace(),
        config={},
        send_summary=AsyncMock(),
    )

    response = asyncio.run(handler.render_manual_summary())

    assert all(isinstance(message, TextReply) for message in response.messages)
    assert all(not isinstance(message, ImageReply) for message in response.messages)
    assert "合成账号" in response.messages[0].text
    runner.run_all_daily.assert_awaited_once()


def test_automatic_daily_summary_keeps_recipient_filter_and_sends_text_once():
    signin_result = DailyTaskResult("合成账号", DailyTaskStatus.SUCCESS, "签到成功")
    community_result = DailyTaskResult(
        "社区账号",
        DailyTaskStatus.SUCCESS,
        "签到：已领取",
        items=({"name": "签到", "status": "success", "detail": "已领取"},),
    )
    stored = [signin_result.to_storage(), community_result.to_storage()]

    def get_setting(key, default=None):
        if key == "summary_group_umo":
            return "synthetic-group"
        if key == "daily_results:2026-10-17:automatic":
            return stored
        return default

    store = SimpleNamespace(get_setting=Mock(side_effect=get_setting))
    runner = SimpleNamespace(run_all_daily=AsyncMock())
    send_summary = AsyncMock()
    handler = DailyCommandHandler(
        account_reader=store,
        store=store,
        runner=runner,
        client=SimpleNamespace(),
        config={},
        send_summary=send_summary,
    )

    asyncio.run(handler.send_automatic_summary("2026-10-17"))

    runner.run_all_daily.assert_not_awaited()
    send_summary.assert_awaited_once()
    recipient, replies = send_summary.await_args.args
    assert recipient == "synthetic-group"
    assert replies and all(isinstance(reply, TextReply) for reply in replies)
    combined = "\n".join(reply.text for reply in replies)
    assert "合成账号" in combined
    assert "社区账号" not in combined


def test_automatic_daily_summary_sends_unknown_result_text_once():
    pending = DailyTaskResult(
        "待确认账号", DailyTaskStatus.UNKNOWN_AFTER_ACTION, "签到已执行，结果待确认；未自动重发"
    )

    def get_setting(key, default=None):
        if key == "summary_group_umo":
            return "synthetic-group"
        if key == "daily_results:2026-10-17:automatic":
            return [pending.to_storage()]
        return default

    store = SimpleNamespace(get_setting=Mock(side_effect=get_setting))
    runner = SimpleNamespace(run_all_daily=AsyncMock())
    send_summary = AsyncMock()
    handler = DailyCommandHandler(
        account_reader=store,
        store=store,
        runner=runner,
        client=SimpleNamespace(),
        config={},
        send_summary=send_summary,
    )

    asyncio.run(handler.send_automatic_summary("2026-10-17"))

    runner.run_all_daily.assert_not_awaited()
    send_summary.assert_awaited_once()
    recipient, replies = send_summary.await_args.args
    assert recipient == "synthetic-group"
    assert any("结果待确认" in reply.text for reply in replies)
    assert any("未自动重发" in reply.text for reply in replies)


def test_automatic_daily_summary_text_keeps_all_47_cached_results_and_recipient():
    results = []
    for index in range(47):
        status = DailyTaskStatus.SUCCESS
        detail = f"自动汇总详情{index + 1:02d}"
        if index == 40:
            status = DailyTaskStatus.UNKNOWN_AFTER_ACTION
            detail = "第 41 个结果待确认；不得重复提交"
        elif index == 46:
            status = DailyTaskStatus.FAILED
            detail = "第 47 个结果失败；保留具体错误"
        results.append(DailyTaskResult(f"自动账号{index + 1:02d}", status, detail))

    stored = [result.to_storage() for result in results]

    def get_setting(key, default=None):
        if key == "summary_group_umo":
            return "synthetic-group"
        if key == "daily_results:2026-10-17:automatic":
            return stored
        return default

    store = SimpleNamespace(get_setting=Mock(side_effect=get_setting))
    runner = SimpleNamespace(run_all_daily=AsyncMock())
    send_summary = AsyncMock()
    handler = DailyCommandHandler(
        account_reader=store,
        store=store,
        runner=runner,
        client=SimpleNamespace(),
        config={},
        send_summary=send_summary,
    )

    asyncio.run(handler.send_automatic_summary("2026-10-17"))

    runner.run_all_daily.assert_not_awaited()
    send_summary.assert_awaited_once()
    recipient, replies = send_summary.await_args.args
    assert recipient == "synthetic-group"
    assert all(isinstance(reply, TextReply) for reply in replies)
    assert all(len(reply.text) <= TEXT_BUDGET for reply in replies)
    combined = "\n".join(reply.text for reply in replies)
    assert all(combined.count(result.account_name) == 1 for result in results)
    assert "第 41 个结果待确认；不得重复提交" in combined
    assert "第 47 个结果失败；保留具体错误" in combined
