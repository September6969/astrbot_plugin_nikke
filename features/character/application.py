# SPDX-License-Identifier: GPL-3.0-or-later
"""妮姬角色查询用例及其账号、数据和静态资源端口。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping, Protocol, Sequence

from astrbot_plugin_nikke.core.privacy import safe_exception_message
from astrbot_plugin_nikke.features.account.errors import CredentialExpiredError
from .models import CharacterCardData, CharacterCardRequest, CharacterCardResult
from .research_levels import map_research_levels


_LOGGER = logging.getLogger(__name__)
DISPLAY_TIMEZONE = timezone(timedelta(hours=8))


class CharacterAccountReader(Protocol):
    def get_account(self, qq_id: str) -> Mapping[str, Any] | None:
        """读取角色查询所需的账号和凭据。"""


class CharacterGateway(Protocol):
    async def get_roster(
        self, account: Mapping[str, Any], include_details: bool = True
    ) -> list[Mapping[str, Any]]:
        """读取账号持有的妮姬列表。"""

    async def get_character_detail(
        self, account: Mapping[str, Any], name_code: str
    ) -> Mapping[str, Any]:
        """只读取指定 name_code 的角色详情。"""

    async def get_profile(self, account: Mapping[str, Any]) -> Mapping[str, Any]:
        """读取统计计算所需的前哨研究快照。"""


class CharacterIdentity(Protocol):
    def find(self, directory: Sequence[Mapping[str, Any]], query: str) -> list[dict[str, Any]]:
        """按唯一角色身份解析查询文本。"""

    def enrich(self, item: Mapping[str, Any]) -> dict[str, Any]:
        """用已核验目录补充角色本地化字段。"""

    @staticmethod
    def display_name(item: Mapping[str, Any]) -> str:
        """返回用于提示和展示的正式名称。"""


class CharacterStatResources(Protocol):
    def load_base(self) -> Any:
        """预热已经校验的角色静态属性表。"""

    def prepare_payload(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """为本次角色详情附加经过校验的静态资源快照。"""


class CharacterCardBuilderPort(Protocol):
    def build(
        self,
        *,
        account: Mapping[str, Any],
        directory: Mapping[str, Any],
        payload: Mapping[str, Any],
        fetched_at: str,
        plugin_version: str,
        display_name: str,
    ) -> CharacterCardData:
        """从身份、账号和上游详情构建角色卡领域 DTO。"""


@dataclass(frozen=True, slots=True)
class CharacterRosterData:
    commander_name: str
    characters: tuple[Mapping[str, Any], ...]
    name_map: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class CharacterInfoData:
    name: str
    title: str
    rows: tuple[tuple[str, str], ...]


class CharacterNotFound(ValueError):
    """角色目录中没有与查询匹配的角色。"""


class CharacterAmbiguousMatch(ValueError):
    """查询匹配多个角色，不允许静默选择第一个结果。"""

    def __init__(self, candidates: Sequence[str], *, too_many: bool = False) -> None:
        self.candidates = tuple(candidates)
        self.too_many = too_many
        super().__init__("角色名称匹配多个候选项")


class CharacterNotOwned(ValueError):
    """账号未持有已明确匹配的角色。"""

    def __init__(self, display_name: str) -> None:
        self.display_name = display_name
        super().__init__(f"你未持有该妮姬：{display_name}")


class CharacterIdentityMismatch(ValueError):
    """上游角色详情身份与请求代码不一致或缺失。"""


class CharacterApplication:
    """角色查询用例；不拥有平台事件或图片渲染副作用。"""

    PROFILE_CACHE_TTL_SECONDS = 300.0
    PROFILE_CACHE_LIMIT = 50

    def __init__(
        self,
        *,
        account_reader: CharacterAccountReader,
        gateway: CharacterGateway,
        identity: CharacterIdentity,
        stat_resources: CharacterStatResources,
        card_builder: CharacterCardBuilderPort,
        clock: Callable[[], datetime],
        monotonic: Callable[[], float] | None = None,
        plugin_version: str,
    ) -> None:
        self._account_reader = account_reader
        self._gateway = gateway
        self._identity = identity
        self._stat_resources = stat_resources
        self._card_builder = card_builder
        self._clock = clock
        self._monotonic = monotonic or time.monotonic
        self._plugin_version = plugin_version
        self._stats_profile_cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._name_map_cache: tuple[str, dict[str, str]] | None = None

    def _account(self, qq_id: str) -> Mapping[str, Any]:
        account = self._account_reader.get_account(str(qq_id))
        if not account:
            raise ValueError("尚未绑定账号，请先私聊发送 /妮姬 账号 绑定")
        return account

    def _query_time(self) -> datetime:
        current = self._clock()
        if not isinstance(current, datetime):
            raise TypeError("角色查询时钟必须返回 datetime")
        if current.tzinfo is None:
            current = current.replace(tzinfo=DISPLAY_TIMEZONE)
        return current.astimezone(DISPLAY_TIMEZONE)

    async def preload_stat_resources(self) -> Any:
        """在线程中预热静态属性表，不让插件入口直接操作统计资源。"""
        return await asyncio.to_thread(self._stat_resources.load_base)

    def name_map(self, directory: Sequence[Mapping[str, Any]]) -> dict[str, str]:
        """按目录内容指纹缓存 roster 展示名，避免目录变化后复用陈旧结果。"""
        entries = [
            (
                str(item.get("name_code", "")),
                str(item.get("name_zh_cn", "")),
                str(item.get("name_zh_tw", "")),
                str(item.get("name_cn", "")),
                str(item.get("name_en", "")),
            )
            for item in directory
            if isinstance(item, Mapping)
        ]
        payload = json.dumps(entries, ensure_ascii=False, separators=(",", ":"))
        fingerprint = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        cached = self._name_map_cache
        if cached is not None and cached[0] == fingerprint:
            return cached[1]

        mapping = {
            str(item.get("name_code", "")): self._identity.display_name(
                self._identity.enrich(item)
            )
            for item in directory
            if isinstance(item, Mapping)
        }
        self._name_map_cache = (fingerprint, mapping)
        return mapping

    async def roster(
        self, qq_id: str, directory: Sequence[Mapping[str, Any]]
    ) -> CharacterRosterData:
        """读取练度列表并附上与同一目录快照匹配的名称。"""
        account = self._account(qq_id)
        characters = await self._gateway.get_roster(account, True)
        if not isinstance(characters, list):
            raise TypeError("角色列表响应必须是数组")
        return CharacterRosterData(
            commander_name=str(
                account.get("nickname") or account.get("role_name") or "指挥官"
            ),
            characters=tuple(characters),
            name_map=self.name_map(directory),
        )

    def _unique_match(
        self, query: str, directory: Sequence[Mapping[str, Any]]
    ) -> dict[str, Any]:
        matches = self._identity.find(directory, query)
        if not matches:
            raise CharacterNotFound("没有找到该妮姬")
        if len(matches) > 1:
            candidates = tuple(
                self._identity.display_name(item) for item in matches[:10]
            )
            raise CharacterAmbiguousMatch(candidates, too_many=len(matches) > 10)
        return matches[0]

    def info(
        self, query: str, directory: Sequence[Mapping[str, Any]]
    ) -> CharacterInfoData:
        """构建唯一匹配角色的公开基础资料；多候选时失败关闭。"""
        item = self._identity.enrich(self._unique_match(query, directory))
        name = self._identity.display_name(item)
        zh_tw = item.get("name_zh_tw") or item.get("name_cn") or "未知"
        name_suffix = f"{name} / {zh_tw} / {item.get('name_en') or '未知'}"
        return CharacterInfoData(
            name=name,
            title="妮姬基础资料",
            rows=(
                ("名称（简体别名 / 繁中 / 英文）", name_suffix),
                ("稀有度", str(item.get("rare") or "未知")),
                ("属性", str(item.get("element") or "未知")),
                ("武器", str(item.get("weapon") or "未知")),
                ("爆裂阶段", str(item.get("burst") or "未知")),
                ("企业", str(item.get("corporation") or "未知")),
            ),
        )

    async def profile_for_stat_calculation(
        self, account: Mapping[str, Any]
    ) -> dict[str, Any]:
        """缓存前哨研究快照；失败时由统计计算器保守显示不可用。"""
        cache_key = str(account.get("game_uid") or account.get("qq_id") or "account")
        now = self._monotonic()
        cached = self._stats_profile_cache.get(cache_key)
        if cached and now - cached[0] < self.PROFILE_CACHE_TTL_SECONDS:
            return cached[1]
        try:
            profile = await self._gateway.get_profile(account)
        except Exception as exc:
            if isinstance(exc, CredentialExpiredError):
                raise
            _LOGGER.warning(
                "[NIKKE] 研究快照读取失败：%s", safe_exception_message(exc)
            )
            profile = {}
        if not isinstance(profile, dict):
            profile = {}
        if len(self._stats_profile_cache) >= self.PROFILE_CACHE_LIMIT:
            expired = [
                key
                for key, value in self._stats_profile_cache.items()
                if now - value[0] >= self.PROFILE_CACHE_TTL_SECONDS
            ]
            for key in expired:
                self._stats_profile_cache.pop(key, None)
            while len(self._stats_profile_cache) >= self.PROFILE_CACHE_LIMIT:
                oldest = min(
                    self._stats_profile_cache,
                    key=lambda key: self._stats_profile_cache[key][0],
                )
                self._stats_profile_cache.pop(oldest, None)
        self._stats_profile_cache[cache_key] = (now, profile)
        return profile

    async def character_card(
        self,
        qq_id: str,
        query: str,
        directory: Sequence[Mapping[str, Any]],
    ) -> CharacterCardData:
        """兼容旧调用方；新入口使用显式的 request/result 合同。"""
        result = await self.build_card(
            CharacterCardRequest(qq_id=str(qq_id), query=query, directory=tuple(directory))
        )
        return result.card

    async def build_card(
        self, request: CharacterCardRequest
    ) -> CharacterCardResult:
        """按唯一目录身份读取并构建角色卡；凭据只留在上游网关调用内。"""
        account = self._account(request.qq_id)
        target = self._identity.enrich(
            self._unique_match(request.query, request.directory)
        )
        code = str(target.get("name_code", "")).strip()
        if not code:
            raise CharacterIdentityMismatch("角色目录缺少稳定 name_code")
        display_name = self._identity.display_name(target)
        try:
            payload = await self._gateway.get_character_detail(account, code)
        except ValueError as exc:
            if "未持有" in str(exc):
                raise CharacterNotOwned(display_name) from exc
            raise
        if not isinstance(payload, Mapping):
            raise CharacterIdentityMismatch("角色详情响应不是对象")
        for field in ("roster_item", "detail"):
            member = payload.get(field)
            response_code = (
                str(member.get("name_code", "")).strip()
                if isinstance(member, Mapping)
                else ""
            )
            if response_code != code:
                raise CharacterIdentityMismatch(
                    f"角色详情 {field} 身份与请求不一致"
                )

        profile = await self.profile_for_stat_calculation(account)
        outpost = profile.get("outpost", {}) if isinstance(profile, Mapping) else {}
        account_for_card = {
            "nickname": account.get("nickname"),
            "role_name": account.get("role_name"),
            "research_levels": map_research_levels(
                outpost.get("recycle_room_researches")
                if isinstance(outpost, Mapping)
                else None
            ),
        }
        prepared_payload = dict(payload)
        try:
            prepared_payload = await asyncio.to_thread(
                self._stat_resources.prepare_payload, prepared_payload
            )
        except Exception as exc:
            _LOGGER.warning(
                "[NIKKE] 角色静态属性资源准备失败：%s",
                safe_exception_message(exc),
            )
        card = self._card_builder.build(
            account=account_for_card,
            directory=target,
            payload=prepared_payload,
            fetched_at=self._query_time().strftime("%Y-%m-%d %H:%M"),
            plugin_version=self._plugin_version,
            display_name=display_name,
        )
        return CharacterCardResult(card=card)
