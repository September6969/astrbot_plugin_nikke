from __future__ import annotations

from pathlib import Path

from astrbot_plugin_nikke.core.providers.account import create_account_application
from astrbot_plugin_nikke.core.providers.storage import create_nikke_store
from astrbot_plugin_nikke.core.providers.voice import create_voice_application


class FakeAccountStore:
    def __init__(self) -> None:
        self.created_sessions: list[tuple[str, str, int, str]] = []

    def create_bind_session(
        self, token: str, qq_id: str, ttl: int = 600, *, status: str
    ) -> None:
        self.created_sessions.append((token, qq_id, ttl, status))


def test_account_provider_accepts_a_fake_store_without_constructing_plugin() -> None:
    store = FakeAccountStore()
    application = create_account_application(
        store, token_factory=lambda _: "test-token"
    )

    url = application.create_binding_url("qq-123", "https://example.test/")

    assert url == "https://example.test/bind/test-token"
    assert store.created_sessions == [
        ("test-token", "qq-123", 600, "pending")
    ]


def test_storage_provider_accepts_a_store_factory_without_plugin_assembly(
    tmp_path,
) -> None:
    fake_store = object()
    calls = []

    def store_factory(data_dir):
        calls.append(data_dir)
        return fake_store

    result = create_nikke_store(tmp_path / "data", store_factory=store_factory)

    assert result is fake_store
    assert calls == [tmp_path / "data"]
    assert (tmp_path / "data").is_dir()


def test_voice_provider_uses_fake_settings_port_without_plugin(tmp_path) -> None:
    class FakeVoiceStore:
        def __init__(self) -> None:
            self.settings = {}

        def get_setting(self, key, default=None):
            return self.settings.get(key, default)

        def set_setting(self, key, value):
            self.settings[key] = value

    store = FakeVoiceStore()
    plugin_dir = Path(__file__).resolve().parents[1]
    application = create_voice_application(
        plugin_dir,
        tmp_path,
        settings_store=store,
        task_factory=lambda coro: None,
        config={},
    )

    result = application.update_settings("qq", "actor-1", "开")

    assert result.startswith("互动语音：开启")
    assert len(store.settings) == 1
    assert next(iter(store.settings.values()))["enabled"] is True
