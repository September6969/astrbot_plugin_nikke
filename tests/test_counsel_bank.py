# SPDX-License-Identifier: GPL-3.0-or-later
"""07 咨询答案查询：合成题库、别名检索、多结果区分与缺失说明。"""

from __future__ import annotations

from astrbot_plugin_nikke.features.counsel.bank import (
    CounselBank,
    CounselBankError,
    render_counsel_search,
)

SOURCE = "https://example.invalid/synthetic-counsel-bank.json"


def payload() -> dict:
    """合成题库：仅用于验证检索与校验，不代表游戏内真实咨询题目。"""
    return {
        "schema_version": 1,
        "source_url": SOURCE,
        "license": "synthetic-only",
        "checked_at": "2026-09-21",
        "entries": [
            {
                "id": "c001",
                "nikke": "拉毗",
                "aliases": ["Rapi", "拉比"],
                "question": "关于部队的作战风格，你会怎么回答？",
                "keywords": ["作战", "部队"],
                "options": [
                    {"id": "a", "label": "稳扎稳打", "detail": "重视同伴"},
                    {"id": "b", "label": "主动出击", "detail": "重视战果"},
                    {"id": "c", "label": "保存实力"},
                ],
                "answer_id": "a",
                "source_url": SOURCE,
            },
            {
                "id": "c002",
                "nikke": "拉毗",
                "aliases": ["Rapi"],
                "question": "休息日通常会做什么？",
                "keywords": ["休息", "日常"],
                "options": [
                    {"id": "a", "label": "训练"},
                    {"id": "b", "label": "散步"},
                ],
                "answer_id": "b",
                "source_url": SOURCE,
                "version": 2,
            },
            {
                "id": "c003",
                "nikke": "拉毗：红莲",
                "aliases": ["红莲"],
                "question": "作战前如何准备？",
                "keywords": ["作战", "准备"],
                "options": [
                    {"id": "a", "label": "检查装备"},
                    {"id": "b", "label": "直接出发"},
                ],
                "answer_id": "a",
                "source_url": SOURCE,
            },
        ],
    }


def bank() -> CounselBank:
    return CounselBank.from_payload(payload())


def test_alias_and_keyword_search_returns_option_and_source() -> None:
    result = bank().search("Rapi", "作战")
    assert not result.ambiguous
    assert [match.entry.entry_id for match in result.matches] == ["c001"]
    entry = result.matches[0].entry
    assert entry.answer().label == "稳扎稳打"
    assert result.matches[0].source == SOURCE

    text = render_counsel_search(result, bank())
    assert "【推荐】" in text
    assert "稳扎稳打" in text
    assert SOURCE in text
    assert "题库覆盖：3 条" in text


def test_keyword_narrows_multiple_entries_for_same_nikke() -> None:
    rest = bank().search("拉毗", "休息")
    assert [match.entry.entry_id for match in rest.matches] == ["c002"]
    assert rest.matches[0].entry.version == 2

    all_entries = bank().search("拉毗")
    assert {match.entry.entry_id for match in all_entries.matches} == {"c001", "c002"}


def test_ambiguous_nikke_names_are_distinguished() -> None:
    # “拉毗”同时是“拉毗”与“拉毗：红莲”的前缀，子串搜索必须显式报告歧义。
    result = bank().search("毗")
    assert result.ambiguous
    assert result.ambiguous_nikke == ("拉毗", "拉毗：红莲")
    assert "请改用完整名称或别名" in render_counsel_search(result, bank())


def test_missing_bank_is_explicit_and_never_fabricates_questions() -> None:
    missing = CounselBank.from_file("does-not-exist.json")
    assert missing.available is False
    assert "题库文件不存在" in missing.reason
    result = missing.search("拉毗", "作战")
    assert result.available is False
    text = render_counsel_search(result, missing)
    assert "题库缺失" in text
    assert "不会用假题代替真实题库" in text


def test_invalid_bank_payloads_are_rejected() -> None:
    bad_answer = payload()
    bad_answer["entries"][0]["answer_id"] = "z"
    try:
        CounselBank.from_payload(bad_answer)
    except CounselBankError as exc:
        assert "answer_id" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("answer_id 越界必须报错")

    bad_source = payload()
    bad_source["source_url"] = "http://example.invalid/bank.json"
    loaded = CounselBank.from_payload  # 保持调用面清晰
    try:
        loaded(bad_source)
    except CounselBankError as exc:
        assert "HTTPS" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("非 HTTPS 来源必须报错")


def test_counsel_bank_defaults_to_unbundled_missing_and_imports_partial_index(tmp_path) -> None:
    from pathlib import Path
    import json

    bundled = Path(__file__).resolve().parents[1] / "assets" / "data" / "counsel_bank.json"
    assert not bundled.exists()
    assert CounselBank.from_file(bundled).available is False

    imported = tmp_path / "counsel_bank.json"
    imported.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "source_url": "https://example.invalid/counsel",
                "license": "Operator Authorized",
                "checked_at": "2026-11-24",
                "entries": [
                    {
                        "id": "4025",
                        "nikke": "艾德米",
                        "aliases": ["Admi"],
                        "question_no": 1,
                        "question": "遇到流浪猫时",
                        "keywords": ["猫咪", "温柔"],
                        "options": [
                            {"id": "1", "label": "轻轻抚摸"},
                            {"id": "2", "label": "转身离开"},
                        ],
                        "answer_id": "1",
                        "answer_index": 1,
                        "source_url": "https://example.invalid/counsel/4025",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    real = CounselBank.from_file(imported)
    assert real.available is True
    result = real.search("艾德米", "猫咪")
    assert result.matches
    text = render_counsel_search(result, real)
    assert "来源答案序号：1" in text
    assert "不代表游戏内按钮位置" in text
