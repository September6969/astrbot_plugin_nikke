from __future__ import annotations

from typing import get_args, get_type_hints

from astrbot_plugin_nikke.core.lifecycle.ports import SchedulerSettingsStore
from astrbot_plugin_nikke.core.lifecycle.scheduler import RuntimeScheduler
from astrbot_plugin_nikke.features.account.application import AccountApplication
from astrbot_plugin_nikke.features.account.ports import AccountStorePort
from astrbot_plugin_nikke.features.announcement.delivery import AnnouncementDelivery
from astrbot_plugin_nikke.features.announcement.ports import AnnouncementStateStore
from astrbot_plugin_nikke.features.cdk.ports import (
    CdkAccountReader,
    CdkCommandStore,
    CdkRunStore,
)
from astrbot_plugin_nikke.features.cdk.service import CdkService
from astrbot_plugin_nikke.features.daily.ports import (
    DailyAccountReader,
    DailyCommandStore,
    DailyStore,
)
from astrbot_plugin_nikke.features.daily.runner import DailyRunner
from astrbot_plugin_nikke.features.voice.application import VoiceApplication
from astrbot_plugin_nikke.features.voice.ports import VoiceSettingsStore
from astrbot_plugin_nikke.integrations.web.ports import BindingSessionStore


def test_consumers_depend_on_their_feature_persistence_protocols() -> None:
    account_store = get_type_hints(AccountApplication.__init__)["store"]
    daily_store = get_args(get_type_hints(DailyRunner.__init__)["store"])
    announcement_store = get_type_hints(AnnouncementDelivery.__init__)["store"]
    voice_store = get_type_hints(VoiceApplication.__init__)["store"]
    scheduler_store = get_type_hints(RuntimeScheduler.__init__)["store"]
    cdk_store = get_type_hints(CdkService._redeem_persistently)["store"]

    assert account_store is AccountStorePort
    assert DailyStore in daily_store
    assert announcement_store is AnnouncementStateStore
    assert voice_store is VoiceSettingsStore
    assert scheduler_store is SchedulerSettingsStore
    assert cdk_store is CdkRunStore


def test_storage_protocols_are_structural_and_do_not_import_the_sqlite_owner() -> None:
    for protocol in (
        AccountStorePort,
        DailyStore,
        DailyCommandStore,
        AnnouncementStateStore,
        VoiceSettingsStore,
        SchedulerSettingsStore,
        BindingSessionStore,
        CdkAccountReader,
        CdkCommandStore,
        CdkRunStore,
        DailyAccountReader,
    ):
        assert getattr(protocol, "_is_protocol", False)
        assert not any(
            getattr(base, "__module__", "").endswith("core.storage")
            for base in protocol.__mro__
        )
