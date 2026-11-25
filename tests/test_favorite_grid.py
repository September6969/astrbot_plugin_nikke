# SPDX-License-Identifier: GPL-3.0-or-later
"""29 本命九宫格：顺序、重复识别、PNG 解码与排行覆盖。"""

from __future__ import annotations

import io
from datetime import datetime, timezone

import pytest
from PIL import Image

from astrbot_plugin_nikke.features.character.identity import CharacterDirectoryResolver
from astrbot_plugin_nikke.features.favorite_grid.grid import (
    FavoriteGridError,
    FavoriteRanking,
    resolve_nine,
    split_nine,
)
from astrbot_plugin_nikke.ui.payloads.favorite_grid import FavoriteGridPayloadBuilder
from astrbot_plugin_nikke.ui.renderers.favorite_grid_png import compose_grid_png, write_grid_png
from astrbot_plugin_nikke.ui.t2i_templates import T2ITemplateLoader
from jinja2 import Environment, StrictUndefined


class MemoryStore:
    def __init__(self) -> None:
        self.values: dict[str, object] = {}

    def get_setting(self, key, default=None):
        return self.values.get(key, default)

    def set_setting(self, key, value):
        self.values[key] = value


ROWS = tuple(
    {
        "name_code": 9000 + index,
        "resource_id": 700 + index,
        "name_zh_cn": f"测试{index}号",
        "name_zh_tw": f"測試{index}號",
        "name_en": f"Test Unit {index}",
        "burst": ("Step1", "Step2", "Step3")[index % 3],
        "element": "Fire",
    }
    for index in range(1, 13)
)


def resolver() -> CharacterDirectoryResolver:
    return CharacterDirectoryResolver()


def test_nine_names_keep_input_order() -> None:
    text = "测试3号,测试1号,测试2号,测试4号,测试5号,测试6号,测试7号,测试8号,测试9号"
    cells = resolve_nine(text, ROWS, resolver())
    assert [cell.name for cell in cells] == [
        "测试3号", "测试1号", "测试2号", "测试4号", "测试5号",
        "测试6号", "测试7号", "测试8号", "测试9号",
    ]
    assert [cell.index for cell in cells] == list(range(1, 10))
    assert len({cell.name_code for cell in cells}) == 9


def test_duplicate_and_wrong_count_are_rejected() -> None:
    duplicate = "测试1号,测试1号,测试2号,测试3号,测试4号,测试5号,测试6号,测试7号,测试8号"
    with pytest.raises(FavoriteGridError, match="重复妮姬"):
        resolve_nine(duplicate, ROWS, resolver())

    with pytest.raises(FavoriteGridError, match="需要九个"):
        resolve_nine("测试1号,测试2号", ROWS, resolver())
    assert len(split_nine("测试1号 测试2号 测试3号")) == 3


def test_ambiguous_or_unknown_names_are_distinguished() -> None:
    rows = (*ROWS, {"name_code": 9500, "name_zh_cn": "测试1号", "name_zh_tw": "測試1號"})
    with pytest.raises(FavoriteGridError, match="多个匹配"):
        resolve_nine(
            "测试1号,测试2号,测试3号,测试4号,测试5号,测试6号,测试7号,测试8号,测试9号",
            rows,
            resolver(),
        )
    with pytest.raises(FavoriteGridError, match="未找到"):
        resolve_nine(
            "不存在,测试2号,测试3号,测试4号,测试5号,测试6号,测试7号,测试8号,测试9号",
            ROWS,
            resolver(),
        )


def test_png_is_a_decodable_3x3_grid_with_stable_placeholders() -> None:
    cells = resolve_nine(
        "测试1号,测试2号,测试3号,测试4号,测试5号,测试6号,测试7号,测试8号,测试9号",
        ROWS,
        resolver(),
    )
    portrait = io.BytesIO()
    Image.new("RGB", (64, 64), (200, 40, 40)).save(portrait, format="PNG")

    first = compose_grid_png([cell.to_dict() for cell in cells], size=900)
    second = compose_grid_png([cell.to_dict() for cell in cells], size=900)
    assert first == second, "同一输入必须得到稳定版面"

    with Image.open(io.BytesIO(first)) as image:
        assert image.format == "PNG"
        assert image.size == (900, 900)
        # 九个格子中心位置各不相同，且都能解码。
        centers = [
            image.getpixel((150 + 300 * column, 150 + 300 * row))
            for row in range(3)
            for column in range(3)
        ]
        assert len(set(centers)) >= 2

    with_portrait = compose_grid_png(
        [cell.to_dict() for cell in cells],
        size=600,
        portraits={cells[0].name_code: portrait.getvalue()},
    )
    with Image.open(io.BytesIO(with_portrait)) as image:
        assert image.size == (600, 600)
        # 第一格使用立绘（红色），与占位色块不同。
        red, green, blue = image.getpixel((100, 100))
        assert red > green and red > blue


def test_ranking_overwrites_old_votes_and_aggregates_users() -> None:
    store = MemoryStore()
    clock = lambda: datetime(2026, 9, 21, tzinfo=timezone.utc)
    ranking = FavoriteRanking(store, clock=clock)

    first = resolve_nine(
        "测试1号,测试2号,测试3号,测试4号,测试5号,测试6号,测试7号,测试8号,测试9号",
        ROWS,
        resolver(),
    )
    second = resolve_nine(
        "测试2号,测试1号,测试3号,测试4号,测试5号,测试6号,测试7号,测试8号,测试9号",
        ROWS,
        resolver(),
    )
    ranking.vote("user-a", first)
    ranking.vote("user-b", second)
    top = ranking.ranking(limit=3)
    assert [entry.name for entry in top] == ["测试1号", "测试2号", "测试3号"]
    assert [entry.votes for entry in top] == [2, 2, 2]
    # 同票按 name_code 稳定排序。
    assert [entry.name_code for entry in top] == ["9001", "9002", "9003"]

    replacement = resolve_nine(
        "测试10号,测试1号,测试3号,测试4号,测试5号,测试6号,测试7号,测试8号,测试9号",
        ROWS,
        resolver(),
    )
    ranking.vote("user-a", replacement)
    after = {entry.name: entry.votes for entry in ranking.ranking(limit=20)}
    assert after["测试1号"] == 2  # user-a 仍保留测试1号
    assert after["测试2号"] == 1  # 旧投票被覆盖后只剩 user-b
    assert after["测试10号"] == 1
    assert ranking.my_vote("user-a")[0].name == "测试10号"

    ranking.clear("user-a")
    assert ranking.my_vote("user-a") == ()
    remaining = {entry.name: entry.votes for entry in ranking.ranking(limit=20)}
    assert "测试10号" not in remaining


def test_payload_and_template_keep_input_order_and_placeholders() -> None:
    cells = resolve_nine(
        "测试9号,测试8号,测试7号,测试6号,测试5号,测试4号,测试3号,测试2号,测试1号",
        ROWS,
        resolver(),
    )
    payload = FavoriteGridPayloadBuilder(assets=None).build(cells)
    assert [row["name"] for row in payload["cells"]] == [cell.name for cell in cells]
    markup = Environment(undefined=StrictUndefined).from_string(
        T2ITemplateLoader().load("favorite_grid")
    ).render(**payload)
    positions = [markup.index(f"P{index}") for index in range(1, 10)]
    assert positions == sorted(positions)
    assert "placeholder" in markup
    assert "本命九宫格" in markup
    assert payload["canvas"] == {"width": 1080, "height": 1080}


def test_write_grid_png_reuses_identical_content(tmp_path=None) -> None:
    from pathlib import Path

    cells = resolve_nine(
        "测试1号,测试2号,测试3号,测试4号,测试5号,测试6号,测试7号,测试8号,测试9号",
        ROWS,
        resolver(),
    )
    directory = Path("output") / ".favorite-grid-test"
    first = write_grid_png(directory, [cell.to_dict() for cell in cells])
    second = write_grid_png(directory, [cell.to_dict() for cell in cells])
    assert first == second
    with Image.open(first) as image:
        assert image.size == (1080, 1080)


def test_ranking_uses_single_key_read_without_n_plus_one_scans() -> None:
    class CountingStore(MemoryStore):
        def __init__(self) -> None:
            super().__init__()
            self.reads = 0

        def get_setting(self, key, default=None):
            self.reads += 1
            return super().get_setting(key, default)

    store = CountingStore()
    clock = lambda: datetime(2026, 9, 21, tzinfo=timezone.utc)
    ranking = FavoriteRanking(store, clock=clock)
    base = [
        resolve_nine(
            "测试1号,测试2号,测试3号,测试4号,测试5号,测试6号,测试7号,测试8号,测试9号",
            ROWS,
            resolver(),
        ),
        resolve_nine(
            "测试10号,测试2号,测试3号,测试4号,测试5号,测试6号,测试7号,测试8号,测试9号",
            ROWS,
            resolver(),
        ),
    ]
    for i in range(5):
        ranking.vote(f"user-{i}", base[i % 2])
    store.reads = 0
    top = ranking.ranking(limit=10)
    assert top[0].name == "测试2号" and top[0].votes == 5
    # 榜单读取只需一次 COUNTS_KEY 读取，禁止按 5 个投票用户发 N+1 次请求。
    assert store.reads == 1


@pytest.mark.asyncio
async def test_favorite_grid_uses_unified_t2i_without_pillow_fallback(tmp_path) -> None:
    from types import SimpleNamespace
    from astrbot_plugin_nikke.adapters.astrbot.command_presentation import AstrBotCommandPresentation

    cells = resolve_nine(
        "测试1号,测试2号,测试3号,测试4号,测试5号,测试6号,测试7号,测试8号,测试9号",
        ROWS,
        resolver(),
    )

    async def failing_html_render(*_args, **_kwargs):
        raise RuntimeError("t2i unavailable")

    presentation = AstrBotCommandPresentation(
        services=SimpleNamespace(asset_manager=None, data_dir=tmp_path),
        html_render=lambda: failing_html_render,
        context=SimpleNamespace(),
    )
    # 失败时返回 None（由命令层回退文本），不再切到 Pillow 本地生图。
    assert await presentation.render_favorite_grid(cells) is None
