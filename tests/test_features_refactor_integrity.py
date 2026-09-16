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


def test_root_shims_features_identity():
    import astrbot_plugin_nikke.announcement_service as ann_svc
    from astrbot_plugin_nikke.features.announcement.service import AnnouncementService
    assert ann_svc.AnnouncementService is AnnouncementService

    import astrbot_plugin_nikke.card_builder as card_bld
    from astrbot_plugin_nikke.features.character.builder import CharacterCardBuilder
    assert card_bld.CharacterCardBuilder is CharacterCardBuilder

    import astrbot_plugin_nikke.tarot_service as tarot_svc
    from astrbot_plugin_nikke.features.tarot.service import TarotService
    assert tarot_svc.TarotService is TarotService

    import astrbot_plugin_nikke.calendar_service as cal_svc
    from astrbot_plugin_nikke.features.calendar.service import CalendarService
    assert cal_svc.CalendarService is CalendarService

    import astrbot_plugin_nikke.cdk_service as cdk_svc
    from astrbot_plugin_nikke.features.cdk.service import CdkService
    assert cdk_svc.CdkService is CdkService

    import astrbot_plugin_nikke.costume_registry as cos_reg
    from astrbot_plugin_nikke.features.character.registries.costume import CostumeRegistry
    assert cos_reg.CostumeRegistry is CostumeRegistry
