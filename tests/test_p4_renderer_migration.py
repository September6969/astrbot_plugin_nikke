import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from PIL import Image

from astrbot_plugin_nikke.features.daily.models import DailyTaskResult, DailyTaskStatus
from astrbot_plugin_nikke.features.character.application import (
    CharacterInfoData,
    CharacterRosterData,
)
from astrbot_plugin_nikke.adapters.astrbot.command_presentation import AstrBotCommandPresentation
from astrbot_plugin_nikke.application.commands.character import CharacterCommandHandler
from astrbot_plugin_nikke.application.commands.contracts import (
    CommandContext,
    CommandResult,
    ImageReply,
    TextReply,
)
from astrbot_plugin_nikke.application.commands.daily import DailyCommandHandler
from astrbot_plugin_nikke.ui.payloads.character_info import CharacterInfoT2IPayloadBuilder
from astrbot_plugin_nikke.ui.renderers.t2i import T2IRenderer
from astrbot_plugin_nikke.ui.t2i_templates import T2ITemplateLoader


def test_public_character_info_payload_uses_only_verified_public_icon():
    resolved = SimpleNamespace(resource_id=95)
    image = Image.new("RGBA", (32, 32), (240, 120, 40, 255))
    assets = SimpleNamespace(
        character_master=SimpleNamespace(resolve_resource_id=Mock(return_value=resolved)),
        get_character_asset=Mock(return_value=SimpleNamespace(image=image, exact_match=True)),
    )
    data = CharacterInfoData(
        "测试妮姬",
        "妮姬基础资料",
        (("稀有度", "SSR"), ("属性", "火力")),
        resource_id="95",
    )

    payload = CharacterInfoT2IPayloadBuilder(assets).build(data)

    assert payload["name"] == "测试妮姬"
    assert payload["rows"] == [{"label": "稀有度", "value": "SSR"}, {"label": "属性", "value": "火力"}]
    assert payload["portrait_data_uri"].startswith("data:image/png;base64,")
    assets.get_character_asset.assert_called_once_with(95, kind="icon")
    assert "private" not in str(payload).casefold()


def test_public_character_info_unknown_identity_uses_placeholder_without_asset_lookup():
    assets = SimpleNamespace(
        character_master=SimpleNamespace(resolve_resource_id=Mock(return_value=None)),
        get_character_asset=Mock(),
    )
    data = CharacterInfoData("未知妮姬", "妮姬基础资料", (("属性", "未知"),), resource_id="999999")

    payload = CharacterInfoT2IPayloadBuilder(assets).build(data)

    assert payload["portrait_data_uri"] is None
    assert payload["portrait_label"] == "头像待核验"
    assets.get_character_asset.assert_not_called()


def test_public_character_info_render_failure_returns_same_dto_as_text():
    data = CharacterInfoData(
        "测试妮姬",
        "妮姬基础资料",
        (("稀有度", "SSR"), ("属性", "火力")),
        resource_id="95",
    )
    application = SimpleNamespace(info=Mock(return_value=data))
    render_info = Mock(side_effect=TimeoutError("渲染超时"))
    handler = CharacterCommandHandler(
        application=application,
        directory=lambda: [],
        render_roster=Mock(),
        render_card=Mock(),
        render_info=render_info,
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

    assert len(result.messages) == 1
    assert isinstance(result.messages[0], TextReply)
    assert result.messages[0].text == "妮姬基础资料\n测试妮姬\n稀有度：SSR\n属性：火力"
    application.info.assert_called_once_with("测试妮姬", [])
    render_info.assert_called_once_with(data)


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
        render_info=AsyncMock(),
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
        render_info=AsyncMock(),
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


def test_daily_summary_pages_preserve_order_status_codes_and_total_for_40_results():
    from astrbot_plugin_nikke.ui.payloads.daily_summary import DailySummaryT2IPayloadBuilder

    statuses = list(DailyTaskStatus)
    results = [
        DailyTaskResult(
            account_name=f"合成账号{i:02d}",
            status=statuses[i % len(statuses)],
            detail="结果待确认" if statuses[i % len(statuses)] is DailyTaskStatus.UNKNOWN_AFTER_ACTION else f"详情{i:02d}",
            items=({"name": "测试奖励", "state": "unknown", "detail": "状态未验证"},) if i == 0 else (),
        )
        for i in range(40)
    ]

    payload = DailySummaryT2IPayloadBuilder().build(results, scope="管理员手动执行")

    assert payload["total_count"] == 40
    assert len(payload["pages"]) == 4
    assert [row["account_name"] for page in payload["pages"] for row in page["rows"]] == [
        result.account_name for result in results
    ]
    assert all(len(page["rows"]) <= 10 for page in payload["pages"])
    assert payload["pages"][0]["range_label"] == "第 1–10 / 共 40 条"
    unknown = next(
        row
        for page in payload["pages"]
        for row in page["rows"]
        if row["status_code"] == DailyTaskStatus.UNKNOWN_AFTER_ACTION.value
    )
    assert unknown["status_label"] == "结果待确认"
    assert unknown["detail"] == "结果待确认"
    projected_reward = payload["pages"][0]["rows"][0]["rewards"][0]
    assert projected_reward["name"] == "测试奖励"
    assert projected_reward["state_label"] == "状态未验证"
    assert projected_reward["detail"] == "状态未验证"
    assert projected_reward["text"] == "测试奖励：状态未验证（状态未验证）"


def test_daily_summary_preserves_all_results_and_text_for_41_and_47_accounts():
    from astrbot_plugin_nikke.ui.payloads.daily_summary import DailySummaryT2IPayloadBuilder

    builder = DailySummaryT2IPayloadBuilder()
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
            results.append(
                DailyTaskResult(f"合成账号{index + 1:02d}", status, detail)
            )

        payload = builder.build(results)
        projected = [row for page in payload["pages"] for row in page["rows"]]
        assert payload["total_count"] == count
        assert payload["shown_count"] == count
        assert payload["omitted_count"] == 0
        assert [row["account_name"] for row in projected] == [
            result.account_name for result in results
        ]
        assert [row["detail"] for row in projected] == [result.detail for result in results]
        assert all(len(page["rows"]) <= builder.PAGE_SIZE for page in payload["pages"])
        assert payload["pages"][-1]["range_label"] == (
            f"第 {count - (count - 1) % builder.PAGE_SIZE}–{count} / 共 {count} 条"
        )
        render_calls = []

        async def fake_html_render(_html, page_payload, *, options):
            render_calls.append(page_payload)
            return f"synthetic-{len(render_calls)}.png"

        renderer = T2IRenderer(html_render=fake_html_render, assets=SimpleNamespace())
        image_paths = asyncio.run(renderer.render_view("daily_summary", results))
        rendered_rows = [row for call in render_calls for row in call["rows"]]
        assert image_paths == [f"synthetic-{index + 1}.png" for index in range(len(payload["pages"]))]
        assert [row["account_name"] for row in rendered_rows] == [
            result.account_name for result in results
        ]
        text_chunks = builder.format_text(results)
        all_text = "\n".join(text_chunks)
        assert all(all_text.count(result.account_name) == 1 for result in results)
        assert all(result.detail in all_text for result in results)
        assert "第 41 个账号结果待确认，不得重试" in all_text
        if count == 47:
            assert "第 47 个账号签到失败，具体原因保留" in all_text
            assert "合成账号47" in all_text


def test_daily_summary_long_content_fits_declared_canvas_and_keeps_all_fields():
    from jinja2 import Environment
    from playwright.async_api import async_playwright

    from astrbot_plugin_nikke.ui.payloads.daily_summary import DailySummaryT2IPayloadBuilder

    statuses = list(DailyTaskStatus)
    long_detail = "签到结果待确认，暂不重复提交。" * 8
    oversized_detail = "单账号超长详情必须分页保留；\n包含换行的下一行也必须保留。\n" * 1200
    results = []
    for index in range(10):
        items = tuple(
            {
                "name": f"奖励项目{reward_index + 1}",
                "status": ("success", "pending", "failed", "unknown", "already_done")[reward_index],
                "detail": f"奖励状态详情{reward_index + 1}，不得丢失。" * 3,
            }
            for reward_index in range(5)
        )
        results.append(
            DailyTaskResult(
                account_name=(
                    "一个用于验证超长昵称换行的合成账号名称" * 3
                    if index == 0
                    else f"合成账号{index + 1:02d}"
                ),
                status=statuses[index % len(statuses)],
                detail=oversized_detail if index == 8 else long_detail,
                items=items,
            )
        )

    payload = DailySummaryT2IPayloadBuilder().build(results)
    loader = T2ITemplateLoader()
    environment = Environment(autoescape=True)

    async def inspect_pages():
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            checks = []
            try:
                page = await browser.new_page()
                for page_payload in payload["pages"]:
                    html = environment.from_string(
                        loader.load("daily_summary")
                    ).render(**page_payload)
                    await page.set_content(html, wait_until="load")
                    await page.evaluate("document.fonts.ready")
                    checks.append(
                        await page.evaluate("""() => {
                          const root = document.querySelector('.daily');
                          const footer = document.querySelector('footer');
                          const rect = element => {
                            const box = element.getBoundingClientRect();
                            return {top: box.top, bottom: box.bottom, left: box.left,
                                    right: box.right, height: box.height};
                          };
                          const rootBox = rect(root);
                          const rows = [...document.querySelectorAll('.row')].map(row => ({
                            box: rect(row),
                            resultIndex: Number(row.dataset.resultIndex),
                            fragmentIndex: Number(row.dataset.fragmentIndex),
                            fragmentCount: Number(row.dataset.fragmentCount),
                            accountName: row.querySelector('.account').textContent,
                            status: row.dataset.status,
                            badgeHeight: rect(row.querySelector('.badge')).height,
                            detail: row.querySelector('.detail').textContent,
                            rewardCount: row.querySelectorAll('.reward').length,
                            texts: [...row.querySelectorAll('.account, .badge, .detail, .reward')]
                              .map(rect)
                          }));
                          const overlaps = [];
                          for (let index = 1; index < rows.length; index++) {
                            if (rows[index - 1].box.bottom > rows[index].box.top + 1)
                              overlaps.push(index - 1);
                          }
                          return {
                            root: rootBox,
                            rootClientHeight: root.clientHeight,
                            rootScrollHeight: root.scrollHeight,
                            documentHeight: document.documentElement.scrollHeight,
                            footer: rect(footer),
                            rows,
                            overlaps
                          };
                        }""")
                    )
            finally:
                await browser.close()
            return checks

    checks = asyncio.run(inspect_pages())
    assert checks
    assert all(check["root"]["height"] == page["canvas"]["height"] for check, page in zip(checks, payload["pages"]))
    assert all(check["rootScrollHeight"] <= check["rootClientHeight"] for check in checks)
    assert all(check["footer"]["bottom"] <= check["root"]["bottom"] for check in checks)
    assert all(check["documentHeight"] <= page["canvas"]["height"] for check, page in zip(checks, payload["pages"]))
    assert all(
        text["top"] >= row["box"]["top"] - 1 and text["bottom"] <= row["box"]["bottom"] + 1
        for check in checks
        for row in check["rows"]
        for text in row["texts"]
    )
    assert all(not check["overlaps"] for check in checks)
    assert all(430 <= page["canvas"]["height"] <= DailySummaryT2IPayloadBuilder.MAX_PAGE_HEIGHT for page in payload["pages"])
    assert all(
        row["badgeHeight"] <= 52
        for check in checks
        for row in check["rows"]
    )

    payload_rows = [row for page in payload["pages"] for row in page["rows"]]
    assert {row["status_code"] for row in payload_rows} == {
        status.value for status in DailyTaskStatus
    }
    reward_labels = {
        "success": "领取成功",
        "pending": "尚未达成",
        "failed": "领取失败",
        "unknown": "状态未验证",
        "already_done": "已领取",
    }
    for index, result in enumerate(results, start=1):
        fragments = sorted(
            (row for row in payload_rows if row["result_index"] == index),
            key=lambda row: row["fragment_index"],
        )
        assert fragments
        assert "".join(row["detail"] for row in fragments) == result.detail
        assert [row["account_name"] for row in fragments] == [result.account_name] * len(fragments)
        for reward_index, reward in enumerate(result.items, start=1):
            reward_parts = sorted(
                (
                    item
                    for row in fragments
                    for item in row["rewards"]
                    if item["reward_index"] == reward_index
                ),
                key=lambda item: item["part_index"],
            )
            expected_text = f"{reward['name']}：{reward_labels[reward['status']]}（{reward['detail']}）"
            assert "".join(item["text"] for item in reward_parts) == expected_text


def test_daily_summary_text_chunks_respect_character_budget_and_keep_rewards():
    from astrbot_plugin_nikke.ui.payloads.daily_summary import DailySummaryT2IPayloadBuilder

    builder = DailySummaryT2IPayloadBuilder()
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

    chunks = builder.format_text(results, scope="自动任务完整执行摘要")
    text = "\n".join(chunks)

    assert all(len(chunk) <= builder.MAX_TEXT_CHARS for chunk in chunks)
    assert all(text.count(result.account_name) == 1 for result in results)
    assert all(result.detail in text for result in results)
    assert "账号41奖励8：领取成功" in text
    assert "账号47奖励5：领取失败" in text
    assert "长文本账号41｜结果待确认" in text
    assert "长文本账号47｜失败" in text


def test_daily_summary_text_splits_one_oversized_result_with_explicit_continuations():
    import re

    from astrbot_plugin_nikke.ui.payloads.daily_summary import DailySummaryT2IPayloadBuilder

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
    chunks = DailySummaryT2IPayloadBuilder().format_text([result], scope="超长详情合成回退")

    assert len(chunks) > 1
    assert all(len(chunk) <= DailySummaryT2IPayloadBuilder.MAX_TEXT_CHARS for chunk in chunks)
    assert all("账号结果续页" in chunk for chunk in chunks)
    rebuilt = []
    for chunk in chunks:
        body = chunk.split("\n", 1)[1]
        continuation = re.match(r"【第 1 条账号结果续页 \d+/\d+】\n", body)
        assert continuation
        rebuilt.append(body[continuation.end() :])
    assert "".join(rebuilt) == (
        f"超长详情账号｜结果待确认\n  详情：{detail}\n"
        f"  周常奖励：领取失败；{reward_detail}"
    )


def test_p4_templates_are_allowlisted_self_contained_and_escape_user_text():
    loader = T2ITemplateLoader()
    attack = "<script>alert(1)</script>"

    for page, payload in (
        (
            "character_info",
            {
                "canvas": {"width": 1080, "height": 680},
                "name": attack,
                "title": "妮姬基础资料",
                "portrait_data_uri": None,
                "portrait_label": "头像待核验",
                "rows": [{"label": "属性", "value": attack}],
                "footer": "静态角色目录",
            },
        ),
        (
            "daily_summary",
            {
                "canvas": {"width": 1200, "height": 520},
                "scope": "管理员手动执行",
                "range_label": "第 1–1 / 共 1 条",
                "total_count": 1,
                "shown_count": 1,
                "omitted_count": 0,
                "status_counts": [{"label": "结果待确认", "count": 1}],
                "rows": [
                    {
                        "account_name": attack,
                        "status_label": "结果待确认",
                        "status_tone": "warning",
                        "detail": attack,
                        "rewards": [],
                    }
                ],
                "footer": "本页内容仅为执行结果摘要",
            },
        ),
    ):
        html = loader.load(page)
        assert "<script>" not in html
        assert "https://" not in html and "file://" not in html
        from jinja2 import Environment

        rendered = Environment(autoescape=True).from_string(html).render(**payload)
        assert "&lt;script&gt;" in rendered
        assert attack not in rendered


def test_daily_summary_t2i_renders_each_page_from_the_same_results():
    calls = []

    async def html_render(html, payload, *, options):
        calls.append((html, payload, options))
        return f"page-{len(calls)}.png"

    renderer = T2IRenderer(html_render=html_render, assets=SimpleNamespace())
    results = [
        DailyTaskResult(f"合成账号{i:02d}", DailyTaskStatus.SUCCESS, f"详情{i:02d}")
        for i in range(12)
    ]

    paths = asyncio.run(renderer.render_view("daily_summary", results, scope="合成测试"))

    assert paths == ["page-1.png", "page-2.png"]
    assert [len(call[1]["rows"]) for call in calls] == [10, 2]
    assert all(call[1]["scope"] == "合成测试" for call in calls)
    assert [call[1]["range_label"] for call in calls] == [
        "第 1–10 / 共 12 条",
        "第 11–12 / 共 12 条",
    ]


def test_manual_daily_summary_falls_back_to_text_without_repeating_the_batch():
    result = DailyTaskResult(
        "合成账号", DailyTaskStatus.UNKNOWN_AFTER_ACTION, "签到结果待确认；未自动重发"
    )
    runner = SimpleNamespace(run_all_daily=AsyncMock(return_value=[result]))
    render_summary = AsyncMock(side_effect=TimeoutError("渲染超时"))
    format_summary = Mock(return_value=("合成账号｜结果待确认｜签到结果待确认；未自动重发",))
    handler = DailyCommandHandler(
        account_reader=SimpleNamespace(),
        store=SimpleNamespace(),
        runner=runner,
        client=SimpleNamespace(),
        config={},
        render_summary=render_summary,
        format_summary=format_summary,
        send_summary=AsyncMock(),
    )

    response = asyncio.run(handler.render_manual_summary())

    assert isinstance(response, CommandResult)
    assert response.messages == (
        TextReply("合成账号｜结果待确认｜签到结果待确认；未自动重发"),
    )
    runner.run_all_daily.assert_awaited_once()
    render_summary.assert_awaited_once_with([result], scope="管理员手动执行")
    format_summary.assert_called_once_with([result], scope="管理员手动执行")


def test_manual_daily_summary_propagates_render_cancellation_without_retry_or_fallback():
    result = DailyTaskResult("合成账号", DailyTaskStatus.SUCCESS, "签到成功")
    runner = SimpleNamespace(run_all_daily=AsyncMock(return_value=[result]))
    render_summary = AsyncMock(side_effect=asyncio.CancelledError())
    format_summary = Mock()
    handler = DailyCommandHandler(
        account_reader=SimpleNamespace(),
        store=SimpleNamespace(),
        runner=runner,
        client=SimpleNamespace(),
        config={},
        render_summary=render_summary,
        format_summary=format_summary,
        send_summary=AsyncMock(),
    )

    async def run_summary():
        return await handler.render_manual_summary()

    try:
        asyncio.run(run_summary())
    except asyncio.CancelledError:
        pass
    else:
        raise AssertionError("取消必须从日常汇总渲染路径继续传播")

    runner.run_all_daily.assert_awaited_once()
    render_summary.assert_awaited_once_with([result], scope="管理员手动执行")
    format_summary.assert_not_called()


def test_automatic_daily_summary_keeps_recipient_filter_and_sends_all_pages_once():
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
    render_summary = AsyncMock(return_value=["page-1.png", "page-2.png"])
    send_summary = AsyncMock()
    handler = DailyCommandHandler(
        account_reader=store,
        store=store,
        runner=runner,
        client=SimpleNamespace(),
        config={},
        render_summary=render_summary,
        send_summary=send_summary,
        format_summary=Mock(),
    )

    asyncio.run(handler.send_automatic_summary("2026-10-17"))

    runner.run_all_daily.assert_not_awaited()
    render_summary.assert_awaited_once_with([signin_result], scope="每日自动任务汇总")
    send_summary.assert_awaited_once_with(
        "synthetic-group", (ImageReply("page-1.png"), ImageReply("page-2.png"))
    )


def test_automatic_daily_summary_sends_unknown_result_text_once_when_t2i_fails():
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
    render_summary = AsyncMock(return_value=None)
    format_summary = Mock(return_value=("待确认账号｜结果待确认｜未自动重发",))
    send_summary = AsyncMock()
    handler = DailyCommandHandler(
        account_reader=store,
        store=store,
        runner=runner,
        client=SimpleNamespace(),
        config={},
        render_summary=render_summary,
        send_summary=send_summary,
        format_summary=format_summary,
    )

    asyncio.run(handler.send_automatic_summary("2026-10-17"))

    runner.run_all_daily.assert_not_awaited()
    render_summary.assert_awaited_once_with([pending], scope="每日自动任务汇总")
    format_summary.assert_called_once_with([pending], scope="每日自动任务汇总")
    send_summary.assert_awaited_once_with(
        "synthetic-group", (TextReply("待确认账号｜结果待确认｜未自动重发"),)
    )


def test_automatic_daily_summary_text_fallback_keeps_all_47_cached_results_and_recipient():
    from astrbot_plugin_nikke.ui.payloads.daily_summary import DailySummaryT2IPayloadBuilder

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
    render_summary = AsyncMock(return_value=None)
    send_summary = AsyncMock()
    formatter = DailySummaryT2IPayloadBuilder().format_text
    handler = DailyCommandHandler(
        account_reader=store,
        store=store,
        runner=runner,
        client=SimpleNamespace(),
        config={},
        render_summary=render_summary,
        send_summary=send_summary,
        format_summary=formatter,
    )

    asyncio.run(handler.send_automatic_summary("2026-10-17"))

    runner.run_all_daily.assert_not_awaited()
    render_summary.assert_awaited_once_with(results, scope="每日自动任务汇总")
    send_summary.assert_awaited_once()
    recipient, replies = send_summary.await_args.args
    assert recipient == "synthetic-group"
    assert all(isinstance(reply, TextReply) for reply in replies)
    assert all(
        len(reply.text) <= DailySummaryT2IPayloadBuilder.MAX_TEXT_CHARS
        for reply in replies
    )
    combined = "\n".join(reply.text for reply in replies)
    assert all(combined.count(result.account_name) == 1 for result in results)
    assert "第 41 个结果待确认；不得重复提交" in combined
    assert "第 47 个结果失败；保留具体错误" in combined


def test_daily_summary_wide_latin_detail_stays_within_each_declared_canvas():
    from jinja2 import Environment
    from playwright.async_api import async_playwright

    from astrbot_plugin_nikke.ui.payloads.daily_summary import DailySummaryT2IPayloadBuilder

    detail = ("WARNING " + "W" * 32 + " ") * 100
    rewards = tuple(
        {"name": f"短奖励{index}", "status": "success", "detail": "已领取"}
        for index in range(1, 6)
    )
    result = DailyTaskResult(
        "宽拉丁字符合成账号",
        DailyTaskStatus.UNKNOWN_AFTER_ACTION,
        detail,
        items=rewards,
    )
    english_detail = (
        "The daily task request timed out; its final status remains unconfirmed. "
    ) * 80
    english_result = DailyTaskResult(
        "English timeout account",
        DailyTaskStatus.FAILED,
        english_detail,
    )
    builder = DailySummaryT2IPayloadBuilder()
    payload = builder.build([result, english_result])
    loader = T2ITemplateLoader()
    environment = Environment(autoescape=True)

    async def inspect_pages():
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            checks = []
            try:
                page = await browser.new_page()
                for page_payload in payload["pages"]:
                    html = environment.from_string(loader.load("daily_summary")).render(
                        **page_payload
                    )
                    await page.set_content(html, wait_until="load")
                    await page.evaluate("document.fonts.ready")
                    checks.append(
                        await page.evaluate("""() => {
                          const root = document.querySelector('.daily');
                          const footer = document.querySelector('footer');
                          const box = node => {
                            const rect = node.getBoundingClientRect();
                            return {top: rect.top, bottom: rect.bottom, height: rect.height};
                          };
                          const rows = [...document.querySelectorAll('.row')].map(row => ({
                            box: box(row),
                            resultIndex: Number(row.dataset.resultIndex),
                            textBoxes: [...row.querySelectorAll(
                              '.account, .badge, .continuation-label, .detail, .reward'
                            )].map(box),
                            detail: row.querySelector('.detail').textContent,
                            rewards: [...row.querySelectorAll('.reward')].map(node => node.textContent),
                          }));
                          return {
                            root: box(root),
                            rootClientHeight: root.clientHeight,
                            rootScrollHeight: root.scrollHeight,
                            documentHeight: document.documentElement.scrollHeight,
                            footer: box(footer),
                            rows,
                          };
                        }""")
                    )
            finally:
                await browser.close()
            return checks

    checks = asyncio.run(inspect_pages())

    assert len(payload["pages"]) >= 2
    assert all(
        page["canvas"]["height"] <= builder.MAX_PAGE_HEIGHT
        for page in payload["pages"]
    )
    for check, page in zip(checks, payload["pages"]):
        declared_height = page["canvas"]["height"]
        assert check["root"]["height"] == declared_height
        assert check["rootScrollHeight"] <= check["rootClientHeight"]
        assert check["documentHeight"] == declared_height
        assert check["footer"]["bottom"] <= declared_height
        assert all(
            text_box["top"] >= row["box"]["top"] - 1
            and text_box["bottom"] <= row["box"]["bottom"] + 1
            for row in check["rows"]
            for text_box in row["textBoxes"]
        )
        assert all(
            previous["box"]["bottom"] <= current["box"]["top"] + 1
            for previous, current in zip(check["rows"], check["rows"][1:])
        )
    assert sum(check["documentHeight"] for check in checks) <= (
        len(checks) * builder.MAX_PAGE_HEIGHT
    )
    assert sum(check["documentHeight"] for check in checks) == sum(
        page["canvas"]["height"] for page in payload["pages"]
    )
    projected_rows = [row for page in payload["pages"] for row in page["rows"]]
    for index, expected_detail in enumerate((detail, english_detail), start=1):
        assert "".join(
            row["detail"]
            for row in projected_rows
            if row["result_index"] == index
        ) == expected_detail
        assert "".join(
            row["detail"]
            for check in checks
            for row in check["rows"]
            if row["resultIndex"] == index
        ) == expected_detail
    assert [
        reward
        for check in checks
        for row in check["rows"]
        if row["resultIndex"] == 1
        for reward in row["rewards"]
    ] == [f"{item['name']}：领取成功（已领取）" for item in rewards]

    projected_rewards = sorted(
        (item for row in projected_rows for item in row["rewards"]),
        key=lambda item: (item["reward_index"], item["part_index"]),
    )
    assert [item["text"] for item in projected_rewards] == [
        f"{item['name']}：领取成功（已领取）" for item in rewards
    ]
