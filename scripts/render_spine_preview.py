"""离线用匹配版本的官方 WebGL runtime 输出高分辨率 idle PNG。"""
import argparse
import asyncio
import base64
import json
from pathlib import Path

import httpx
from PIL import Image
from playwright.async_api import async_playwright


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--webgl-runtime", type=Path, required=True)
    parser.add_argument("--bundle-dir", type=Path, required=True)
    parser.add_argument("--render-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    key = args.render_id
    atlas = (args.bundle_dir / f"{key}.atlas").read_text(encoding="utf-8")
    # 页名取自 atlas，仅接受当前资源目录中的文件。
    pages = [line.strip() for line in atlas.splitlines() if line.strip().endswith('.png')]
    textures = {}
    for name in pages:
        if Path(name).name != name:
            raise ValueError("纹理页路径越界")
        path = args.bundle_dir / name
        if not path.is_file():
            raw = httpx.get(f"https://raw.githubusercontent.com/Nikke-db/Nikke-db.github.io/main/l2d/{key}/{name}", timeout=30).raise_for_status().content
            path.write_bytes(raw)
        textures[name] = "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode()
    payload = {"atlas": atlas, "skel": base64.b64encode((args.bundle_dir / f"{key}.skel").read_bytes()).decode(), "textures": textures}
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--enable-unsafe-swiftshader"])
        page = await browser.new_page(viewport={"width": 4096, "height": 4096})
        await page.set_content('<html><body style="margin:0"><canvas width="4096" height="4096"></canvas></body></html>')
        await page.add_script_tag(path=str(args.runtime))
        await page.add_script_tag(path=str(args.webgl_runtime))
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
          if(!data.findAnimation('idle')) throw new Error('idle missing');
          const state = new spine.AnimationState(new spine.AnimationStateData(data));
          state.setAnimation(0,'idle',false);state.update(0);state.apply(skeleton);skeleton.updateWorldTransform();
          let offset=new spine.Vector2(),size=new spine.Vector2();skeleton.getBounds(offset,size);
          const scale=Math.min(4096*.84/size.x,4096*.84/size.y);
          skeleton.scaleX=scale;skeleton.scaleY=scale;skeleton.updateWorldTransform();skeleton.getBounds(offset,size);
          skeleton.x=(4096-size.x)/2-offset.x;skeleton.y=(4096-size.y)/2-offset.y;skeleton.updateWorldTransform();
          const renderer=new spine.SceneRenderer(canvas,gl);
          renderer.camera.position.x=2048;renderer.camera.position.y=2048;
          renderer.camera.viewportWidth=4096;renderer.camera.viewportHeight=4096;renderer.camera.update();
          gl.viewport(0,0,4096,4096);gl.clearColor(0,0,0,0);gl.clear(gl.COLOR_BUFFER_BIT);
          renderer.begin();renderer.drawSkeleton(skeleton,true);renderer.end();
          return canvas.toDataURL('image/png');
        }''', payload)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(base64.b64decode(result.split(',', 1)[1]))
        await browser.close()
    with Image.open(args.output) as image:
        box = image.getchannel('A').getbbox()
        cropped = image.crop(box)
        final = Image.new('RGBA', (cropped.width + 128, cropped.height + 128))
        final.paste(cropped, (64, 64));final.save(args.output)
    args.output.with_suffix('.json').write_text(json.dumps({"canonical_asset_id":key,"png_file":args.output.name,
        "width":final.width,"height":final.height,"alpha_bbox":box,"render_width":4096,"crop_padding":64}),encoding='utf-8')
    print(final.size)


if __name__ == '__main__':
    asyncio.run(main())
