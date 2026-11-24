# SPDX-License-Identifier: GPL-3.0-or-later
"""AUD-016：Spine worker 进程隔离、Xvfb 回收与预检查归属的回归测试。

不需要官方 Spine runtime；真实 Xvfb 入口测试只在本机存在 Xvfb 时运行，
官方镜像端到端验证仍由 CI Docker worker job 负责。
"""

from __future__ import annotations

import ast
import json
import os
import shutil
import subprocess
import sys
import textwrap
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image

from astrbot_plugin_nikke.integrations.spine import bundle_inspection, worker_caller
from astrbot_plugin_nikke.integrations.spine.prerenderer import SpineBundle, SpineRenderError
from astrbot_plugin_nikke.integrations.spine.worker_caller import (
    SpineWorkerConfig,
    SpineWorkerRuntime,
    worker_environment,
)

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
WORKER_DIR = PLUGIN_ROOT / "runtime" / "spine_worker"
POSIX_ONLY = pytest.mark.skipif(os.name != "posix" or not Path("/proc").is_dir(), reason="需要 Linux 进程组与 /proc")


def _bundle(root: Path) -> SpineBundle:
    skeleton, atlas, texture = root / "c191.skel", root / "c191.atlas", root / "c191.png"
    skeleton.write_bytes(b"skeleton")
    atlas.write_text("c191.png\n", encoding="utf-8")
    Image.new("RGBA", (2, 2), "white").save(texture)
    return SpineBundle(skeleton=skeleton, atlas=atlas, textures=(texture,))


def _alive(pid: int) -> bool:
    """进程存在且不是已退出待回收的僵尸进程。"""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except OSError:
        return False
    return stat.rsplit(")", 1)[1].split()[0] != "Z"


def _wait_dead(pid: int, timeout: float = 2.0) -> bool:
    limit = time.monotonic() + timeout
    while time.monotonic() < limit:
        if not _alive(pid):
            return True
        time.sleep(0.02)
    return not _alive(pid)


def _script(path: Path, body: str) -> Path:
    path.write_text(f"#!{sys.executable}\n" + textwrap.dedent(body), encoding="utf-8")
    path.chmod(0o755)
    return path


# ---------------------------------------------------------------------------
# 预检查归属：生产代码不再依赖 scripts/
# ---------------------------------------------------------------------------


def test_production_spine_code_does_not_import_scripts() -> None:
    for path in (PLUGIN_ROOT / "integrations" / "spine").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                target = "." * node.level + (node.module or "")
                assert "scripts" not in target.split("."), f"{path.name} 仍导入 {target}"
            elif isinstance(node, ast.Import):
                assert not any("scripts" in alias.name.split(".") for alias in node.names), path.name


def test_cli_reexports_the_single_integrations_implementation() -> None:
    from astrbot_plugin_nikke.scripts.spine import inspect_spine_bundle as cli

    assert cli.inspect is bundle_inspection.inspect
    assert cli._binary_spine_version is bundle_inspection._binary_spine_version


def test_prerenderer_uses_integrations_inspection(tmp_path: Path) -> None:
    from astrbot_plugin_nikke.integrations.spine.prerenderer import SpinePreRenderer

    renderer = SpinePreRenderer(tmp_path)
    with patch.object(bundle_inspection, "inspect", return_value={"status": "VERSION_MATCH", "major_minor": "4.1", "missing_pages": 0}) as inspect:
        report = renderer.inspect_bundle(tmp_path / "a.atlas", tmp_path / "a.skel", "4.1")
    inspect.assert_called_once()
    assert (report.status, report.spine_version) == ("VERSION_MATCH", "4.1")


# ---------------------------------------------------------------------------
# 环境变量白名单
# ---------------------------------------------------------------------------


def test_worker_environment_is_allowlisted() -> None:
    source = {
        "PATH": "/usr/bin",
        "HOME": "/home/bot",
        "LANG": "C.UTF-8",
        "DOCKER_HOST": "unix:///var/run/docker.sock",
        "NIKKE_ENCRYPTION_KEY": "synthetic-secret-key",
        "HTTPS_PROXY": "http://user:pass@proxy:8080",
        "AWS_SECRET_ACCESS_KEY": "synthetic",
        "SDL_VIDEODRIVER": "x11",
        "path": "/lowercase/variant",
    }
    environment = worker_environment(source)
    assert environment["PATH"] == "/usr/bin"
    assert environment["HOME"] == "/home/bot"
    assert environment["DOCKER_HOST"] == "unix:///var/run/docker.sock"
    assert environment["SDL_VIDEODRIVER"] == "dummy"
    assert environment["SDL_RENDER_DRIVER"] == "software"
    for secret in ("NIKKE_ENCRYPTION_KEY", "HTTPS_PROXY", "AWS_SECRET_ACCESS_KEY", "path"):
        assert secret not in environment


@POSIX_ONLY
def test_real_worker_process_receives_only_allowlisted_environment(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    worker = _script(tmp_path / "env-worker.py", """
        import json, os, sys
        args = sys.argv[1:]
        output = args[args.index("--output") + 1]
        with open(output, "wb") as stream:
            stream.write((1).to_bytes(4, "little") + (1).to_bytes(4, "little") + bytes([1, 2, 3, 255]))
        print(json.dumps({"status": "ok", "geometry": {"schema": 1, "env": sorted(os.environ)}}))
    """)
    runtime = SpineWorkerRuntime(SpineWorkerConfig(worker, tmp_path, width=1, height=1))
    with patch.dict(os.environ, {"NIKKE_ENCRYPTION_KEY": "synthetic-secret-key", "HTTPS_PROXY": "http://proxy:1"}):
        image = runtime.render(bundle, animation="idle")
    names = set(image.info["spine_geometry"]["env"])
    assert "NIKKE_ENCRYPTION_KEY" not in names and "HTTPS_PROXY" not in names
    assert {"SDL_VIDEODRIVER", "SDL_RENDER_DRIVER"} <= names
    assert names <= set(worker_caller.WORKER_ENVIRONMENT_ALLOWLIST) | set(worker_caller.WORKER_FIXED_ENVIRONMENT) | {
        # 解释器自身在启动时可能补充的变量。
        "LC_CTYPE", "PWD", "SHLVL", "_",
    }
    assert not list(tmp_path.glob(".spine-worker-*"))


# ---------------------------------------------------------------------------
# 超时整组查杀
# ---------------------------------------------------------------------------


@POSIX_ONLY
def test_timeout_kills_whole_process_group_including_grandchild(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    pid_file = tmp_path / "grandchild.pid"
    worker = _script(tmp_path / "forking-worker.py", f"""
        import subprocess, sys, time
        # 模拟 entrypoint 启动的 Xvfb：孙进程不继承输出管道，只有进程组能定位它。
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        open({str(pid_file)!r}, "w").write(str(child.pid))
        time.sleep(30)
    """)
    runtime = SpineWorkerRuntime(SpineWorkerConfig(worker, tmp_path, timeout_seconds=1.0))
    start = time.monotonic()
    with pytest.raises(SpineRenderError, match="超时"):
        runtime.render(bundle, animation="idle")
    assert time.monotonic() - start < 3.0
    grandchild = int(pid_file.read_text(encoding="utf-8"))
    try:
        assert _wait_dead(grandchild), "超时后孙进程（如 Xvfb）不得成为孤儿"
    finally:
        if _alive(grandchild):
            os.kill(grandchild, 9)
    assert not list(tmp_path.glob(".spine-worker-*"))


@POSIX_ONLY
def test_worker_runs_in_its_own_session(tmp_path: Path) -> None:
    script = _script(tmp_path / "pgid.py", """
        import os
        print(os.getpgid(0), os.getsid(0))
    """)
    completed = worker_caller._run_worker([str(script)], cwd=tmp_path, timeout=5.0)
    pgid, sid = map(int, completed.stdout.split())
    assert pgid != os.getpgid(0) and sid != os.getsid(0)


def test_missing_worker_executable_is_render_error(tmp_path: Path) -> None:
    runtime = SpineWorkerRuntime(SpineWorkerConfig(tmp_path / "missing-worker", tmp_path))
    with pytest.raises(SpineRenderError, match="启动失败"):
        runtime.render(_bundle(tmp_path), animation="idle")


# ---------------------------------------------------------------------------
# Xvfb entrypoint：动态 display + trap
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["entrypoint-xvfb.sh", "entrypoint-xvfb-4.1.sh"])
def test_entrypoint_static_contract(name: str) -> None:
    text = (WORKER_DIR / name).read_text(encoding="utf-8")
    code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    assert ":99" not in code and "/tmp/.X" not in code, "不得共享固定 display 或手工接管锁文件"
    assert "-displayfd" in text
    assert "trap cleanup EXIT" in text and "TERM" in text
    assert "mktemp -d" in text


def test_worker_source_escapes_animation_names_and_uses_unique_temp_atlas() -> None:
    source = (WORKER_DIR / "main_sfml.cpp").read_text(encoding="utf-8")
    assert '+ ".utf8"' not in source
    assert "mkstemp(" in source
    list_block = source[source.index("if (options.list_animations) {\n\t\t\t\t\t"):]
    list_block = list_block[: list_block.index("return 0;")]
    assert "json_string(skeleton_data->getAnimations()[anim_index]->getName().buffer())" in list_block
    assert "<< \"\\\"\" << skeleton_data" not in list_block


def _entrypoint_with_fake_worker(tmp_path: Path, name: str) -> Path:
    # argv[1]：写入同一 entrypoint 所启动 Xvfb 的 pid；argv[2]：可选 sleep 模式。
    # -displayfd 模式下 Xvfb 不写 /tmp/.X<n>-lock，按父进程（entrypoint）的子进程查找。
    fake = _script(tmp_path / "fake-worker", """
        import json, os, sys, time
        parent = os.getppid()
        found = []
        for entry in os.listdir("/proc"):
            if not entry.isdigit():
                continue
            try:
                stat = open(f"/proc/{entry}/stat", encoding="utf-8").read()
            except OSError:
                continue
            name = stat[stat.index("(") + 1 : stat.rindex(")")]
            if name == "Xvfb" and int(stat.rsplit(")", 1)[1].split()[1]) == parent:
                found.append(entry)
        open(sys.argv[1], "w", encoding="utf-8").write(",".join(found))
        print(json.dumps({"status": "ok", "display": os.environ.get("DISPLAY")}), flush=True)
        if sys.argv[2:] == ["sleep"]:
            time.sleep(30)
    """)
    original = (WORKER_DIR / name).read_text(encoding="utf-8")
    binary = "/usr/local/bin/nikke-spine-worker-4.1" if "4.1" in name else "/usr/local/bin/nikke-spine-worker"
    assert f'worker_bin="{binary}"' in original
    entry = tmp_path / name
    entry.write_text(original.replace(f'worker_bin="{binary}"', f'worker_bin="{fake}"'), encoding="utf-8")
    entry.chmod(0o755)
    return entry


XVFB_REQUIRED = pytest.mark.skipif(
    os.name != "posix" or shutil.which("Xvfb") is None or not Path("/bin/sh").exists() or not Path("/proc").is_dir(),
    reason="需要本机 Xvfb 与 /bin/sh",
)


@XVFB_REQUIRED
@pytest.mark.parametrize("name", ["entrypoint-xvfb.sh", "entrypoint-xvfb-4.1.sh"])
def test_concurrent_entrypoints_get_private_displays_and_clean_up(tmp_path: Path, name: str) -> None:
    entry = _entrypoint_with_fake_worker(tmp_path, name)
    temp_root = tmp_path / "tmp"
    temp_root.mkdir()
    pid_files = [tmp_path / f"xvfb-{index}.pid" for index in range(3)]
    with patch.dict(os.environ, {"TMPDIR": str(temp_root)}):
        processes = [
            subprocess.Popen([str(entry), str(pid_file)], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
            for pid_file in pid_files
        ]
        outputs = [process.communicate(timeout=20)[0] for process in processes]
    assert [process.returncode for process in processes] == [0, 0, 0]
    displays = [json.loads(output)["display"] for output in outputs]
    assert len(set(displays)) == 3, f"并发 worker 必须各自使用独立 display：{displays}"
    for pid_file in pid_files:
        xvfb = int(pid_file.read_text(encoding="utf-8"))  # 恰好一个本次 entrypoint 的 Xvfb
        assert _wait_dead(xvfb), "正常结束后 Xvfb 必须被 trap 回收"
    assert not list(temp_root.iterdir()), "entrypoint 临时目录必须清理"


@XVFB_REQUIRED
def test_timeout_through_entrypoint_leaves_no_orphan_xvfb(tmp_path: Path) -> None:
    entry = _entrypoint_with_fake_worker(tmp_path, "entrypoint-xvfb.sh")
    pid_file = tmp_path / "xvfb.pid"
    temp_root = tmp_path / "tmp"
    temp_root.mkdir()
    start = time.monotonic()
    with patch.dict(os.environ, {"TMPDIR": str(temp_root)}), pytest.raises(subprocess.TimeoutExpired):
        # 首次启动 Xvfb 可能较慢；超时预算足够其就绪后再触发查杀。
        worker_caller._run_worker([str(entry), str(pid_file), "sleep"], cwd=tmp_path, timeout=3.0)
    assert time.monotonic() - start < 6.0
    # 先 SIGTERM 再 SIGKILL：entrypoint 的 trap 必须有机会删除自己的临时目录。
    limit = time.monotonic() + 3
    while list(temp_root.iterdir()) and time.monotonic() < limit:
        time.sleep(0.05)
    assert not list(temp_root.iterdir()), "超时回收必须给 entrypoint trap 清理临时目录的宽限"
    assert pid_file.is_file(), "fake worker 未启动，无法验证 Xvfb 回收"
    xvfb = int(pid_file.read_text(encoding="utf-8"))
    try:
        assert _wait_dead(xvfb), "worker 超时后 Xvfb 不得成为孤儿"
    finally:
        if _alive(xvfb):
            os.kill(xvfb, 9)


@XVFB_REQUIRED
def test_sigterm_to_entrypoint_runs_trap_cleanup(tmp_path: Path) -> None:
    entry = _entrypoint_with_fake_worker(tmp_path, "entrypoint-xvfb.sh")
    temp_root = tmp_path / "tmp"
    temp_root.mkdir()
    pid_file = tmp_path / "xvfb.pid"
    with patch.dict(os.environ, {"TMPDIR": str(temp_root)}):
        process = subprocess.Popen([str(entry), str(pid_file), "sleep"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        limit = time.monotonic() + 10
        while not (pid_file.is_file() and pid_file.read_text(encoding="utf-8")) and time.monotonic() < limit:
            time.sleep(0.05)
        xvfb = int(pid_file.read_text(encoding="utf-8"))
        process.terminate()
        assert process.wait(timeout=5) == 143
        assert _wait_dead(xvfb)
        assert not list(temp_root.iterdir())
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()


def test_orphan_atlas_copies_are_swept_but_fresh_ones_kept(tmp_path: Path) -> None:
    atlas = tmp_path / "c010.atlas"
    atlas.write_text("atlas", encoding="utf-8")
    stale = tmp_path / "c010.atlas.utf8.AAAAAA"
    fresh = tmp_path / "c010.atlas.utf8.BBBBBB"
    other = tmp_path / "c011.atlas.utf8.CCCCCC"
    for path in (stale, fresh, other):
        path.write_text("copy", encoding="utf-8")
    old = time.time() - 60
    os.utime(stale, (old, old))
    os.utime(other, (old, old))
    assert worker_caller.sweep_orphan_atlas_copies(atlas, older_than=10) == 1
    assert not stale.exists()
    assert fresh.exists(), "仍可能被正在运行的 worker 使用的副本不得删除"
    assert other.exists(), "只清理同一 atlas 的副本"


def test_sync_script_uses_hardened_worker_runner() -> None:
    source = (Path(__file__).resolve().parents[1] / "scripts" / "spine" / "sync_spine_assets.py").read_text(encoding="utf-8")
    assert "run_spine_worker(command" in source
    assert "os.environ.copy()" not in source
