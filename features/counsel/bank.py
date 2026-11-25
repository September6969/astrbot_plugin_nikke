# SPDX-License-Identifier: GPL-3.0-or-later
"""咨询答案查询（07）：妮姬名称/别名与问题关键词检索。

仓库不含可分发的完整咨询题库；本模块提供**严格校验的导入格式**，只在运营者或用户
显式导入带来源与许可声明的题库后提供查询。缺失时返回明确缺口说明，绝不内置假题。
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import urlparse

_ENTRY_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")


class CounselBankError(ValueError):
    """题库不符合导入格式或来源声明。"""


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CounselBankError(f"{field} 缺失")
    return value.strip()


def _norm(value: Any) -> str:
    return unicodedata.normalize("NFKC", str(value or "")).casefold().strip()


def _source(value: Any, field: str) -> str:
    text = _text(value, field)
    parsed = urlparse(text)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise CounselBankError(f"{field} 必须是无凭据 HTTPS 地址")
    return text


@dataclass(frozen=True, slots=True)
class CounselOption:
    option_id: str
    label: str
    detail: str = ""


@dataclass(frozen=True, slots=True)
class CounselEntry:
    entry_id: str
    nikke: str
    question: str
    keywords: tuple[str, ...]
    options: tuple[CounselOption, ...]
    answer_id: str
    source_url: str
    version: int = 1
    aliases: tuple[str, ...] = ()
    answer_index: int = 1
    question_no: int | None = None

    def answer(self) -> CounselOption | None:
        return next((item for item in self.options if item.option_id == self.answer_id), None)


@dataclass(frozen=True, slots=True)
class CounselMatch:
    entry: CounselEntry

    @property
    def source(self) -> str:
        return self.entry.source_url


@dataclass(frozen=True, slots=True)
class CounselSearch:
    """一次咨询检索结果；范围与缺口均可解释。"""

    nikke: str
    keyword: str
    matches: tuple[CounselMatch, ...] = ()
    ambiguous_nikke: tuple[str, ...] = ()
    available: bool = True
    reason: str = ""
    match_kind: str = "exact"

    @property
    def ambiguous(self) -> bool:
        return bool(self.ambiguous_nikke)


@dataclass(frozen=True, slots=True)
class CounselBank:
    """已导入的咨询题库；空题库是安全的“缺失”状态。"""

    entries: tuple[CounselEntry, ...] = ()
    source_url: str = ""
    license_note: str = ""
    checked_at: str = ""
    available: bool = False
    reason: str = ""

    @classmethod
    def missing(cls, reason: str = "") -> "CounselBank":
        return cls(
            available=False,
            reason=reason
            or "未导入可分发咨询题库；请由运营者以带来源与许可声明的 JSON 导入后再查询。",
        )

    @classmethod
    def from_file(cls, path: str | Path) -> "CounselBank":
        target = Path(path)
        if not target.is_file():
            return cls.missing(f"题库文件不存在：{target.name}")
        try:
            payload = json.loads(target.read_text(encoding="utf-8"))
        except OSError:
            return cls.missing(f"题库文件无法读取：{target.name}")
        except (UnicodeError, json.JSONDecodeError):
            return cls.missing("题库不是合法 UTF-8 JSON")
        try:
            return cls.from_payload(payload)
        except CounselBankError as exc:
            return cls.missing(f"题库格式无效：{exc}")

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "CounselBank":
        if not isinstance(payload, Mapping):
            raise CounselBankError("题库根节点必须是对象")
        if payload.get("schema_version") != 1:
            raise CounselBankError("schema_version 必须为 1")
        source = _source(payload.get("source_url"), "source_url")
        license_note = _text(payload.get("license"), "license")
        checked_at = _text(payload.get("checked_at"), "checked_at")
        raw_entries = payload.get("entries")
        if not isinstance(raw_entries, list) or not raw_entries:
            raise CounselBankError("entries 必须是非空数组")
        entries: list[CounselEntry] = []
        seen: set[str] = set()
        for index, raw in enumerate(raw_entries):
            if not isinstance(raw, Mapping):
                raise CounselBankError(f"entries[{index}] 必须是对象")
            entry_id = _text(raw.get("id"), f"entries[{index}].id")
            if not _ENTRY_ID.fullmatch(entry_id):
                raise CounselBankError(f"entries[{index}].id 含非法字符")
            if entry_id in seen:
                raise CounselBankError(f"题库条目 ID 重复：{entry_id}")
            seen.add(entry_id)
            options_raw = raw.get("options")
            if not isinstance(options_raw, list) or len(options_raw) < 2:
                raise CounselBankError(f"entries[{index}].options 至少需要两个选项")
            options: list[CounselOption] = []
            option_ids: set[str] = set()
            for position, option in enumerate(options_raw):
                if not isinstance(option, Mapping):
                    raise CounselBankError(f"entries[{index}].options[{position}] 必须是对象")
                option_id = _text(option.get("id"), f"entries[{index}].options[{position}].id")
                if option_id in option_ids:
                    raise CounselBankError(f"entries[{index}] 选项 ID 重复：{option_id}")
                option_ids.add(option_id)
                detail = option.get("detail", "")
                if not isinstance(detail, str):
                    raise CounselBankError(f"entries[{index}].options[{position}].detail 必须是字符串")
                options.append(
                    CounselOption(
                        option_id=option_id,
                        label=_text(option.get("label"), f"entries[{index}].options[{position}].label"),
                        detail=detail.strip(),
                    )
                )
            answer_id = _text(raw.get("answer_id"), f"entries[{index}].answer_id")
            if answer_id not in option_ids:
                raise CounselBankError(f"entries[{index}].answer_id 不在选项内")
            keywords_raw = raw.get("keywords", [])
            if not isinstance(keywords_raw, list) or any(not isinstance(item, str) for item in keywords_raw):
                raise CounselBankError(f"entries[{index}].keywords 必须是字符串数组")
            aliases_raw = raw.get("aliases", [])
            if not isinstance(aliases_raw, list) or any(not isinstance(item, str) for item in aliases_raw):
                raise CounselBankError(f"entries[{index}].aliases 必须是字符串数组")
            version = raw.get("version", 1)
            if isinstance(version, bool) or not isinstance(version, int) or version < 1:
                raise CounselBankError(f"entries[{index}].version 必须是正整数")
            question_no = raw.get("question_no")
            if question_no is not None and (
                isinstance(question_no, bool) or not isinstance(question_no, int) or question_no < 1
            ):
                raise CounselBankError(f"entries[{index}].question_no 必须是正整数")
            answer_index = raw.get("answer_index", 1)
            if (
                isinstance(answer_index, bool)
                or not isinstance(answer_index, int)
                or not 1 <= answer_index <= len(options)
            ):
                raise CounselBankError(f"entries[{index}].answer_index 超出选项范围")
            entries.append(
                CounselEntry(
                    entry_id=entry_id,
                    nikke=_text(raw.get("nikke"), f"entries[{index}].nikke"),
                    question=_text(raw.get("question"), f"entries[{index}].question"),
                    keywords=tuple(item.strip() for item in keywords_raw if item.strip()),
                    options=tuple(options),
                    answer_id=answer_id,
                    source_url=_source(raw.get("source_url", source), f"entries[{index}].source_url"),
                    version=version,
                    aliases=tuple(item.strip() for item in aliases_raw if item.strip()),
                    answer_index=answer_index,
                    question_no=question_no,
                )
            )
        return cls(
            entries=tuple(entries),
            source_url=source,
            license_note=license_note,
            checked_at=checked_at,
            available=True,
        )

    def search(self, nikke: str, keyword: str = "", *, limit: int = 5) -> CounselSearch:
        """按妮姬名称/别名与问题关键词检索；重名或多结果显式区分。"""
        if not self.available:
            return CounselSearch(nikke=nikke, keyword=keyword, available=False, reason=self.reason)
        if not 1 <= limit <= 20:
            raise CounselBankError("结果数量上限必须在 1–20")
        query = _norm(nikke)
        if not query:
            raise CounselBankError("请提供妮姬名称或别名")
        # 先按名称/别名精确匹配；无精确命中时再退化为子串匹配，但必须唯一。
        exact = [entry for entry in self.entries if query in {_norm(entry.nikke), *(_norm(alias) for alias in entry.aliases)}]
        match_kind = "exact"
        pool = exact
        if not pool:
            match_kind = "partial"
            partial = [
                entry for entry in self.entries
                if query in _norm(entry.nikke) or any(query in _norm(alias) for alias in entry.aliases)
            ]
            names = {entry.nikke for entry in partial}
            if len(names) > 1:
                return CounselSearch(
                    nikke=nikke,
                    keyword=keyword,
                    ambiguous_nikke=tuple(sorted(names)),
                    match_kind="ambiguous",
                )
            pool = partial
        if not pool:
            return CounselSearch(nikke=nikke, keyword=keyword, matches=(), match_kind="none")

        tokens = [token for token in re.split(r"[\s,，、/]+", _norm(keyword)) if token]
        scored: list[tuple[int, str, CounselEntry]] = []
        for entry in pool:
            haystack = _norm(entry.question + " " + " ".join(entry.keywords) + " " + " ".join(
                option.label + " " + option.detail for option in entry.options
            ))
            hits = sum(1 for token in tokens if token in haystack)
            if tokens and hits == 0:
                continue
            scored.append((hits, entry.entry_id, entry))
        scored.sort(key=lambda row: (-row[0], row[1]))
        return CounselSearch(
            nikke=nikke,
            keyword=keyword,
            matches=tuple(CounselMatch(entry) for _, _, entry in scored[:limit]),
            match_kind=match_kind,
        )


def render_counsel_search(result: CounselSearch, bank: CounselBank) -> str:
    """渲染检索结果；缺口、匹配方式与歧义分别说明。"""
    if not result.available:
        return "【咨询答案】\n题库缺失：" + result.reason + "\n本功能不会用假题代替真实题库。"
    title = f"【咨询答案】{result.nikke}"
    if result.keyword:
        title += f" · 关键词：{result.keyword}"
    lines = [title]
    if result.ambiguous:
        lines.append("名称匹配到多名妮姬，请改用完整名称或别名：" + "、".join(result.ambiguous_nikke))
        return "\n".join(lines)
    if not result.matches:
        lines.append("题库中未找到匹配条目；覆盖范围：" + (bank.checked_at or "未标注核验日期"))
        lines.append("来源：" + (bank.source_url or "未提供"))
        lines.append("说明：未收录条目不自动推测答案。")
        return "\n".join(lines)
    if result.match_kind == "partial":
        lines.append(f"匹配方式：名称子串模糊命中（{result.matches[0].entry.nikke}；如非目标角色请改用完整名称）")
    else:
        lines.append(f"匹配方式：名称/别名精确匹配（{result.matches[0].entry.nikke}）")
    for match in result.matches:
        entry = match.entry
        answer = entry.answer()
        lines.append("")
        prefix = f"第 {entry.question_no} 问 · " if entry.question_no else ""
        lines.append(f"· {prefix}{entry.question}")
        for option in entry.options:
            marker = "【推荐】" if answer is not None and option.option_id == answer.option_id else ""
            detail = f"：{option.detail}" if option.detail else ""
            lines.append(f"  {option.option_id}. {option.label}{marker}{detail}")
        lines.append(
            f"  来源答案序号：{entry.answer_index}"
            "（网站索引顺序，不代表游戏内按钮位置） · "
            f"来源：{entry.source_url} · 题库版本 v{entry.version}"
        )
    lines.append("")
    lines.append(f"题库覆盖：{len(bank.entries)} 条 · 核验 {bank.checked_at or '未标注'} · 许可：{bank.license_note or '未标注'}")
    return "\n".join(lines)


__all__ = [
    "CounselBank",
    "CounselBankError",
    "CounselEntry",
    "CounselMatch",
    "CounselOption",
    "CounselSearch",
    "render_counsel_search",
]
