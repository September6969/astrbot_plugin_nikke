"""通过生产 renderer 与 AstrBot 原生接口输出各页合成预览。"""
import argparse
import asyncio
import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
from astrbot_plugin_nikke.core.asset_manager import AssetManager
from astrbot_plugin_nikke.ui.renderers.t2i import T2IRenderer
from astrbot_plugin_nikke.scripts.t2i_preview_fixtures import get_cases


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--page", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--fixture", default="all")
    parser.add_argument("--spine-manifest", type=Path, help="可选的已准备本地 Spine 清单")
    parser.add_argument("--spine-dir", type=Path, help="清单 PNG 所在目录")
    args = parser.parse_args()
    output = args.output_dir / args.page
    output.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("ASTRBOT_ROOT", str(args.output_dir / "runtime"))
    (Path(os.environ["ASTRBOT_ROOT"]) / "data" / "temp").mkdir(parents=True, exist_ok=True)
    from astrbot.api.star import Star
    from jinja2 import Environment
    from PIL import Image

    async def native(template, payload, options):
        (output / f"{current_name}.html").write_text(Environment(autoescape=False).from_string(template).render(**payload), encoding="utf-8")
        (output / f"{current_name}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        from PIL import Image
        for attempt in range(3):
            try:
                path = await Star.html_render(object(), template, payload, return_url=False, options=options)
                with Image.open(path) as image:
                    image.verify()
                return path
            except (OSError, ValueError, RuntimeError, asyncio.TimeoutError):
                if attempt == 2:
                    raise
                print("原生预览返回暂不可用图片，重试", flush=True)

    # 独立预览补齐框架启动时的官方端点发现；不自选或硬编码服务端点。
    if not getattr(args, "html_only", False):
        from astrbot.core import html_renderer
        try:
            await asyncio.wait_for(html_renderer.network_strategy.get_official_endpoints(), timeout=15)
        except asyncio.TimeoutError:
            pass
    assets = AssetManager(args.output_dir / "asset-cache", ROOT / "assets", remote=False,
                          spine_manifest_path=args.spine_manifest, spine_rendered_dir=args.spine_dir)
    renderer = T2IRenderer(native, assets, timeout=180)
    for current_name, data in get_cases(args.page, args.output_dir / "fixtures").items():
        if args.fixture != "all" and current_name not in args.fixture.split(","):
            continue
        path = await renderer.render_view(args.page, data)
        paths = path if isinstance(path, (list, tuple)) else [path]
        for p_idx, p in enumerate(paths, 1):
            suffix = f"-p{p_idx}" if len(paths) > 1 else ""
            target = output / f"{current_name}{suffix}.png"
            shutil.copyfile(p, target)
            with Image.open(target) as image:
                for percent in (50, 30):
                    image.resize((image.width * percent // 100, image.height * percent // 100), Image.Resampling.LANCZOS).save(output / f"{current_name}{suffix}-{percent}.png")
                print(f"{args.page}/{current_name}{suffix}: {image.size}", flush=True)
    assets.close()


if __name__ == "__main__":
    asyncio.run(main())
