# SPDX-License-Identifier: GPL-3.0-or-later
"""验证 Features 领域模块化及根目录兼容性 shim 的完整性与一致性。"""

import pytest


def test_features_domains_importable():
    from astrbot_plugin_nikke.features.announcement.service import AnnouncementService
    from astrbot_plugin_nikke.features.campaign.builder import CampaignHistoryBuilder
    from astrbot_plugin_nikke.features.cdk.service import CdkService
    from astrbot_plugin_nikke.features.character.builder import CharacterCardBuilder
    from astrbot_plugin_nikke.features.character.registries.costume import CostumeRegistry
    from astrbot_plugin_nikke.features.daily.models import DailyTaskResult
    from astrbot_plugin_nikke.features.guide.registry import GuideRegistry
    from astrbot_plugin_nikke.features.profile.builder import ProfileBuilder
    from astrbot_plugin_nikke.features.raid.builder import UnionRaidBuilder
    from astrbot_plugin_nikke.features.tower.registry import TowerRegistry
    from astrbot_plugin_nikke.features.voice.character_resolver import VoiceCharacterResolver
    from astrbot_plugin_nikke.features.tarot.service import TarotService
    from astrbot_plugin_nikke.features.calendar.service import CalendarService

    assert AnnouncementService is not None
    assert CampaignHistoryBuilder is not None
    assert CdkService is not None
    assert CharacterCardBuilder is not None
    assert CostumeRegistry is not None
    assert DailyTaskResult is not None
    assert GuideRegistry is not None
    assert ProfileBuilder is not None
    assert UnionRaidBuilder is not None
    assert TowerRegistry is not None
    assert VoiceCharacterResolver is not None
    assert TarotService is not None
    assert CalendarService is not None


def test_features_root_isolation():
    # 验证旧根目录垫片已被彻底收敛，不再暴露于包根
    legacy_feature_shims = [
        "announcement_service",
        "card_builder",
        "tarot_service",
        "calendar_service",
        "cdk_service",
        "costume_registry",
        "profile_builder",
        "union_raid_builder",
        "campaign_history_builder",
        "daily_runner",
    ]
    for shim in legacy_feature_shims:
        with pytest.raises(ModuleNotFoundError):
            __import__(f"astrbot_plugin_nikke.{shim}")

