"""用生产适配器和 AstrBot 原生接口生成合成数据预览，不启动插件服务。"""
import argparse
import asyncio
import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))

from astrbot_plugin_nikke.asset_manager import AssetManager
from astrbot_plugin_nikke.campaign_history_builder import CampaignHistoryBuilder
from astrbot_plugin_nikke.campaign_stage_resolver import CampaignStageResolver
from astrbot_plugin_nikke.t2i_renderer import T2IRenderer


def fixture_record(name):
    fixture = json.loads((ROOT / "tests" / "fixtures" / "t2i_campaign.json").read_text(encoding="utf-8"))[name]
    stage = CampaignStageResolver.from_file(ROOT / "assets" / "campaign_stages.json").resolve_query(fixture["query"])
    record = CampaignHistoryBuilder().build(stage, fixture["response"], commander_name=fixture.get("commander", "合成示例 · 非账号数据"),
                                           fetched_at="2026-09-13 12:00", plugin_version="T2I PREVIEW")
    # 仅合成边界案例替换展示文本，业务解析仍经过正式 Builder。
    for member in record.members:
        if "display_name" in fixture:
            member.name_cn = fixture["display_name"]
    return record


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--fixture", default="normal")
    parser.add_argument("--html-only", action="store_true", help="仅导出生产模板，用于离线审查")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("ASTRBOT_ROOT", str(args.output_dir / "astrbot-runtime"))
    (Path(os.environ["ASTRBOT_ROOT"]) / "data" / "temp").mkdir(parents=True, exist_ok=True)
    from jinja2 import Environment

    async def native(template, payload, options):
        from astrbot.api.star import Star
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
    assets = AssetManager(args.output_dir / "asset-cache", ROOT / "assets", remote=False)
    renderer = T2IRenderer(native, assets, timeout=180)
    names = list(json.loads((ROOT / "tests" / "fixtures" / "t2i_campaign.json").read_text(encoding="utf-8"))) if args.fixture == "all" else args.fixture.split(",")
    for name in names:
        record = fixture_record(name)
        payload = renderer.payload_builder.build(record)
        html = Environment(autoescape=False).from_string(renderer.loader.load()).render(**payload)
        (args.output_dir / f"{name}.html").write_text(html, encoding="utf-8")
        (args.output_dir / f"{name}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        if not args.html_only:
            path = await renderer.render_campaign_history(record)
            target = args.output_dir / f"{name}.png"
            shutil.copyfile(path, target)
            from PIL import Image
            with Image.open(target) as image:
                if image.size != (1600, 880):
                    raise ValueError(f"画布溢出: {image.size}")
                for percent in (30, 50):
                    image.resize((1600 * percent // 100, 880 * percent // 100), Image.Resampling.LANCZOS).save(args.output_dir / f"{name}-{percent}.png")
        print(f"完成 {name}")


if __name__ == "__main__":
    asyncio.run(main())
