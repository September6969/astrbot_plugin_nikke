# 根目录 Python 文件与兼容性 Shim 完整审计报告 (2026-09)

> **审计目的**：
> 针对 Issue #82 完成后的仓库根目录，全面排查 94 个根目录 `.py` 文件，制定清理与迁移策略。
> 消除视觉拥挤与冗余存根，将所有业务实现与内部引用全面收敛至 `features/`, `core/`, `integrations/`, `ui/` 分层包中。

> **后续状态（PR #103）**：本审计是历史快照。`character_card_renderer.py` 兼容 shim 及其 1800×1000 Pillow 实现已彻底删除；当前角色练度卡只使用白色竖版 T2I replica。

---

## 一、分类统计总览

| 分类代码 | 类别描述 | 数量 | 处置原则 |
| :---: | :--- | :---: | :--- |
| **A** | **必须保留的正式入口** | **4** | 永久保留在根目录（`main.py`, `__init__.py`, `_version.py`, `container.py`） |
| **B** | **Compatibility Shim (有引用待清理)** | **64** | 先清理内部/测试引用，确认无外部依赖后分批清理 |
| **C** | **仍包含真实实现的遗留模块** | **16** | 完整迁移至对应领域包，再切断旧引用 |
| **D** | **已无引用、可安全删除的 Shim** | **10** | 第一批（PR A）直接删除 |
| **E** | **不确定、需进一步追踪** | **0** | 经全库交叉分析，所有模块均已明确分类 |
| **合计** | **根目录 Python 文件总数** | **94** | - |

---

## 二、全量 94 个根目录文件详细审计明细表

| 序号 | 文件名 (`file`) | 分类 | 当前角色 (`current role`) | 目标正式模块 (`target module`) | 内部引用数 | 测试引用数 | 外部/公开兼容风险 | 计划行动 (`action`) |
| :---: | :--- | :---: | :--- | :--- | :---: | :---: | :--- | :--- |
| 1 | `__init__.py` | **A** | Official Entrypoint | `-` | 1 (main.py) | 0 (无) | Critical (Plugin Failure) | Keep at root |
| 2 | `_version.py` | **A** | Official Entrypoint | `-` | 2 (main.py, integrations/service.py) | 3 (test_card_builder.py, test_release_metadata.py...) | Critical (Plugin Failure) | Keep at root |
| 3 | `announcement_delivery.py` | **A** | Compatibility Shim | `features.announcement.delivery` | 1 (main.py) | 4 (test_announcement_delivery.py, test_announcement_push_wiring.py...) | Low (Internal legacy) | Keep at root |
| 4 | `announcement_models.py` | **A** | Compatibility Shim | `features.announcement.models` | 0 (无) | 6 (test_announcements.py, test_announcement_cache_lifecycle.py...) | Low (Internal legacy) | Keep at root |
| 5 | `announcement_service.py` | **A** | Compatibility Shim | `features.announcement.service` | 1 (main.py) | 10 (test_announcements.py, test_announcement_cache_lifecycle.py...) | Low (Internal legacy) | Keep at root |
| 6 | `announcement_sources.py` | **A** | Compatibility Shim | `features.announcement.sources` | 0 (无) | 2 (test_announcement_v2.py, test_informationfeeds.py) | Low (Internal legacy) | Keep at root |
| 7 | `asset_manager.py` | **A** | Compatibility Shim | `core.asset_manager` | 17 (main.py, core/container.py...) | 14 (test_asset_manager.py, test_character_card_renderer.py...) | Low (Internal legacy) | Keep at root |
| 8 | `bind_template.py` | **A** | Compatibility Shim | `integrations.web.bind_template` | 1 (integrations/service.py) | 1 (test_bind_tutorial.py) | Low (Internal legacy) | Keep at root |
| 9 | `boss_asset_resolver.py` | **C** | Legacy Implementation (unmigrated) | `features.raid.boss_resolver` | 3 (core/asset_manager.py, scripts/generate_asset_contact_sheets.py...) | 1 (test_boss_asset_resolver.py) | High (Business logic) | Migrate to target, then convert to shim/delete |
| 10 | `calendar_models.py` | **C** | Compatibility Shim | `features.calendar.models` | 1 (scripts/t2i_preview_fixtures.py) | 2 (test_calendar_v04.py, test_calendar_v05.py) | Low (Internal legacy) | Migrate to target, then convert to shim/delete |
| 11 | `calendar_service.py` | **C** | Compatibility Shim | `features.calendar.service` | 2 (main.py, scripts/t2i_preview_fixtures.py) | 4 (test_calendar_v04.py, test_calendar_v05.py...) | Low (Internal legacy) | Migrate to target, then convert to shim/delete |
| 12 | `calendar_sources.py` | **C** | Compatibility Shim | `features.calendar.sources` | 0 (无) | 2 (test_calendar_v04.py, test_calendar_v05.py) | Low (Internal legacy) | Migrate to target, then convert to shim/delete |
| 13 | `calendar_visuals.py` | **C** | Compatibility Shim | `features.calendar.visuals` | 0 (无) | 1 (test_calendar_v05.py) | Low (Internal legacy) | Migrate to target, then convert to shim/delete |
| 14 | `campaign_history_builder.py` | **C** | Compatibility Shim | `features.campaign.builder` | 3 (main.py, scripts/capture_campaign_history.py...) | 1 (test_campaign_history.py) | Low (Internal legacy) | Migrate to target, then convert to shim/delete |
| 15 | `campaign_history_models.py` | **C** | Compatibility Shim | `features.campaign.models` | 4 (main.py, ui/campaign.py...) | 2 (test_campaign_history.py, test_campaign_resource_wiring.py) | Low (Internal legacy) | Migrate to target, then convert to shim/delete |
| 16 | `campaign_history_renderer.py` | **C** | Compatibility Shim | `ui.renderers.campaign` | 1 (scripts/preview_ui_v03.py) | 3 (test_campaign_history.py, test_campaign_resource_wiring.py...) | Low (Internal legacy) | Migrate to target, then convert to shim/delete |
| 17 | `campaign_stage_resolver.py` | **C** | Compatibility Shim | `features.campaign.stage_resolver` | 3 (main.py, scripts/capture_campaign_history.py...) | 4 (test_campaign_history.py, test_core.py...) | Low (Internal legacy) | Migrate to target, then convert to shim/delete |
| 18 | `canonical_models.py` | **C** | Legacy Implementation (unmigrated) | `features.calendar.canonical_models` | 0 (无) | 1 (test_schedule_data_layer.py) | High (Business logic) | Migrate to target, then convert to shim/delete |
| 19 | `card_builder.py` | **C** | Compatibility Shim | `features.character.builder` | 3 (main.py, scripts/audit_all_spine_runtime_resolution.py...) | 5 (test_card_builder.py, test_costume_selection.py...) | Low (Internal legacy) | Migrate to target, then convert to shim/delete |
| 20 | `card_models.py` | **C** | Compatibility Shim | `features.character.models` | 5 (core/asset_manager.py, ui/character.py...) | 7 (test_character_card_renderer.py, test_character_replica.py...) | Low (Internal legacy) | Migrate to target, then convert to shim/delete |
| 21 | `card_theme.py` | **C** | Compatibility Shim | `ui.theme` | 0 (无) | 4 (test_character_card_renderer.py, test_theme_and_profile.py...) | Low (Internal legacy) | Migrate to target, then convert to shim/delete |
| 22 | `cdk_models.py` | **C** | Compatibility Shim | `features.cdk.models` | 0 (无) | 3 (test_cdk.py, test_cdk_persistence.py...) | Low (Internal legacy) | Migrate to target, then convert to shim/delete |
| 23 | `cdk_service.py` | **C** | Compatibility Shim | `features.cdk.service` | 1 (main.py) | 4 (test_cdk.py, test_cdk_persistence.py...) | Low (Internal legacy) | Migrate to target, then convert to shim/delete |
| 24 | `character_card_renderer.py` | **HISTORICAL / DELETED** | Retired legacy single-character renderer and shim | None | 0 current production refs | 0 current test refs | No compatibility surface retained | Deleted by PR #103; current white vertical T2I replica is the sole production character-card path |
| 25 | `character_crop.py` | **C** | Legacy Implementation (unmigrated) | `features.character.crop` | 0 (无) | 1 (test_character_crop.py) | High (Business logic) | Migrate to target, then convert to shim/delete |
| 26 | `character_detail_diagnostic.py` | **C** | Compatibility Shim | `features.character.diagnostic` | 1 (scripts/diagnose_character_details.py) | 1 (test_character_detail_diagnostic.py) | Low (Internal legacy) | Migrate to target, then convert to shim/delete |
| 27 | `character_identity.py` | **C** | Compatibility Shim | `features.character.identity` | 2 (main.py, scripts/benchmark_measurements.py) | 1 (test_character_identity.py) | Low (Internal legacy) | Migrate to target, then convert to shim/delete |
| 28 | `character_master_resolver.py` | **C** | Compatibility Shim | `features.character.master_resolver` | 6 (core/asset_manager.py, integrations/provider.py...) | 2 (test_character_master.py, test_eunhwa_tactical_upgrade_portrait.py) | Low (Internal legacy) | Migrate to target, then convert to shim/delete |
| 29 | `character_replica.py` | **C** | Compatibility Shim | `features.character.replica` | 0 (无) | 1 (test_character_replica.py) | Low (Internal legacy) | Migrate to target, then convert to shim/delete |
| 30 | `character_stat_calculator.py` | **C** | Compatibility Shim | `features.character.stat_calculator` | 0 (无) | 2 (test_arcana_game_panel.py, test_character_stat_calculator.py) | Low (Internal legacy) | Migrate to target, then convert to shim/delete |
| 31 | `character_stat_resources.py` | **C** | Compatibility Shim | `features.character.stat_resources` | 1 (main.py) | 1 (test_character_stat_resources.py) | Low (Internal legacy) | Migrate to target, then convert to shim/delete |
| 32 | `character_visual_resolver.py` | **C** | Legacy Implementation (unmigrated) | `features.character.visual_resolver` | 2 (core/asset_manager.py, scripts/build_character_asset_contact_sheet.py) | 2 (test_character_visual_resolver.py, test_spine_placement.py) | High (Business logic) | Migrate to target, then convert to shim/delete |
| 33 | `character_weapon_bases.py` | **C** | Legacy Implementation (unmigrated) | `features.character.weapon_bases` | 3 (core/asset_manager.py, features/builder.py...) | 0 (无) | High (Business logic) | Migrate to target, then convert to shim/delete |
| 34 | `client.py` | **C** | Compatibility Shim | `integrations.blablalink.client` | 6 (main.py, features/service.py...) | 17 (test_bind_tutorial.py, test_campaign_history.py...) | Low (Internal legacy) | Migrate to target, then convert to shim/delete |
| 35 | `container.py` | **A** | DI Container Shim/Entrypoint | `core.container` | 1 (main.py) | 1 (test_main_refactor_integrity.py) | Critical (Plugin Failure) | Keep at root |
| 36 | `cookie_utils.py` | **A** | Compatibility Shim | `core.cookie_utils` | 1 (core/storage.py) | 1 (test_cookie_utils.py) | Low (Internal legacy) | Keep at root |
| 37 | `costume_asset_resolver.py` | **C** | Legacy Implementation (unmigrated) | `features.character.costume_asset_resolver` | 2 (core/asset_manager.py, scripts/audit_assets.py) | 1 (test_costume_asset_resolver.py) | High (Business logic) | Migrate to target, then convert to shim/delete |
| 38 | `costume_registry.py` | **C** | Compatibility Shim | `features.character.registries.costume` | 3 (main.py, scripts/capture_campaign_history.py...) | 3 (test_costume_registry.py, test_features_refactor_integrity.py...) | Low (Internal legacy) | Migrate to target, then convert to shim/delete |
| 39 | `currency_registry.py` | **C** | Legacy Implementation (unmigrated) | `features.profile.currency_registry` | 3 (core/asset_manager.py, features/builder.py...) | 2 (test_profile_v04_campaign_and_manifest.py, test_t2i_presentation_refinements.py) | High (Business logic) | Migrate to target, then convert to shim/delete |
| 40 | `daily_models.py` | **C** | Compatibility Shim | `features.daily.models` | 1 (main.py) | 3 (test_daily_auto.py, test_daily_recovery.py...) | Low (Internal legacy) | Migrate to target, then convert to shim/delete |
| 41 | `daily_runner.py` | **C** | Compatibility Shim | `features.daily.runner` | 1 (main.py) | 1 (test_main_refactor_integrity.py) | Low (Internal legacy) | Migrate to target, then convert to shim/delete |
| 42 | `face_anchor.py` | **C** | Legacy Implementation (unmigrated) | `features.character.face_anchor` | 1 (features/replica.py) | 1 (test_face_anchor.py) | High (Business logic) | Migrate to target, then convert to shim/delete |
| 43 | `fetch_client.py` | **C** | Compatibility Shim | `integrations.blablalink.fetch_client` | 0 (无) | 1 (test_schedule_data_layer.py) | Low (Internal legacy) | Migrate to target, then convert to shim/delete |
| 44 | `guide_registry.py` | **C** | Compatibility Shim | `features.guide.registry` | 2 (main.py, scripts/preview_ui_v03.py) | 1 (test_guide_registry.py) | Low (Internal legacy) | Migrate to target, then convert to shim/delete |
| 45 | `idle_animation_resolver.py` | **C** | Compatibility Shim | `integrations.spine.idle_resolver` | 1 (core/asset_manager.py) | 1 (test_idle_animation_resolver.py) | Low (Internal legacy) | Migrate to target, then convert to shim/delete |
| 46 | `lineup_portrait_resolver.py` | **C** | Legacy Implementation (unmigrated) | `features.character.lineup_portrait_resolver` | 2 (core/asset_manager.py, scripts/generate_asset_contact_sheets.py) | 1 (test_lineup_portrait_resolver.py) | High (Business logic) | Migrate to target, then convert to shim/delete |
| 47 | `local_spine_resolver.py` | **C** | Compatibility Shim | `integrations.spine.local_resolver` | 1 (scripts/sync_spine_assets.py) | 1 (test_local_spine_resolver.py) | Low (Internal legacy) | Migrate to target, then convert to shim/delete |
| 48 | `log_privacy.py` | **C** | Compatibility Shim | `core.privacy` | 5 (main.py, features/service.py...) | 1 (test_log_privacy.py) | Low (Internal legacy) | Migrate to target, then convert to shim/delete |
| 49 | `main.py` | **A** | Official Entrypoint | `-` | 0 (无) | 28 (test_announcements.py, test_announcement_push_wiring.py...) | Critical (Plugin Failure) | Keep at root |
| 50 | `memorial_registry.py` | **A** | Compatibility Shim | `features.character.registries.memorial` | 0 (无) | 1 (test_profile_v04.py) | Low (Internal legacy) | Keep at root |
| 51 | `nikke_db_provider.py` | **A** | Compatibility Shim | `integrations.nikke_db.provider` | 2 (core/asset_manager.py, scripts/audit_all_spine_runtime_resolution.py) | 5 (test_all_default_portrait_resolution.py, test_all_verified_costume_resolution.py...) | Low (Internal legacy) | Keep at root |
| 52 | `ol_unknown_inventory.py` | **C** | Legacy Implementation (unmigrated) | `features.character.ol_unknown_inventory` | 1 (features/builder.py) | 1 (test_ol_unknown_inventory.py) | High (Business logic) | Migrate to target, then convert to shim/delete |
| 53 | `overload_tier_registry.py` | **C** | Compatibility Shim | `features.character.registries.overload` | 0 (无) | 1 (test_overload_tier_registry.py) | Low (Internal legacy) | Migrate to target, then convert to shim/delete |
| 54 | `processing_feedback.py` | **C** | Compatibility Shim | `core.feedback` | 1 (main.py) | 1 (test_feedback_and_voice.py) | Low (Internal legacy) | Migrate to target, then convert to shim/delete |
| 55 | `profile_builder.py` | **C** | Compatibility Shim | `features.profile.builder` | 2 (main.py, scripts/t2i_preview_fixtures.py) | 7 (test_live_rc_profile_stabilization.py, test_profile_structured.py...) | Low (Internal legacy) | Migrate to target, then convert to shim/delete |
| 56 | `profile_card_renderer.py` | **C** | Compatibility Shim | `ui.renderers.profile` | 1 (scripts/preview_ui_v03.py) | 7 (test_live_rc_profile_stabilization.py, test_profile_structured.py...) | Low (Internal legacy) | Migrate to target, then convert to shim/delete |
| 57 | `profile_models.py` | **C** | Compatibility Shim | `features.profile.models` | 2 (ui/profile.py, scripts/preview_ui_v03.py) | 4 (test_profile_v04.py, test_profile_v04_campaign_and_manifest.py...) | Low (Internal legacy) | Migrate to target, then convert to shim/delete |
| 58 | `raid_participants.py` | **C** | Compatibility Shim | `features.raid.participants` | 2 (main.py, scripts/t2i_preview_fixtures.py) | 2 (test_raid_increment_a.py, test_raid_participants.py) | Low (Internal legacy) | Migrate to target, then convert to shim/delete |
| 59 | `renderer.py` | **C** | Compatibility Shim | `ui.primitives` | 2 (main.py, scripts/preview_ui_v03.py) | 2 (test_core.py, test_ui_refactor_integrity.py) | Low (Internal legacy) | Migrate to target, then convert to shim/delete |
| 60 | `research_registry.py` | **C** | Compatibility Shim | `features.character.registries.research` | 1 (ui/profile.py) | 1 (test_profile_v04.py) | Low (Internal legacy) | Migrate to target, then convert to shim/delete |
| 61 | `runtime_config.py` | **C** | Compatibility Shim | `core.config` | 1 (main.py) | 1 (test_runtime_config.py) | Low (Internal legacy) | Migrate to target, then convert to shim/delete |
| 62 | `runtime_health.py` | **C** | Compatibility Shim | `core.health` | 1 (main.py) | 1 (test_runtime_health.py) | Low (Internal legacy) | Migrate to target, then convert to shim/delete |
| 63 | `schedule_adapters.py` | **C** | Legacy Implementation (unmigrated) | `features.calendar.schedule_adapters` | 0 (无) | 1 (test_schedule_data_layer.py) | High (Business logic) | Migrate to target, then convert to shim/delete |
| 64 | `schedule_service.py` | **C** | Legacy Implementation (unmigrated) | `features.calendar.schedule_service` | 0 (无) | 1 (test_schedule_data_layer.py) | High (Business logic) | Migrate to target, then convert to shim/delete |
| 65 | `skill_icon_resolver.py` | **C** | Legacy Implementation (unmigrated) | `features.character.skill_icon_resolver` | 2 (core/asset_manager.py, scripts/audit_assets.py) | 1 (test_skill_icon_resolver.py) | High (Business logic) | Migrate to target, then convert to shim/delete |
| 66 | `spine_placement.py` | **C** | Compatibility Shim | `integrations.spine.placement` | 2 (scripts/benchmark_spine_placement.py, scripts/build_character_placement_meta.py) | 1 (test_spine_placement.py) | Low (Internal legacy) | Migrate to target, then convert to shim/delete |
| 67 | `spine_prerenderer.py` | **C** | Compatibility Shim | `integrations.spine.prerenderer` | 3 (core/asset_manager.py, integrations/local_resolver.py...) | 6 (test_core_integrations_refactor_integrity.py, test_profile_v04_campaign_and_manifest.py...) | Low (Internal legacy) | Migrate to target, then convert to shim/delete |
| 68 | `spine_renderer.py` | **C** | Compatibility Shim | `integrations.spine.renderer` | 1 (scripts/benchmark_spine_placement.py) | 1 (test_spine_runtime.py) | Low (Internal legacy) | Migrate to target, then convert to shim/delete |
| 69 | `spine_runtime.py` | **C** | Compatibility Shim | `integrations.spine.runtime` | 7 (main.py, integrations/renderer.py...) | 3 (test_spine_runtime.py, test_spine_runtime_worker.py...) | Low (Internal legacy) | Migrate to target, then convert to shim/delete |
| 70 | `spine_runtime_config.py` | **C** | Compatibility Shim | `integrations.spine.config` | 1 (main.py) | 1 (test_spine_runtime_config.py) | Low (Internal legacy) | Migrate to target, then convert to shim/delete |
| 71 | `spine_runtime_worker.py` | **C** | Compatibility Shim | `integrations.spine.worker_caller` | 0 (无) | 1 (test_spine_runtime_worker.py) | Low (Internal legacy) | Migrate to target, then convert to shim/delete |
| 72 | `spine_semantic_mapper.py` | **C** | Compatibility Shim | `integrations.spine.semantic_mapper` | 2 (scripts/benchmark_spine_placement.py, scripts/build_spine_semantics.py) | 1 (test_spine_semantics.py) | Low (Internal legacy) | Migrate to target, then convert to shim/delete |
| 73 | `state_effect_registry.py` | **C** | Compatibility Shim | `features.character.registries.state_effect` | 0 (无) | 1 (test_state_effect_registry.py) | Low (Internal legacy) | Migrate to target, then convert to shim/delete |
| 74 | `static_registry.py` | **C** | Compatibility Shim | `features.character.registries.static` | 1 (core/asset_manager.py) | 2 (test_static_registry.py, test_t2i_presentation_refinements.py) | Low (Internal legacy) | Migrate to target, then convert to shim/delete |
| 75 | `storage.py` | **C** | Compatibility Shim | `core.storage` | 7 (main.py, core/container.py...) | 15 (test_announcement_delivery.py, test_announcement_push_wiring.py...) | Low (Internal legacy) | Migrate to target, then convert to shim/delete |
| 76 | `t2i_assets.py` | **C** | Legacy Implementation (unmigrated) | `ui.t2i_assets` | 2 (ui/t2i.py, scripts/preview_replica.py) | 3 (test_t2i_asset_integration.py, test_t2i_campaign.py...) | High (Business logic) | Migrate to target, then convert to shim/delete |
| 77 | `t2i_payloads.py` | **C** | Legacy Implementation (unmigrated) | `ui.t2i_payloads` | 4 (main.py, ui/t2i.py...) | 5 (test_character_pixel_calibration.py, test_t2i_asset_integration.py...) | High (Business logic) | Migrate to target, then convert to shim/delete |
| 78 | `t2i_renderer.py` | **C** | Compatibility Shim | `ui.renderers.t2i` | 2 (scripts/preview_t2i_frontend.py, scripts/preview_t2i_ui.py) | 3 (test_t2i_campaign.py, test_t2i_frontend.py...) | Low (Internal legacy) | Migrate to target, then convert to shim/delete |
| 79 | `t2i_templates.py` | **C** | Legacy Implementation (unmigrated) | `ui.t2i_templates` | 2 (ui/t2i.py, scripts/preview_replica.py) | 5 (test_character_pixel_calibration.py, test_t2i_asset_integration.py...) | High (Business logic) | Migrate to target, then convert to shim/delete |
| 80 | `tarot_models.py` | **C** | Compatibility Shim | `features.tarot.models` | 0 (无) | 1 (test_tarot_service.py) | Low (Internal legacy) | Migrate to target, then convert to shim/delete |
| 81 | `tarot_service.py` | **C** | Compatibility Shim | `features.tarot.service` | 1 (main.py) | 2 (test_features_refactor_integrity.py, test_tarot_service.py) | Low (Internal legacy) | Migrate to target, then convert to shim/delete |
| 82 | `tower_registry.py` | **C** | Compatibility Shim | `features.tower.registry` | 1 (main.py) | 2 (test_t2i_presentation_refinements.py, test_tower_registry.py) | Low (Internal legacy) | Migrate to target, then convert to shim/delete |
| 83 | `union_raid_builder.py` | **C** | Compatibility Shim | `features.raid.builder` | 2 (main.py, scripts/t2i_preview_fixtures.py) | 4 (test_overnight_contracts.py, test_raid_increment_a.py...) | Low (Internal legacy) | Migrate to target, then convert to shim/delete |
| 84 | `union_raid_models.py` | **C** | Compatibility Shim | `features.raid.models` | 3 (main.py, ui/raid.py...) | 3 (test_raid_increment_a.py, test_union_raid.py...) | Low (Internal legacy) | Migrate to target, then convert to shim/delete |
| 85 | `union_raid_renderer.py` | **C** | Compatibility Shim | `ui.renderers.raid` | 1 (scripts/preview_ui_v03.py) | 3 (test_raid_increment_a.py, test_ui_refactor_integrity.py...) | Low (Internal legacy) | Migrate to target, then convert to shim/delete |
| 86 | `voice_audio.py` | **C** | Compatibility Shim | `features.voice.audio` | 2 (main.py, scripts/benchmark_measurements.py) | 2 (test_voice_audio.py, test_voice_character_and_costume.py) | Low (Internal legacy) | Migrate to target, then convert to shim/delete |
| 87 | `voice_character_resolver.py` | **C** | Compatibility Shim | `features.voice.character_resolver` | 1 (main.py) | 2 (test_character_identity.py, test_voice_character_and_costume.py) | Low (Internal legacy) | Migrate to target, then convert to shim/delete |
| 88 | `voice_encoder.py` | **C** | Compatibility Shim | `features.voice.encoder` | 1 (main.py) | 1 (test_voice_encoder.py) | Low (Internal legacy) | Migrate to target, then convert to shim/delete |
| 89 | `voice_feedback.py` | **C** | Compatibility Shim | `features.voice.feedback` | 0 (无) | 2 (test_feedback_and_voice.py, test_voice_character_and_costume.py) | Low (Internal legacy) | Migrate to target, then convert to shim/delete |
| 90 | `voice_mapping.py` | **C** | Compatibility Shim | `features.voice.mapping` | 1 (main.py) | 2 (test_voice_audio.py, test_voice_mapping.py) | Low (Internal legacy) | Migrate to target, then convert to shim/delete |
| 91 | `voice_pipeline.py` | **C** | Compatibility Shim | `features.voice.pipeline` | 1 (main.py) | 1 (test_voice_pipeline.py) | Low (Internal legacy) | Migrate to target, then convert to shim/delete |
| 92 | `voice_resource_provider.py` | **C** | Compatibility Shim | `features.voice.provider` | 2 (main.py, scripts/benchmark_measurements.py) | 1 (test_voice_resource_provider.py) | Low (Internal legacy) | Migrate to target, then convert to shim/delete |
| 93 | `voice_scene_catalog.py` | **C** | Compatibility Shim | `features.voice.scene_catalog` | 0 (无) | 1 (test_voice_scene_catalog.py) | Low (Internal legacy) | Migrate to target, then convert to shim/delete |
| 94 | `web_service.py` | **C** | Compatibility Shim | `integrations.web.service` | 2 (main.py, scripts/preview_ui_v03.py) | 5 (test_bind_tutorial.py, test_configuration.py...) | Low (Internal legacy) | Migrate to target, then convert to shim/delete |

---

## 三、两阶段清理落地规划 (PR A & PR B)

### 阶段一：遗留实现沉降与全库引用解耦 (Phase 2 & PR A 前置)
1. 将 16 个 Category C 遗留实现模块完整迁移至对应的领域包：
   - 角色/战力模块 (`character_visual_resolver`, `character_crop`, `character_weapon_bases`, `costume_asset_resolver`, `lineup_portrait_resolver`, `skill_icon_resolver`, `face_anchor`, `ol_unknown_inventory`) -> `features/character/`
   - 突袭模块 (`boss_asset_resolver`) -> `features/raid/`
   - 日程模块 (`canonical_models`, `schedule_adapters`, `schedule_service`) -> `features/calendar/`
   - 资料模块 (`currency_registry`) -> `features/profile/`
   - T2I 渲染辅助 (`t2i_assets`, `t2i_payloads`, `t2i_templates`) -> `ui/renderers/` 或 `ui/t2i/`
2. 批量将 `main.py`、各领域模块及 `tests/` 中的旧根路径引用切换至正式分层包。

### 阶段二：PR A (refactor/root-shim-cleanup-a)
- 目标：删除首批 60%–80% 的根目录 shim。
- 范围：所有无外部公开契约依赖且内部引用已清空的 shim（Category D 及清理后的 Category B/C 存根，共计约 60–70 个）。
- 门禁：全套 pytest、node extension、编译及导入测试全绿。

### 阶段三：PR B (refactor/root-shim-cleanup-b)
- 目标：完成根目录终态收敛。
- 范围：二次审计确认剩余 shim，除核心入口 (`main.py`, `__init__.py`, `_version.py`, `container.py`) 外，清理全部无公开价值的残余 shim。
- 门禁：更新 `test_repository_integrity.py`，加入 `forbidden_legacy_root_modules` 白名单/黑名单校验，确保根目录保持干净。

---

## 四、执行结果总结 (Execution Status)

| 阶段 | PR / 动作 | 涉及模块数 | 结果 | 门禁验证 |
| :---: | :--- | :---: | :---: | :--- |
| **Phase 2** | 16 个遗留实现沉降至各领域包 | 16 | 已完成并经回归测试验证 | 编译通过，全量引用就地解耦 |
| **Phase 3** | PR A (`#92`): 首批根目录存根清理 | 61 | 已合并至 `main` | 941 passed, 2 skipped, 0 failed |
| **Phase 4** | PR B: 根目录终态收敛 (清理剩余 29 个存根) | 29 | 已完成并经回归测试验证 | 942 passed, 2 skipped, 0 failed |
| **终态** | 根目录只保留 4 个核心入口文件 | 4 (`main.py`, `__init__.py`, `_version.py`, `container.py`) | 达到目标终态 | 4/4 仅留必要入口，`FORBIDDEN_LEGACY_ROOT_MODULES` 全绿 |

# R21 后续复核（2026-09-23）

- 删除 `experimental/spine_prerenderer.py` 及其空包 `experimental/__init__.py`：全仓 Python/测试/脚本/扩展/动态导入审计仅发现模块自身和历史审计/验收文档提及；正式唯一实现为 `integrations/spine/prerenderer.py`。`enqueue_experimental_spine()` 与 `SpineAssetService.enqueue_experimental()` 仅互相转发，没有生产或测试调用点，已随之删除。静态读取与正式受控预渲染实现保留。
- 删除 `ProfileDashboardData.memorial_summary_dict`、`MemorialCategoryRegistry.summarize_memorials()` 以及 renderer 对 dict 摘要和字符串模拟室记录的分支。消费者审计仅发现 builder/renderer 之间的旧 DTO 通路和 `tests/test_profile_v04.py` 手工夹具；builder 已同时产出结构化 `memorial_summary`，现由唯一结构化 `summarize()` 提供展示摘要并保留未知/部分语义。
- 保留 `container.py` 根级公开转发 shim：代码显式标注 deprecated 且发出 `DeprecationWarning`；唯一目的为历史 `ServiceContainer`/`create_container` 导入兼容，不重复装配。正式 owner 是 `core/container.py`；在 `tests/test_repository_integrity.py` 作为唯一显式例外验证，计划于 `1.0.0` 移除。仓库外当前使用量不可由本地审计证明，因此不宣称有活跃外部调用方。
