"""Batch pipeline to extract authentic Spine face anchors and render high-res idle portraits."""
import asyncio
import base64
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time

import httpx
from PIL import Image
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_40 = ROOT / "cache" / "spine_alice" / "spine-4.0.js"
RUNTIME_41 = ROOT / "cache" / "spine_runtime" / "spine-4.1.js"

sys.path.insert(0, str(ROOT / "scripts"))
from inspect_spine_bundle import _binary_spine_version

TARGETS = [
    # Group A: 普通直立/紧凑
    "c011", "c012", "c070", "c072", "c080", "c082", "c120", "c172",
    # Group B: 长发
    "c170", "c221", "c270",
    # Group C: 长枪/背包
    "c100", "c102", "c220",
    # Group D: 机械翼/披风
    "c101", "c180",
    # Group E: 宽裙摆
    "c181", "c233", "c310",
    # Group F: 偏头/侧脸
    "c161", "c222",
    # Group G: 强非对称姿势
    "c110", "c111", "c140", "c400",
    # Group H: costume variants
    "c224",
]


def download_bundle(key: str, bundle_dir: Path) -> tuple[Path, Path, Path, str]:
    bundle_dir.mkdir(parents=True, exist_ok=True)
    skel = bundle_dir / f"{key}.skel"
    atlas_path = bundle_dir / f"{key}.atlas"

    if not skel.is_file():
        r = httpx.get(f"https://raw.githubusercontent.com/Nikke-db/Nikke-db.github.io/main/l2d/{key}/{key}_00.skel", timeout=30)
        r.raise_for_status()
        skel.write_bytes(r.content)

    if not atlas_path.is_file():
        r = httpx.get(f"https://raw.githubusercontent.com/Nikke-db/Nikke-db.github.io/main/l2d/{key}/{key}_00.atlas", timeout=30)
        r.raise_for_status()
        atlas_path.write_bytes(r.content)

    atlas_text = atlas_path.read_text(encoding="utf-8-sig")
    pages = [line.strip() for line in atlas_text.splitlines() if line.strip().endswith(".png")]
    for p in pages:
        p_path = bundle_dir / p
        if not p_path.is_file():
            r = httpx.get(f"https://raw.githubusercontent.com/Nikke-db/Nikke-db.github.io/main/l2d/{key}/{p}", timeout=30)
            r.raise_for_status()
            p_path.write_bytes(r.content)

    version = _binary_spine_version(skel)
    if version not in ("4.0", "4.1"):
        raise ValueError(f"Unsupported spine version: {version} for {key}")

    runtime = RUNTIME_40 if version == "4.0" else RUNTIME_41
    return skel, atlas_path, runtime, version


def extract_anchor(key: str, skel: Path, atlas: Path, runtime: Path, sidecar: Path) -> dict:
    if not sidecar.is_file():
        subprocess.run(
            ["node", str(ROOT / "scripts/extract_spine_face_anchor.mjs"),
             str(runtime), str(skel), str(atlas), key, "idle", str(sidecar)],
            check=True, capture_output=True, timeout=45
        )
    return json.loads(sidecar.read_text(encoding="utf-8"))


async def render_portrait(key: str, skel: Path, atlas_path: Path, runtime: Path, out_png: Path, page):
    atlas_text = atlas_path.read_text(encoding="utf-8-sig")
    pages = [line.strip() for line in atlas_text.splitlines() if line.strip().endswith(".png")]
    textures = {}
    for p in pages:
        p_path = atlas_path.parent / p
        textures[p] = "data:image/png;base64," + base64.b64encode(p_path.read_bytes()).decode()

    payload = {
        "atlas": atlas_text,
        "skel": base64.b64encode(skel.read_bytes()).decode(),
        "textures": textures
    }

    await page.set_content('<html><body style="margin:0"><canvas width="4096" height="4096"></canvas></body></html>')
    await page.add_script_tag(path=str(runtime))
    result = await page.evaluate('''async ({atlas, skel, textures}) => {
      const canvas = document.querySelector('canvas');
      const gl = canvas.getContext('webgl', {alpha:true, premultipliedAlpha:true, preserveDrawingBuffer:true});
      if (!gl) throw new Error('WebGL unavailable');
      const textureAtlas = new spine.TextureAtlas(atlas);
      spine.GLTexture.DISABLE_UNPACK_PREMULTIPLIED_ALPHA_WEBGL = true;
      for (const item of textureAtlas.pages) {
        const image = new Image(); image.src = textures[item.name]; await image.decode();
        item.setTexture(new spine.GLTexture(gl, image));
      }
      const data = new spine.SkeletonBinary(new spine.AtlasAttachmentLoader(textureAtlas)).readSkeletonData(Uint8Array.from(atob(skel),c=>c.charCodeAt(0)));
      const skeleton = new spine.Skeleton(data);
      if(data.skins.length===1) skeleton.setSkin(data.skins[0]);
      skeleton.setToSetupPose();
      let anim = data.findAnimation('idle') ? 'idle' : data.animations[0].name;
      const state = new spine.AnimationState(new spine.AnimationStateData(data));
      state.setAnimation(0, anim, false); state.update(0); state.apply(skeleton); skeleton.updateWorldTransform();
      let offset=new spine.Vector2(),size=new spine.Vector2(); skeleton.getBounds(offset,size);
      const scale=Math.min(4096*.84/size.x,4096*.84/size.y);
      skeleton.scaleX=scale; skeleton.scaleY=scale; skeleton.updateWorldTransform(); skeleton.getBounds(offset,size);
      skeleton.x=(4096-size.x)/2-offset.x; skeleton.y=(4096-size.y)/2-offset.y; skeleton.updateWorldTransform();
      const renderer=new spine.SceneRenderer(canvas,gl);
      renderer.camera.position.x=2048; renderer.camera.position.y=2048;
      renderer.camera.viewportWidth=4096; renderer.camera.viewportHeight=4096; renderer.camera.update();
      gl.viewport(0,0,4096,4096); gl.clearColor(0,0,0,0); gl.clear(gl.COLOR_BUFFER_BIT);
      renderer.begin(); renderer.drawSkeleton(skeleton,true); renderer.end();
      return canvas.toDataURL('image/png');
    }''', payload)

    raw_bytes = base64.b64decode(result.split(",", 1)[1])
    import io
    with Image.open(io.BytesIO(raw_bytes)) as full_img:
        box = full_img.getchannel("A").getbbox()
        cropped = full_img.crop(box)
        final = Image.new("RGBA", (cropped.width + 128, cropped.height + 128), (0, 0, 0, 0))
        final.paste(cropped, (64, 64))
        final.save(out_png)
    return box, final.size


async def main():
    bundle_base = ROOT / "cache" / "spine_bundles"
    rendered_dir = ROOT / "assets" / "spine-rendered"
    rendered_dir.mkdir(parents=True, exist_ok=True)
    face_anchors_file = ROOT / "assets" / "face_anchors.json"
    face_anchors_data = json.loads(face_anchors_file.read_text(encoding="utf-8"))
    records = face_anchors_data.get("records", {})

    print(f"Starting batch preparation for {len(TARGETS)} targets...")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--enable-unsafe-swiftshader"])
        page = await browser.new_page(viewport={"width": 4096, "height": 4096})

        for i, key in enumerate(TARGETS, 1):
            out_png = rendered_dir / f"{key}.png"
            if key in records and out_png.is_file():
                print(f"[{i}/{len(TARGETS)}] {key} already exists and anchored. Skipping.")
                continue

            print(f"[{i}/{len(TARGETS)}] Processing {key}...")
            t0 = time.time()
            bundle_dir = bundle_base / key
            try:
                skel, atlas, runtime, version = download_bundle(key, bundle_dir)
                sidecar = bundle_dir / f"{key}.anchor.json"
                anchor_raw = extract_anchor(key, skel, atlas, runtime, sidecar)
                box, final_size = await render_portrait(key, skel, atlas, runtime, out_png, page)

                point_1024 = anchor_raw.get("point_1024", [512, 512])
                extent_1024 = anchor_raw.get("extent_1024", [256, 100])
                point_4096 = [point_1024[0] * 4.0, point_1024[1] * 4.0]
                extent_4096 = [extent_1024[0] * 4.0, extent_1024[1] * 4.0] if extent_1024 else [256, 100]

                final_point = [
                    point_4096[0] - box[0] + 64,
                    point_4096[1] - box[1] + 64,
                ]
                final_extent = extent_4096

                with Image.open(out_png) as im:
                    rgba = im.convert("RGBA")
                    pixel_sha256 = hashlib.sha256(rgba.tobytes()).hexdigest()
                    png_sha256 = hashlib.sha256(out_png.read_bytes()).hexdigest()

                record = {
                    "schema": 1,
                    "render_id": key,
                    "runtime": "4.1.20" if version == "4.1" else "4.0.47",
                    "animation": "idle",
                    "time": 0,
                    "skeleton_sha256": hashlib.sha256(skel.read_bytes()).hexdigest(),
                    "atlas_sha256": hashlib.sha256(atlas.read_bytes()).hexdigest(),
                    "anchor_kind": anchor_raw.get("anchor_kind", "eye_attachment"),
                    "attachments": anchor_raw.get("attachments", []),
                    "point_1024": point_1024,
                    "extent_1024": extent_1024,
                    "bounds": anchor_raw.get("bounds", [0, 0, 1000, 1000]),
                    "point": final_point,
                    "extent": final_extent,
                    "pixel_sha256": pixel_sha256,
                    "png_sha256": png_sha256,
                    "image_size": list(final_size),
                    "png_transform": {
                        "render_size": [4096, 4096],
                        "render_padding": 0.08,
                        "alpha_bbox": list(box),
                        "crop_padding": 64
                    },
                    "framing": {
                        "target": [760, 550],
                        "extent_width": 256.0
                    }
                }
                records[key] = record
                print(f"[{i}/{len(TARGETS)}] Finished {key} in {time.time()-t0:.2f}s (size: {final_size})")
            except Exception as e:
                print(f"[{i}/{len(TARGETS)}] ERROR on {key}: {e}")

        await browser.close()

    face_anchors_data["records"] = records
    face_anchors_file.write_text(json.dumps(face_anchors_data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"All done! Total face anchor records: {len(records)}")


if __name__ == "__main__":
    asyncio.run(main())
