"""验证插件入口把唯一生命周期所有权交给 RuntimeCoordinator。"""

from __future__ import annotations

import ast
import asyncio
import inspect
import textwrap
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from astrbot_plugin_nikke.main import NikkePlugin


class LifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_plugin_close_delegates_to_runtime_and_tolerates_partial_init(self):
        plugin = NikkePlugin.__new__(NikkePlugin)
        plugin.runtime = SimpleNamespace(close=AsyncMock())

        await plugin.terminate()
        await plugin.close()

        self.assertEqual(plugin.runtime.close.await_count, 2)

        partial_plugin = NikkePlugin.__new__(NikkePlugin)
        await partial_plugin.close()

    async def test_runtime_coordinator_cancels_tasks_before_resource_cleanup(self):
        from astrbot_plugin_nikke.core.lifecycle.coordinator import RuntimeCoordinator

        coordinator = RuntimeCoordinator()
        events: list[str] = []
        ready = asyncio.Event()

        async def pending_job():
            try:
                await asyncio.Event().wait()
            finally:
                events.append("cancelled")

        async def start():
            coordinator.create_task(pending_job())
            ready.set()

        async def scheduler():
            await asyncio.Event().wait()

        coordinator.register_cleanup("web", lambda: events.append("web"))
        coordinator.register_cleanup("assets", lambda: events.append("assets"))
        coordinator.start(start, scheduler)
        await ready.wait()

        await asyncio.gather(coordinator.close(), coordinator.close())

        self.assertEqual(events, ["cancelled", "assets", "web"])
        self.assertEqual(coordinator.active_task_count, 0)
        self.assertTrue(coordinator.closed)

    def test_main_has_no_parallel_scheduler_or_task_factory(self):
        module = ast.parse(textwrap.dedent(inspect.getsource(NikkePlugin)))
        method_names = {
            node.name
            for node in ast.walk(module)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        self.assertTrue({"close", "terminate"}.issubset(method_names))
        self.assertTrue(
            {
                "_spawn_background_task",
                "_start_services",
                "_scheduler_loop",
                "_dispatch_announcements",
            }.isdisjoint(method_names)
        )
        self.assertFalse(
            any(
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "create_task"
                for node in ast.walk(module)
            )
        )

        init_tree = ast.parse(textwrap.dedent(inspect.getsource(NikkePlugin.__init__)))
        runtime_starts = [
            node
            for node in ast.walk(init_tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "start"
            and isinstance(node.func.value, ast.Attribute)
            and node.func.value.attr == "runtime"
        ]
        self.assertEqual(len(runtime_starts), 1)

        close_tree = ast.parse(textwrap.dedent(inspect.getsource(NikkePlugin.close)))
        self.assertTrue(
            any(
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "close"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "runtime"
                for node in ast.walk(close_tree)
            )
        )

    def test_all_runtime_background_factories_flow_through_coordinator(self):
        package = Path(__file__).resolve().parents[1]
        raw_factory_references = []
        for path in package.rglob("*.py"):
            relative = path.relative_to(package)
            if relative.parts[0] in {"tests", "scripts"}:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Attribute)
                    and node.attr == "create_task"
                    and isinstance(node.value, ast.Name)
                    and node.value.id == "asyncio"
                ):
                    raw_factory_references.append(relative.as_posix())
        self.assertEqual(
            raw_factory_references,
            ["core/lifecycle/coordinator.py"],
        )

        container = ast.parse(
            (package / "core" / "container.py").read_text(encoding="utf-8")
        )
        managed_constructors = {
            node.func.id
            for node in ast.walk(container)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in {
                "DelayedFeedbackManager",
                "VoiceResourceProvider",
                "VoicePipeline",
            }
            and any(
                keyword.arg == "task_factory"
                and isinstance(keyword.value, ast.Attribute)
                and keyword.value.attr == "create_task"
                and isinstance(keyword.value.value, ast.Name)
                and keyword.value.value.id == "runtime_coordinator"
                for keyword in node.keywords
            )
        }
        self.assertEqual(
            managed_constructors,
            {"DelayedFeedbackManager", "VoiceResourceProvider", "VoicePipeline"},
        )


if __name__ == "__main__":
    unittest.main()
