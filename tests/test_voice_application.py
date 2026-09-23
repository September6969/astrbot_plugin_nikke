"""语音应用边界的身份、偏好、去重与资源所有权合同。"""

from __future__ import annotations

import ast
import asyncio
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock

from astrbot_plugin_nikke.core.storage import NikkeStore
from astrbot_plugin_nikke.features.character.registries.costume import CostumeRegistry
from astrbot_plugin_nikke.features.voice.audio import VoicePreference
from astrbot_plugin_nikke.features.voice.character_resolver import VoiceCharacterResolver
from astrbot_plugin_nikke.features.voice.mapping import VoiceMapping
from astrbot_plugin_nikke.features.voice.application import (
    VoiceApplication,
    VoicePokeContext,
)


class VoiceApplicationTests(IsolatedAsyncioTestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.assets = Path(__file__).resolve().parents[1] / "assets"
        self.store = NikkeStore(self.root / "store")

    def _application(self, **overrides):
        dependencies = {
            "store": self.store,
            "character_resolver": VoiceCharacterResolver(self.assets),
            "costume_registry": CostumeRegistry(self.assets),
            "audio_cache": SimpleNamespace(resolve=AsyncMock(return_value=None)),
            "mapping_registry": SimpleNamespace(resolve_poke=Mock(return_value=None)),
            "pipeline": None,
            "dynamic_enabled": True,
            "directory_provider": lambda: [],
            "monotonic": Mock(return_value=100.0),
        }
        dependencies.update(overrides)
        return VoiceApplication(**dependencies)

    async def test_settings_resolve_character_and_costume_by_exact_owner(self):
        app = self._application()

        result = app.update_settings("aiocqhttp", "fake-user", "角色", "拉毗")
        self.assertIn("rapi", result)
        result = app.update_settings("aiocqhttp", "fake-user", "服装", "10005")
        self.assertIn("10005", result)
        preference = VoicePreference.load(self.store, "aiocqhttp:fake-user")
        self.assertEqual(
            (preference.character, preference.skin, preference.spine_asset_id),
            ("rapi", "10005", "c010_03"),
        )

        result = app.update_settings("aiocqhttp", "fake-user", "角色", "drake")
        self.assertIn("drake", result)
        result = app.update_settings("aiocqhttp", "fake-user", "服装", "10005")
        self.assertIn("不属于", result)
        preference = VoicePreference.load(self.store, "aiocqhttp:fake-user")
        self.assertEqual((preference.character, preference.skin), ("drake", "default"))

    async def test_settings_resolve_against_current_directory(self):
        directory = [{"character_key": "test_nikke"}]
        resolver = SimpleNamespace(
            resolve=Mock(return_value="test_nikke"),
            get_resource_id=Mock(return_value=999),
        )
        app = self._application(
            character_resolver=resolver,
            directory_provider=lambda: directory,
        )

        result = app.update_settings("aiocqhttp", "fake-user", "角色", "临时目录名")

        self.assertIn("test_nikke", result)
        resolver.resolve.assert_called_once_with("临时目录名", directory)

    async def test_poke_preserves_exact_resource_identity_through_dynamic_resolution(self):
        expected_audio = self.root / "verified.wav"
        mapping = VoiceMapping(
            "rapi", "10005", "c010_03", "en", "rapi_poke", "rapi_poke_02",
            "https://example.invalid/source", "https://example.invalid/map", "2026-09-22",
        )
        audio_cache = SimpleNamespace(resolve=AsyncMock(return_value=None))
        registry = SimpleNamespace(resolve_poke=Mock(return_value=mapping))
        pipeline = SimpleNamespace(resolve=AsyncMock(return_value=expected_audio))
        app = self._application(
            audio_cache=audio_cache,
            mapping_registry=registry,
            pipeline=pipeline,
            dynamic_enabled=True,
        )
        VoicePreference(
            enabled=True,
            character="rapi",
            locale="en",
            skin="10005",
            spine_asset_id="c010_03",
        ).save(self.store, "aiocqhttp:fake-user")

        context = VoicePokeContext(
            platform_name="aiocqhttp",
            actor_id="fake-user",
            sender_id="fake-sender",
            unified_msg_origin="group:fake-room",
            supported_platform=True,
            is_self_poke=True,
        )
        result = await app.resolve_poke(context)

        self.assertEqual(result, expected_audio)
        registry.resolve_poke.assert_called_once_with(
            "rapi", "10005", "en", spine_asset_id="c010_03"
        )
        pipeline.resolve.assert_awaited_once_with(
            "rapi_poke", "rapi_poke_02", "en", budget=4
        )

    async def test_poke_is_fail_closed_and_cooldown_applies_to_same_origin(self):
        audio_cache = SimpleNamespace(resolve=AsyncMock(return_value=self.root / "local.wav"))
        app = self._application(audio_cache=audio_cache)
        context = VoicePokeContext(
            "aiocqhttp", "fake-user", "fake-sender", "group:fake-room", True, True
        )

        self.assertIsNone(await app.resolve_poke(context))
        self.assertEqual(audio_cache.resolve.await_count, 0)
        VoicePreference(True).save(self.store, "aiocqhttp:fake-user")
        self.assertEqual(await app.resolve_poke(context), self.root / "local.wav")
        self.assertIsNone(await app.resolve_poke(context))
        self.assertEqual(audio_cache.resolve.await_count, 1)
        self.assertIsNone(await app.resolve_poke(
            VoicePokeContext("unverified", "fake-user", "fake-sender", "room", True, True)
        ))
        self.assertIsNone(await app.resolve_poke(
            VoicePokeContext("aiocqhttp", "fake-user", "fake-sender", "room", True, False)
        ))
        self.assertEqual(audio_cache.resolve.await_count, 1)

    async def test_close_delegates_pipeline_ownership_once(self):
        pipeline = SimpleNamespace(close=AsyncMock())
        provider = SimpleNamespace(close=AsyncMock())
        encoder = SimpleNamespace(close=AsyncMock())
        app = self._application(pipeline=pipeline, provider=provider, encoder=encoder)

        await app.close()
        await app.close()

        pipeline.close.assert_awaited_once()
        provider.close.assert_not_awaited()
        encoder.close.assert_not_awaited()

    async def test_close_can_retry_after_pipeline_cleanup_failure(self):
        pipeline = SimpleNamespace(
            close=AsyncMock(side_effect=[RuntimeError("close failed"), None])
        )
        app = self._application(pipeline=pipeline)

        with self.assertRaisesRegex(RuntimeError, "close failed"):
            await app.close()
        await app.close()

        self.assertEqual(pipeline.close.await_count, 2)

    async def test_dynamic_fallback_stays_disabled_when_configured_off(self):
        pipeline = SimpleNamespace(resolve=AsyncMock(return_value=self.root / "dynamic.wav"))
        registry = SimpleNamespace(resolve_poke=Mock(return_value=object()))
        app = self._application(
            audio_cache=SimpleNamespace(resolve=AsyncMock(return_value=None)),
            mapping_registry=registry,
            pipeline=pipeline,
            dynamic_enabled=False,
        )
        VoicePreference(True, character="rapi").save(self.store, "aiocqhttp:fake-user")
        context = VoicePokeContext(
            "aiocqhttp", "fake-user", "fake-user", "room", True, True
        )

        self.assertIsNone(await app.resolve_poke(context))
        registry.resolve_poke.assert_not_called()
        pipeline.resolve.assert_not_awaited()

    async def test_cancelled_local_resolution_propagates(self):
        audio_cache = SimpleNamespace(resolve=AsyncMock(side_effect=asyncio.CancelledError))
        app = self._application(audio_cache=audio_cache)
        VoicePreference(True).save(self.store, "aiocqhttp:fake-user")
        context = VoicePokeContext(
            "aiocqhttp", "fake-user", "fake-sender", "room", True, True
        )

        with self.assertRaises(asyncio.CancelledError):
            await app.resolve_poke(context)

    def test_main_delegates_voice_and_container_exposes_only_application(self):
        root = Path(__file__).resolve().parents[1]
        main_tree = ast.parse((root / "main.py").read_text(encoding="utf-8"))
        plugin_class = next(
            node for node in main_tree.body
            if isinstance(node, ast.ClassDef) and node.name == "NikkePlugin"
        )
        methods = {
            node.name: ast.unparse(node)
            for node in plugin_class.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        self.assertNotIn("resolve_voice_character", methods)
        self.assertIn("voice_event_adapter", methods["voice_settings"])
        self.assertIn("voice_event_adapter", methods["on_nikke_poke"])
        for forbidden in (
            "VoicePreference", "VoiceMapRegistry", "VoiceAudioCache",
            "Record.fromFileSystem", "resolve_poke", "resolve_by_spine_asset",
        ):
            self.assertNotIn(forbidden, methods["on_nikke_poke"])
        self.assertFalse(any(
            isinstance(node, ast.ImportFrom)
            and node.module
            and node.module.startswith("features.voice")
            for node in main_tree.body
        ))

        from dataclasses import fields
        from astrbot_plugin_nikke.core.container import ServiceContainer

        container_fields = {item.name for item in fields(ServiceContainer)}
        self.assertIn("voice_application", container_fields)
        self.assertFalse(container_fields.intersection({
            "voice_mapping", "voice_character_resolver", "costume_registry",
            "voice_audio", "voice_provider", "voice_encoder", "voice_pipeline",
        }))


if __name__ == "__main__":
    import unittest

    unittest.main()
