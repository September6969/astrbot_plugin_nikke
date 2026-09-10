"""本地测试音频及 OneBot 通知过滤；不进行真实消息发送。"""
import json
import tempfile
from pathlib import Path
from unittest import IsolatedAsyncioTestCase
from astrbot_plugin_nikke.voice_audio import VoiceAudioCache, VoicePreference, is_self_poke
from astrbot_plugin_nikke.storage import NikkeStore


class VoiceAudioTests(IsolatedAsyncioTestCase):
    async def test_invalid_and_overlong_wav_are_not_cached(self):
        import wave
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            row = dict(character="rapi", locale="ja", file="test.wav", source="synthetic", license="self")
            (root / "registry.json").write_text(json.dumps([row]), encoding="utf-8")
            (root / "test.wav").write_bytes(b"RIFF0000WAVEbroken")
            cache = VoiceAudioCache(root, root / "cache")
            self.assertIsNone(await cache.resolve(VoicePreference(True)))
            with wave.open(str(root / "test.wav"), "wb") as audio:
                audio.setnchannels(1)
                audio.setsampwidth(1)
                audio.setframerate(8000)
                audio.writeframes(b"\0" * (8000 * 31))
            self.assertIsNone(await cache.resolve(VoicePreference(True)))
            self.assertFalse(list((root / "cache").glob("*.wav")))

    async def test_cache_and_preferences(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = NikkeStore(root / "store")
            preference = VoicePreference(True)
            preference.save(store, "fake-user")
            self.assertTrue(VoicePreference.load(store, "fake-user").enabled)
            self.assertFalse(VoicePreference.load(store, "other-user").enabled)
            import wave
            with wave.open(str(root / "test.wav"), "wb") as audio:
                audio.setnchannels(1)
                audio.setsampwidth(2)
                audio.setframerate(24000)
                audio.writeframes(b"\0\0" * 240)
            row = dict(character="rapi", locale="ja", file="test.wav", source="synthetic", license="self")
            (root / "registry.json").write_text(json.dumps([row]), encoding="utf-8")
            cache = VoiceAudioCache(root, root / "cache")
            first = await cache.resolve(preference)
            self.assertTrue(first.is_file())
            self.assertEqual(first, await cache.resolve(preference))
            preference.locale = "en"
            self.assertIsNone(await cache.resolve(preference))

    def test_only_pokes_directed_at_bot(self):
        event = dict(post_type="notice", notice_type="notify", sub_type="poke", self_id="fake-bot", target_id="fake-bot", user_id="fake-user")
        self.assertTrue(is_self_poke(event))
        self.assertFalse(is_self_poke(dict(event, target_id="someone-else")))
        self.assertFalse(is_self_poke(dict(event, user_id="fake-bot")))

    async def test_listener_default_off_and_record_sender(self):
        from types import SimpleNamespace
        from unittest.mock import AsyncMock, Mock
        from astrbot_plugin_nikke.main import NikkePlugin
        with tempfile.TemporaryDirectory() as directory:
            plugin = NikkePlugin.__new__(NikkePlugin)
            plugin.store = NikkeStore(directory)
            plugin.plugin_dir = Path(directory)
            raw = dict(post_type="notice", notice_type="notify", sub_type="poke", self_id="fake-bot", target_id="fake-bot", user_id="fake-user")
            event = SimpleNamespace(message_obj=SimpleNamespace(raw_message=raw), get_platform_name=lambda: "aiocqhttp",
                get_sender_id=lambda: "fake-user", plain_result=lambda x: x, chain_result=Mock(side_effect=lambda x: x))
            self.assertEqual([x async for x in plugin.on_nikke_poke(event)], [])
            event.get_sender_id = lambda: "other-user"
            raw["user_id"] = "other-user"
            VoicePreference(True).save(plugin.store, "aiocqhttp:other-user")
            plugin._voice_audio = SimpleNamespace(resolve=AsyncMock(return_value=Path(directory) / "fake.wav"))
            self.assertEqual(len([x async for x in plugin.on_nikke_poke(event)]), 1)
            event.get_sender_id = lambda: "fake-user"
            raw["user_id"] = "fake-user"
            event.chain_result.reset_mock()
            VoicePreference(True).save(plugin.store, "aiocqhttp:fake-user")
            plugin._voice_audio = SimpleNamespace(resolve=AsyncMock(return_value=Path(directory) / "fake.wav"))
            self.assertEqual(len([x async for x in plugin.on_nikke_poke(event)]), 1)
            event.chain_result.assert_called_once()
            self.assertEqual([x async for x in plugin.on_nikke_poke(event)], [])

    async def test_listener_uses_verified_dynamic_pipeline_after_local_cache_miss(self):
        from types import SimpleNamespace
        from unittest.mock import AsyncMock, Mock
        from astrbot_plugin_nikke.main import NikkePlugin
        from astrbot_plugin_nikke.voice_mapping import VoiceMapping
        with tempfile.TemporaryDirectory() as directory:
            plugin = NikkePlugin.__new__(NikkePlugin)
            plugin.store = NikkeStore(directory)
            plugin.plugin_dir = Path(directory)
            plugin.config = {"voice_dynamic_enabled": True}
            raw = dict(post_type="notice", notice_type="notify", sub_type="poke", self_id="fake-bot", target_id="fake-bot", user_id="fake-user")
            event = SimpleNamespace(message_obj=SimpleNamespace(raw_message=raw), get_platform_name=lambda: "aiocqhttp",
                get_sender_id=lambda: "fake-user", plain_result=lambda x: x, chain_result=Mock(side_effect=lambda x: x))
            preference = VoicePreference(True, character="alice", locale="en", skin="default")
            preference.save(plugin.store, "aiocqhttp:fake-user")
            plugin._voice_audio = SimpleNamespace(resolve=AsyncMock(return_value=None))
            mock_mapping = VoiceMapping(
                "alice", "default", "c191", "en", "alice_poke", "alice_poke_01",
                "https://example.invalid/source", "https://example.invalid/map", "2026-09-08",
            )
            plugin.voice_mapping = SimpleNamespace(
                resolve=Mock(return_value=mock_mapping),
                resolve_poke=Mock(return_value=mock_mapping),
            )
            plugin.voice_pipeline = SimpleNamespace(resolve=AsyncMock(return_value=Path(directory) / "verified.wav"))
            outputs = [x async for x in plugin.on_nikke_poke(event)]
            self.assertEqual(len(outputs), 1)
            plugin.voice_pipeline.resolve.assert_awaited_once_with("alice_poke", "alice_poke_01", "en", budget=4)

    def test_voice_preference_default_locale_and_migration(self):
        import hashlib
        with tempfile.TemporaryDirectory() as directory:
            store = NikkeStore(Path(directory) / "store")
            pref = VoicePreference(True)
            self.assertEqual(pref.locale, "ja")
            self.assertFalse(pref.explicit_locale)

            # 旧版未显式设置 zh-cn 的偏好自动迁移到 ja
            store.set_setting("voice:" + hashlib.sha256(b"legacy-user").hexdigest(), {
                "enabled": True, "character": "rapi", "locale": "zh-cn", "skin": "default", "spine_asset_id": ""
            })
            loaded = VoicePreference.load(store, "legacy-user")
            self.assertEqual(loaded.locale, "ja")

            # 即使显式设置了 zh-cn，也必须严格收口迁移到 ja
            store.set_setting("voice:" + hashlib.sha256(b"explicit-zh-cn").hexdigest(), {
                "enabled": True, "character": "rapi", "locale": "zh-cn", "skin": "default", "spine_asset_id": "",
                "explicit_locale": True
            })
            loaded_explicit = VoicePreference.load(store, "explicit-zh-cn")
            self.assertEqual(loaded_explicit.locale, "ja")
            self.assertFalse(loaded_explicit.explicit_locale)

            # 未知/外部语言（如 fr）同样收口迁移到 ja
            store.set_setting("voice:" + hashlib.sha256(b"fr-user").hexdigest(), {
                "enabled": True, "character": "rapi", "locale": "fr", "skin": "default", "spine_asset_id": "",
                "explicit_locale": True
            })
            loaded_fr = VoicePreference.load(store, "fr-user")
            self.assertEqual(loaded_fr.locale, "ja")
            self.assertFalse(loaded_fr.explicit_locale)

            # 官方已验证语言 (ja, en, ko) 正常保留
            for valid_loc in ("ja", "en", "ko"):
                store.set_setting("voice:" + hashlib.sha256(f"valid-{valid_loc}".encode()).hexdigest(), {
                    "enabled": True, "character": "rapi", "locale": valid_loc, "skin": "default", "spine_asset_id": "",
                    "explicit_locale": True
                })
                loaded_valid = VoicePreference.load(store, f"valid-{valid_loc}")
                self.assertEqual(loaded_valid.locale, valid_loc)
                self.assertTrue(loaded_valid.explicit_locale)

    async def test_poke_interaction_audio_only_no_text_fallback(self):
        from types import SimpleNamespace
        from unittest.mock import AsyncMock, Mock
        from astrbot_plugin_nikke.main import NikkePlugin
        with tempfile.TemporaryDirectory() as directory:
            plugin = NikkePlugin.__new__(NikkePlugin)
            plugin.store = NikkeStore(directory)
            plugin.plugin_dir = Path(directory)
            raw = dict(post_type="notice", notice_type="notify", sub_type="poke", self_id="fake-bot", target_id="fake-bot", user_id="fake-user")
            event = SimpleNamespace(message_obj=SimpleNamespace(raw_message=raw), get_platform_name=lambda: "aiocqhttp",
                get_sender_id=lambda: "fake-user", plain_result=lambda x: x, chain_result=Mock(side_effect=lambda x: x))
            VoicePreference(True, character="rapi", locale="ja").save(plugin.store, "aiocqhttp:fake-user")
            plugin._voice_audio = SimpleNamespace(resolve=AsyncMock(return_value=None))
            plugin.voice_mapping = SimpleNamespace(resolve_poke=Mock(return_value=None))
            outputs = [x async for x in plugin.on_nikke_poke(event)]
            self.assertEqual(outputs, [], "音频解析失败时戳一戳必须不发送任何内容，禁止伪造文本台词")

    async def test_registry_json_is_cached_in_memory_and_invalidates_on_mtime(self):
        """验证 VoiceAudioCache 在 registry.json 未被修改时复用内存缓存，修改后自动重新加载。"""
        import json
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache_dir = root / "cache"
            voices_dir = root / "voices"
            voices_dir.mkdir()
            cache = VoiceAudioCache(voices_dir, cache_dir)

            registry_path = voices_dir / "registry.json"
            registry_path.write_text(json.dumps([{"character": "rapi", "license": "test", "source": "test"}]), encoding="utf-8")

            # 首次加载
            first = await cache._load_registry()
            self.assertEqual(len(first), 1)
            self.assertEqual(first[0]["character"], "rapi")

            # 在不改变 mtime 的情况下验证缓存命中（即使临时重命名或 mock）
            second = await cache._load_registry()
            self.assertIs(first, second)

            # 更新文件并修改 mtime
            import time
            time.sleep(0.05)
            registry_path.write_text(json.dumps([
                {"character": "rapi", "license": "test", "source": "test"},
                {"character": "anis", "license": "test", "source": "test"},
            ]), encoding="utf-8")

            third = await cache._load_registry()
            self.assertEqual(len(third), 2)
            self.assertIsNot(first, third)

    async def test_bounded_concurrency_and_temp_file_cleanup_for_ogg(self):
        """验证 20 个不同角色 OGG 转换任务：并发子进程数不超过配置上限、临时文件无碰撞、无残留、结果独立。"""
        import asyncio
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache_dir = root / "cache"
            voices_dir = root / "voices"
            voices_dir.mkdir()
            max_limit = 2
            cache = VoiceAudioCache(voices_dir, cache_dir, max_concurrency=max_limit)

            active_ffmpeg = 0
            peak_ffmpeg = 0
            lock = asyncio.Lock()
            temp_files_seen = set()

            registry_rows = []
            preferences = []
            for i in range(20):
                char = f"char_{i}"
                filename = f"{char}.ogg"
                ogg_path = voices_dir / filename
                ogg_path.write_bytes(b"OggSsynthetic_" + f"{i}".encode())
                registry_rows.append(dict(
                    character=char,
                    locale="ja",
                    skin="default",
                    file=filename,
                    source="test",
                    license="test",
                ))
                preferences.append(VoicePreference(True, character=char, locale="ja", skin="default"))

            (voices_dir / "registry.json").write_text(json.dumps(registry_rows), encoding="utf-8")

            class MockProcess:
                def __init__(self, target_path):
                    self.target_path = target_path
                    self.returncode = 0

                async def wait(self):
                    nonlocal active_ffmpeg, peak_ffmpeg
                    async with lock:
                        active_ffmpeg += 1
                        if active_ffmpeg > peak_ffmpeg:
                            peak_ffmpeg = active_ffmpeg
                    await asyncio.sleep(0.02)
                    Path(self.target_path).write_bytes(b"RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00\x00")
                    async with lock:
                        active_ffmpeg -= 1
                    return 0

                def kill(self):
                    self.returncode = -9

            async def mock_exec(*args, **kwargs):
                out_path = args[-1]
                temp_files_seen.add(out_path)
                return MockProcess(out_path)

            with patch("shutil.which", return_value="fake_ffmpeg"):
                with patch("asyncio.create_subprocess_exec", side_effect=mock_exec):
                    results = await asyncio.gather(*(cache.resolve(pref) for pref in preferences))

            self.assertEqual(len(results), 20)
            self.assertEqual(len(set(results)), 20, "20 个不同音频必须生成 20 个不同文件")
            self.assertTrue(all(r is not None and r.is_file() for r in results))
            self.assertLessEqual(peak_ffmpeg, max_limit, f"并发 ffmpeg 活跃峰值 ({peak_ffmpeg}) 必须 <= 配置上限 ({max_limit})")
            self.assertEqual(len(temp_files_seen), 20, "20 个临时文件必须完全独立无冲突")
            leftover_tmps = [p for p in cache_dir.glob("*") if ".tmp." in p.name]
            self.assertEqual(leftover_tmps, [], "转换完成后不得遗留临时文件")

    async def test_ogg_conversion_cancellation_kills_process_and_cleans_temp(self):
        """验证本地 OGG 转换任务被取消时，子进程被杀死且临时文件被彻底清理。"""
        import asyncio
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache_dir = root / "cache"
            voices_dir = root / "voices"
            voices_dir.mkdir()
            cache = VoiceAudioCache(voices_dir, cache_dir)
            (voices_dir / "cancel.ogg").write_bytes(b"OggSsynthetic_cancel")
            (voices_dir / "registry.json").write_text(json.dumps([
                dict(
                    character="cancel_char",
                    locale="ja",
                    skin="default",
                    file="cancel.ogg",
                    source="test",
                    license="test",
                )
            ]), encoding="utf-8")

            process_killed = False
            created_temp = []

            class SlowProcess:
                def __init__(self, target_path):
                    self.target_path = Path(target_path)
                    self.returncode = None
                    created_temp.append(self.target_path)
                    self.target_path.write_bytes(b"partial_ogg_conversion")

                async def wait(self):
                    if self.returncode is not None:
                        return self.returncode
                    await asyncio.sleep(10)
                    return 0

                def kill(self):
                    nonlocal process_killed
                    process_killed = True
                    self.returncode = -9

            async def mock_exec(*args, **kwargs):
                out_path = args[-1]
                return SlowProcess(out_path)

            pref = VoicePreference(True, character="cancel_char", locale="ja", skin="default")
            with patch("shutil.which", return_value="fake_ffmpeg"):
                with patch("asyncio.create_subprocess_exec", side_effect=mock_exec):
                    task = asyncio.create_task(cache.resolve(pref))
                    await asyncio.sleep(0.04)
                    task.cancel()
                    with self.assertRaises(asyncio.CancelledError):
                        await task

            self.assertTrue(process_killed, "任务取消时必须杀死运行中的 ffmpeg 子进程")
            self.assertTrue(len(created_temp) > 0)
            for p in created_temp:
                self.assertFalse(p.exists(), f"被取消任务的临时文件 {p} 必须被彻底删除")
