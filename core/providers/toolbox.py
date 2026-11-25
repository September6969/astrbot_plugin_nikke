# SPDX-License-Identifier: GPL-3.0-or-later
"""本地工具集（04/05/07/12/14/16/22/26/27/29）的组合根。

只装配仓库已有的仓储、日程快照、角色元数据与可选导入文件；所有外部数据文件缺失时
保持显式的“未导入”状态，不生成占位数据。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from ...features.announcement.feeds import (
    AnnouncementCatalog,
    FeedCatalog,
    FeedSubscriptions,
    ScheduleCatalog,
    VideoCatalog,
)
from ...features.calendar.application import CalendarApplication
from ...features.character.identity import CharacterDirectoryResolver
from ...features.counsel.bank import CounselBank
from ...features.favorite_grid.grid import FavoriteRanking
from ...features.growth.history import (
    GrowthHistory,
    RosterGrowthHistory,
    growth_identity_key,
    snapshot_from_dashboard,
)
from ...features.identity.public_profile import ManualProfileStore
from ...features.overload_advice.advisor import (
    CharacterTargets,
    OverloadAdviceError,
    load_character_targets,
    load_default_line_counts,
    load_recommendations,
)
from ...features.solo_raid.plans import SoloRaidPlanStore
from ...features.solo_raid.seasons import SeasonCatalog
from ...features.sync.cost_table import SyncCostTable, SyncCostTableError
from ...features.wishlist.advisor import (
    PoolEligibilityEntry,
    WishlistError,
    load_pool_eligibility,
)
from ...integrations.announcement.youtube_atom import YouTubeAtomSource
from ...integrations.nikke_api.share_profile import fetch_public_share
from ...integrations.nikke_calc.engine import (
    EngineNameMappingError,
    SoloRaidDamageEngine,
    load_name_mapping_with_meta,
)


@dataclass(frozen=True)
class ToolboxServices:
    """十个本地工具共享的只读/持久化依赖。"""

    calendar: CalendarApplication | None
    feeds: FeedSubscriptions
    counsel: CounselBank
    sync_table: SyncCostTable | None
    sync_table_error: str
    wishlist_rows: tuple[Mapping[str, Any], ...]
    wishlist_exclusions: tuple[str, ...]
    overload_recommendations: Mapping[str, tuple[str, ...]]
    overload_recommendation_label: str
    solo_catalog: SeasonCatalog
    solo_plans: SoloRaidPlanStore
    solo_damage_model: Mapping[str, Any] | None
    solo_engine: SoloRaidDamageEngine | None
    share_lookup: Callable[..., Any] | None
    roster_loader: Callable[[Mapping[str, Any]], Any] | None
    profile_loader: Callable[[Mapping[str, Any]], Any] | None
    account_reader: Any
    manual_profiles: ManualProfileStore
    growth: GrowthHistory
    roster_growth: RosterGrowthHistory
    grid_rows: tuple[Mapping[str, Any], ...]
    grid_resolver: CharacterDirectoryResolver
    grid_ranking: FavoriteRanking
    overload_character_targets: Mapping[str, CharacterTargets] | None = None
    overload_default_counts: Mapping[str, int] | None = None
    shiftypad_web: Any | None = None
    shiftypad_readonly: Any | None = None
    public_share_enabled: bool = False
    card_loader: Callable[[str, str], Any] | None = None
    wishlist_eligibility: Mapping[str, PoolEligibilityEntry] = field(default_factory=dict)

    def growth_generation(self, actor_id: str) -> int:
        """读取清空代数快照，防止清零后并发旧请求回写。"""
        return self.growth.generation(actor_id)

    def _growth_identity(self, actor_id: str, account: Any = None, identity: str = "") -> str:
        if identity:
            return str(identity).strip()
        if account is not None:
            return growth_identity_key(account)
        if self.account_reader is not None and hasattr(self.account_reader, "get_account"):
            return growth_identity_key(self.account_reader.get_account(actor_id))
        return ""

    def record_roster(
        self,
        actor_id: str,
        rows: Any,
        *,
        account: Mapping[str, Any] | None = None,
        identity: str = "",
        expected_generation: int | None = None,
    ) -> Any:
        """角色名单成功读取后按游戏身份隔离写入角色成长快照。"""
        return self.roster_growth.record(
            actor_id,
            rows,
            identity=self._growth_identity(actor_id, account=account, identity=identity),
            expected_generation=expected_generation,
        )

    def record_growth(
        self,
        context: Any,
        dashboard: Any,
        *,
        account: Mapping[str, Any] | None = None,
        identity: str = "",
        expected_generation: int | None = None,
    ) -> Any:
        """成功账号同步后按游戏身份隔离写入成长快照；失败由调用方降级为提示。"""
        actor_id = str(getattr(context, "actor_id", "") or "")
        return self.growth.record(
            actor_id,
            snapshot_from_dashboard(dashboard),
            identity=self._growth_identity(actor_id, account=account, identity=identity),
            expected_generation=expected_generation,
        )


def _optional_json(path: Path) -> Any:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None


def _character_rows(plugin_dir: Path) -> tuple[dict[str, Any], ...]:
    payload = _optional_json(plugin_dir / "assets" / "data" / "character_master.json")
    rows = payload.get("characters") if isinstance(payload, Mapping) else None
    if not isinstance(rows, list):
        return ()
    result: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        item = dict(row)
        item.setdefault("name_zh_cn", str(item.get("name_zh_tw") or item.get("name_cn") or ""))
        result.append(item)
    return tuple(result)


def _exclusions(path: Path) -> tuple[str, ...]:
    payload = _optional_json(path)
    if isinstance(payload, Mapping):
        payload = payload.get("exclusions")
    if not isinstance(payload, list):
        return ()
    return tuple(str(item).strip() for item in payload if isinstance(item, (str, int)) and str(item).strip())


def _wishlist_eligibility(data_dir: Path, plugin_dir: Path) -> dict[str, PoolEligibilityEntry]:
    result: dict[str, PoolEligibilityEntry] = {}
    bundled = plugin_dir / "assets" / "data" / "wishlist_pool_eligibility.json"
    if bundled.is_file():
        try:
            result.update(load_pool_eligibility(bundled))
        except WishlistError:
            return {}
    override = data_dir / "wishlist-pool-eligibility.json"
    if override.is_file():
        try:
            result.update(load_pool_eligibility(override))
        except WishlistError:
            pass
    return result


def _sync_table(
    config: Mapping[str, Any], data_dir: Path, plugin_dir: Path
) -> tuple[SyncCostTable | None, str]:
    raw = str(config.get("sync_level_cost_table_path") or "").strip()
    if raw:
        path = Path(raw)
    else:
        imported = data_dir / "sync-level-costs.json"
        path = imported if imported.is_file() else plugin_dir / "assets" / "data" / "sync-level-costs.json"
    if not path.is_file():
        return None, "未配置同步器等级成本表（缺少可靠成本数据，不猜测等级消耗）。"
    try:
        return SyncCostTable.from_file(path), ""
    except SyncCostTableError as exc:
        return None, f"同步器成本表无效：{exc}"


def _counsel_bank(config: Mapping[str, Any], data_dir: Path, plugin_dir: Path) -> CounselBank:
    raw = str(config.get("counsel_bank_path") or "").strip()
    if raw:
        path = Path(raw)
    else:
        imported = data_dir / "counsel-bank.json"
        path = imported if imported.is_file() else plugin_dir / "assets" / "data" / "counsel_bank.json"
    return CounselBank.from_file(path)


def _recommendations(
    config: Mapping[str, Any], data_dir: Path, plugin_dir: Path
) -> tuple[dict[str, tuple[str, ...]], str, dict[str, CharacterTargets], dict[str, int]]:
    raw = str(config.get("overload_recommendations_path") or "").strip()
    if raw:
        path = Path(raw)
    else:
        imported = data_dir / "overload-recommendations.json"
        path = imported if imported.is_file() else plugin_dir / "assets" / "data" / "overload_recommendations.json"
    if not path.is_file():
        return {}, "", {}, {}
    try:
        values = load_recommendations(path)
        characters = load_character_targets(path)
        defaults = load_default_line_counts(path)
        label = (
            f"导入推荐表（{path.name}）"
            if characters
            else (f"导入默认目标（{path.name}，非角色专属）" if "__default__" in values else path.name)
        )
        return values, label, characters, defaults
    except OverloadAdviceError:
        return {}, f"{path.name}（格式无效）", {}, {}


def _season_catalog(config: Mapping[str, Any], plugin_dir: Path, data_dir: Path) -> SeasonCatalog:
    raw = str(config.get("solo_raid_season_path") or "").strip()
    if raw:
        return SeasonCatalog.from_file(Path(raw))
    # 数据目录中的维护副本优先于内置空表，便于运营者离线导入新赛季。
    imported = data_dir / "solo-raid-seasons.json"
    if imported.is_file():
        return SeasonCatalog.from_file(imported)
    return SeasonCatalog.from_file(plugin_dir / "assets" / "data" / "solo_raid_seasons.json")


def create_toolbox_services(
    *,
    plugin_dir: Path,
    data_dir: Path,
    store: Any,
    calendar: CalendarApplication | None,
    announcements: Any,
    account_reader: Any,
    roster_loader: Callable[[Mapping[str, Any]], Any] | None,
    profile_loader: Callable[[Mapping[str, Any]], Any] | None,
    config: Mapping[str, Any],
    clock: Callable[[], Any] | None = None,
    card_loader: Callable[[str, str], Any] | None = None,
) -> ToolboxServices:
    """装配十个工具的依赖；不联网、不读取账号凭据。"""
    video_source = YouTubeAtomSource()
    catalog = FeedCatalog(
        {
            "news": AnnouncementCatalog(announcements),
            "video": VideoCatalog(video_source),
            "schedule": ScheduleCatalog(calendar, clock=clock),
        }
    )
    feeds = FeedSubscriptions(store, catalog, clock=clock)
    table, table_error = _sync_table(config, data_dir, plugin_dir)
    recommendations, recommendation_label, character_targets, default_counts = _recommendations(config, data_dir, plugin_dir)
    engine_path = str(
        config.get("solo_raid_engine_path")
        or os.environ.get("NIKKE_CALC_ENGINE_PATH")
        or data_dir / "nikke-calc"
    ).strip()
    mapping: dict[str, str] = {}
    mapping_commit = ""
    mapping_error = ""
    mapping_path = data_dir / "solo-raid-engine-names.json"
    if not mapping_path.is_file():
        bundled = plugin_dir / "assets" / "data" / "solo_raid_engine_names.json"
        mapping_path = bundled if bundled.is_file() else mapping_path
    if mapping_path.is_file():
        try:
            mapping, mapping_commit = load_name_mapping_with_meta(mapping_path)
        except EngineNameMappingError as exc:
            mapping_error = str(exc)
    solo_engine = SoloRaidDamageEngine(
        Path(engine_path),
        mapping,
        mapping_error=mapping_error,
        mapping_commit=mapping_commit,
        work_dir=data_dir / "nikke-calc-runs",
        require_git=True,
        allow_unverified=config.get("solo_raid_engine_allow_unverified") is True,
    )
    damage_model = config.get("solo_raid_damage_model")
    if isinstance(damage_model, str):
        try:
            damage_model = json.loads(damage_model) if damage_model.strip() else None
        except json.JSONDecodeError:
            damage_model = None
    if not isinstance(damage_model, Mapping):
        damage_model = None
    rows = _character_rows(plugin_dir)
    public_share_enabled = config.get("enable_public_share_api") is True
    return ToolboxServices(
        calendar=calendar,
        feeds=feeds,
        counsel=_counsel_bank(config, data_dir, plugin_dir),
        sync_table=table,
        sync_table_error=table_error,
        wishlist_rows=rows,
        wishlist_exclusions=_exclusions(data_dir / "wishlist-exclusions.json"),
        wishlist_eligibility=_wishlist_eligibility(data_dir, plugin_dir),
        overload_recommendations=recommendations,
        overload_recommendation_label=recommendation_label,
        overload_character_targets=character_targets,
        overload_default_counts=default_counts,
        solo_catalog=_season_catalog(config, plugin_dir, data_dir),
        solo_plans=SoloRaidPlanStore(store, clock=clock),
        solo_damage_model=damage_model,
        solo_engine=solo_engine,
        share_lookup=fetch_public_share if public_share_enabled else None,
        public_share_enabled=public_share_enabled,
        card_loader=card_loader,
        roster_loader=roster_loader,
        profile_loader=profile_loader,
        account_reader=account_reader,
        manual_profiles=ManualProfileStore(store, clock=clock),
        growth=GrowthHistory(store, clock=clock),
        roster_growth=RosterGrowthHistory(store, clock=clock),
        grid_rows=rows,
        grid_resolver=CharacterDirectoryResolver(),
        grid_ranking=FavoriteRanking(store, clock=clock),
    )


__all__ = ["ToolboxServices", "create_toolbox_services"]
