from __future__ import annotations

from pathlib import Path

import pytest

from scripts.spine_worker_docker_bridge import DockerBridgeError, build_docker_command


def test_docker_bridge_maps_only_paths_inside_the_selected_bundle(tmp_path: Path) -> None:
    bundle = tmp_path / "c020"
    bundle.mkdir()
    skeleton = bundle / "c020_00.skel"
    atlas = bundle / "c020_00.atlas"
    output = bundle / ".spine-c020.rgba"
    skeleton.write_bytes(b"skeleton")
    atlas.write_bytes(b"atlas")

    command = build_docker_command(
        "nikke-spine-worker:4.0",
        bundle,
        [
            "--skeleton", str(skeleton),
            "--atlas", str(atlas),
            "--output", str(output),
            "--animation", "idle",
            "--width", "1024",
            "--height", "1024",
        ],
    )

    assert command[0:2] == ["docker", "run"]
    image_index = command.index("nikke-spine-worker:4.0")
    assert command[image_index + 1:] == [
        "--skeleton", "/bundle/c020_00.skel",
        "--atlas", "/bundle/c020_00.atlas",
        "--output", "/bundle/.spine-c020.rgba",
        "--animation", "idle",
        "--width", "1024",
        "--height", "1024",
    ]


def test_docker_bridge_rejects_escape_and_unknown_worker_options(tmp_path: Path) -> None:
    bundle = tmp_path / "c020"
    bundle.mkdir()
    outside = tmp_path / "outside.skel"
    outside.write_bytes(b"skeleton")

    with pytest.raises(DockerBridgeError, match="路径越界"):
        build_docker_command(
            "nikke-spine-worker:4.0", bundle,
            ["--skeleton", str(outside)],
        )
    with pytest.raises(DockerBridgeError, match="不支持的 worker 参数"):
        build_docker_command("nikke-spine-worker:4.0", bundle, ["--exec", "malicious"])


def test_docker_bridge_rejects_untrusted_image_name(tmp_path: Path) -> None:
    with pytest.raises(DockerBridgeError, match="镜像名称无效"):
        build_docker_command("nikke-worker;whoami", tmp_path, [])
