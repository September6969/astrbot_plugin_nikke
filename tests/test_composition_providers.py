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


def test_voice_provider_warns_once_and_notices_when_tools_missing(tmp_path, monkeypatch, caplog) -> None:
    # PR-6A G4-voice-a：缺 ffmpeg/ffprobe 时启动 WARNING 点名缺失工具，“语音 开”照常保存并提示。
    import logging

    import astrbot_plugin_nikke.core.providers.voice as voice_provider

    class FakeVoiceStore:
        def __init__(self) -> None:
            self.settings = {}

        def get_setting(self, key, default=None):
            return self.settings.get(key, default)

        def set_setting(self, key, value):
            self.settings[key] = value

    monkeypatch.setattr(voice_provider.shutil, "which", lambda name: None if name == "ffprobe" else f"/usr/bin/{name}")
    store = FakeVoiceStore()
    with caplog.at_level(logging.WARNING, logger="astrbot_plugin_nikke"):
        application = create_voice_application(
            Path(__file__).resolve().parents[1],
            tmp_path,
            settings_store=store,
            task_factory=lambda coro: None,
            config={},
        )
    warnings = [record.getMessage() for record in caplog.records if "PATH" in record.getMessage()]
    assert len(warnings) == 1
    assert "ffprobe" in warnings[0] and "ffmpeg/" not in warnings[0]
    assert "仅能播放本地登记音频" in warnings[0]
    assert application._pipeline is None

    result = application.update_settings("aiocqhttp", "actor-1", "开")
    assert result.startswith("互动语音：开启")
    assert "提示：当前部署缺少 ffprobe" in result
    assert next(iter(store.settings.values()))["enabled"] is True

    monkeypatch.setattr(voice_provider.shutil, "which", lambda name: None)
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="astrbot_plugin_nikke"):
        create_voice_application(
            Path(__file__).resolve().parents[1],
            tmp_path,
            settings_store=FakeVoiceStore(),
            task_factory=lambda coro: None,
            config={},
        )
    message = next(record.getMessage() for record in caplog.records if "PATH" in record.getMessage())
    assert "ffmpeg/ffprobe" in message and "仅 WAV 可用" in message


def test_voice_provider_is_silent_when_tools_present(tmp_path, monkeypatch, caplog) -> None:
    import logging

    import astrbot_plugin_nikke.core.providers.voice as voice_provider

    monkeypatch.setattr(voice_provider.shutil, "which", lambda name: f"/usr/bin/{name}")
    with caplog.at_level(logging.WARNING, logger="astrbot_plugin_nikke"):
        application = create_voice_application(
            Path(__file__).resolve().parents[1],
            tmp_path,
            settings_store=type("S", (), {"get_setting": lambda self, k, d=None: d, "set_setting": lambda self, k, v: None})(),
            task_factory=lambda coro: None,
            config={},
        )
    assert not [record for record in caplog.records if "PATH" in record.getMessage()]
    assert "提示" not in application.update_settings("aiocqhttp", "actor-1", "开")
