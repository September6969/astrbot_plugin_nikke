"""锚点联动回归：同帧、裁切、缓存重启与真实取景消费。"""
import json
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image, ImageDraw

from astrbot_plugin_nikke.features.character import face_anchor
from astrbot_plugin_nikke.features.character.portrait_anchor import ANCHOR_KEY, read_anchor
from astrbot_plugin_nikke.integrations.spine.prerenderer import SpinePreRenderer
from astrbot_plugin_nikke.integrations.spine.portrait_anchor import save_portrait
from astrbot_plugin_nikke.integrations.spine.local_resolver import LocalSpineBundleResolver
from astrbot_plugin_nikke.integrations.spine.worker_caller import SpineWorkerConfig, SpineWorkerRuntime
from astrbot_plugin_nikke.integrations.spine.prerenderer import SpineBundle


def source_image():
    image = Image.new("RGBA", (1000, 1000))
    draw = ImageDraw.Draw(image)
    draw.rectangle((500, 100, 700, 850), fill="white")
    draw.line((500, 500, 40, 850), fill="white", width=15)
    image.info["spine_geometry"] = {
        "schema": 1,
        "bones": [{"name": "chest", "parent": "body", "x": 600, "y": 330}],
        "attachments": [
            {"slot": "eye", "attachment": "eye", "box": [575, 150, 625, 170]},
            {"slot": "face", "attachment": "face", "box": [550, 110, 650, 230]},
        ],
    }
    return image


def test_same_frame_anchor_survives_crop_disk_reload_and_framing(tmp_path):
    renderer = SpinePreRenderer(tmp_path)
    image = renderer._normalize_output(source_image())
    row = read_anchor(image)
    assert row and row["status"] == "ready"
    assert row["core_axis"]["torso_point"][1] > row["point"][1]
    save_portrait(image, renderer.prerender_dir / "raven.png")
    loaded = SpinePreRenderer(tmp_path).cached_portrait("raven")
    assert read_anchor(loaded) == row
    data = SimpleNamespace(resource_id=851, costume_id=None, costume_selection=None)
    resolver = SimpleNamespace(resolve_render_id=lambda *a: "c851", resolve_character_id=lambda *a: "c851")
    with patch.object(face_anchor, "metadata", return_value={}):
        result = face_anchor.framing(data, loaded, identity_resolver=resolver, summary_count=0)
    assert result["source"] != "anchor_unavailable"
    assert result["core_axis"]["available"]


def test_corrupt_or_mismatched_anchor_is_not_trusted(tmp_path):
    image = SpinePreRenderer(tmp_path)._normalize_output(source_image())
    assert read_anchor(image)
    image.putpixel((0, 0), (1, 1, 1, 255))
    assert read_anchor(image) is None
    image.info[ANCHOR_KEY] = "[]"
    assert read_anchor(image) is None


def test_missing_geometry_is_cached_as_unavailable(tmp_path):
    renderer = SpinePreRenderer(tmp_path)
    image = source_image()
    image.info.clear()
    result = renderer._normalize_output(image)
    assert read_anchor(result)["status"] == "unavailable"
    save_portrait(result, renderer.prerender_dir / "unsupported.png")
    assert read_anchor(renderer.cached_portrait("unsupported"))["status"] == "unavailable"


def test_legacy_local_cache_backfills_once_then_survives_restart(tmp_path):
    """缺失记录的旧缓存自动补算，重启后的热命中不再启动 worker。"""
    class Runtime:
        version = "4.1"
        calls = 0

        def render(self, bundle, **kwargs):
            self.calls += 1
            return source_image()

    root = tmp_path / "source" / "l2d" / "c851"
    root.mkdir(parents=True)
    (root / "c851_00.skel").write_bytes(b"12345678\x074.1.24")
    (root / "c851_00.atlas").write_text("page.png\nsize: 2, 2\n", encoding="utf-8")
    Image.new("RGBA", (2, 2), "white").save(root / "page.png")
    local = LocalSpineBundleResolver(tmp_path / "source").resolve("c851")
    runtime = Runtime()
    cache = tmp_path / "cache"
    renderer = SpinePreRenderer(cache, runtime=runtime)
    with patch("astrbot_plugin_nikke.scripts.inspect_spine_bundle.inspect", return_value={"status": "VERSION_MATCH", "missing_pages": 0}):
        assert read_anchor(renderer.render_local_portrait("c851", local))
        output = next(renderer.prerender_dir.glob("*.png"))
        # 模拟旧图仍在但没有随附锚点。
        with Image.open(output) as saved:
            legacy = saved.convert("RGBA")
        legacy.save(output, format="PNG")
        assert read_anchor(renderer.render_local_portrait("c851", local))
        assert runtime.calls == 2
        restarted = SpinePreRenderer(cache, runtime=runtime)
        assert read_anchor(restarted.render_local_portrait("c851", local))
        assert runtime.calls == 2


def test_weapon_length_does_not_change_core_anchor_distance(tmp_path):
    """改动武器像素不应改变同帧骨架给出的头胸距离。"""
    renderer = SpinePreRenderer(tmp_path)
    original = source_image()
    extended = original.copy()
    ImageDraw.Draw(extended).line((500, 500, 1, 980), fill="white", width=20)
    rows = [read_anchor(renderer._normalize_output(im)) for im in (original, extended)]
    distances = [r["core_axis"]["torso_point"][1] - r["point"][1] for r in rows]
    assert distances == [170, 170]


def test_worker_report_is_consumed_in_render_pipeline(tmp_path):
    """覆盖 worker 响应到真实取景数据的交接，防止只有 helper 测试通过。"""
    skeleton, atlas, texture = [tmp_path / name for name in ("c851.skel", "c851.atlas", "page.png")]
    skeleton.write_bytes(b"12345678\x074.1.24")
    atlas.write_text("page.png\nsize: 2, 2\n", encoding="utf-8")
    Image.new("RGBA", (2, 2), "white").save(texture)
    source = source_image()

    def run(command, **kwargs):
        from pathlib import Path
        output = Path(command[command.index("--output") + 1])
        output.write_bytes(source.width.to_bytes(4, "little") + source.height.to_bytes(4, "little") + source.tobytes())
        return SimpleNamespace(returncode=0, stdout=json.dumps({"status": "ok", "geometry": source.info["spine_geometry"]}))

    runtime = SpineWorkerRuntime(SpineWorkerConfig(tmp_path / "worker", tmp_path), version="4.1")
    renderer = SpinePreRenderer(tmp_path / "cache", runtime=runtime)
    with patch("astrbot_plugin_nikke.integrations.spine.worker_caller.subprocess.run", side_effect=run), patch(
        "astrbot_plugin_nikke.scripts.inspect_spine_bundle.inspect", return_value={"status": "VERSION_MATCH", "missing_pages": 0}
    ):
        result = renderer.render_full_body(SpineBundle(skeleton, atlas, (texture,)), "4.1")
    assert read_anchor(result)["core_axis"]["torso_source"] == "generic:chest"


def test_invalid_optional_geometry_does_not_discard_image(tmp_path):
    image = source_image()
    image.info["spine_geometry"] = {"schema": 1, "attachments": None, "bones": None}
    result = SpinePreRenderer(tmp_path)._normalize_output(image)
    assert result.getbbox()
    assert read_anchor(result)["status"] == "unavailable"


def test_numbered_rig_uses_unique_named_torso_surfaces_and_rejects_ambiguity(tmp_path):
    image = source_image()
    geometry = image.info["spine_geometry"]
    geometry["bones"] = [{"name": "bone3", "parent": "bone2", "x": 600, "y": 400}]
    geometry["attachments"] += [
        {"slot": "breast_l_ww", "attachment": "breast_l", "parent": "bone3", "box": [560, 280, 610, 350]},
        {"slot": "breast_r_ww", "attachment": "breast_r", "parent": "bone3", "box": [610, 280, 660, 350]},
    ]
    renderer = SpinePreRenderer(tmp_path)
    row = read_anchor(renderer._normalize_output(image))
    assert row["core_axis"]["torso_source"].startswith("generic-attachment:")
    geometry["attachments"].append(dict(geometry["attachments"][-1]))
    row = read_anchor(renderer._normalize_output(image))
    assert "core_axis" not in row
    assert row["core_axis_reason"] == "ambiguous_upper_torso_attachments"


def test_eye_accessories_cannot_expand_eye_bounds(tmp_path):
    image = source_image()
    renderer = SpinePreRenderer(tmp_path)
    before = read_anchor(renderer._normalize_output(image))
    for name in ("eyepatch", "eye_patch", "eyeborw_l", "eye_mask", "eyelight_l3", "headset"):
        image.info["spine_geometry"]["attachments"].append(
            {"slot": name, "attachment": name, "box": [400, 10, 800, 200]})
    after = read_anchor(renderer._normalize_output(image))
    assert after["point"] == before["point"]
    assert after["extent"] == before["extent"]


def test_whole_head_uses_actual_upper_edge_not_an_extra_half_head(tmp_path):
    image = source_image()
    image.info["spine_geometry"] = {"schema": 1, "bones": [], "attachments": [
        {"slot": "head", "attachment": "head", "box": [550, 110, 650, 210]},
    ]}
    portrait = SpinePreRenderer(tmp_path)._normalize_output(image)
    data = SimpleNamespace(resource_id=570, costume_id=None, costume_selection=None)
    resolver = SimpleNamespace(resolve_render_id=lambda *a: "c570", resolve_character_id=lambda *a: "c570")
    with patch.object(face_anchor, "metadata", return_value={}):
        result = face_anchor.framing(data, portrait, identity_resolver=resolver, summary_count=4)
    assert result["source"] == "head_attachment"
    assert result["final_scale"] == 2.94
    assert result["face_anchor"][1] - result["face_safe_source_y"] == 50


def test_accessory_on_face_slot_does_not_become_a_face(tmp_path):
    image = source_image()
    image.info["spine_geometry"] = {"schema": 1, "bones": [], "attachments": [
        {"slot": "face", "attachment": "eyepatch", "box": [500, 50, 700, 200]},
        {"slot": "head", "attachment": "headset", "box": [500, 50, 700, 200]},
    ]}
    row = read_anchor(SpinePreRenderer(tmp_path)._normalize_output(image))
    assert row["status"] == "unavailable"


def test_previous_anchor_schema_is_recomputed_instead_of_reused(tmp_path):
    image = SpinePreRenderer(tmp_path)._normalize_output(source_image())
    row = read_anchor(image)
    row["schema"] -= 1
    image.info[ANCHOR_KEY] = json.dumps(row)
    assert read_anchor(image) is None
