"""用人工固定样本回放个人资料模板，输出整图、手机缩图与布局检查。"""

# 支持直接执行、模块导入及从其他工作目录调用。
import sys as _bootstrap_sys
from pathlib import Path as _BootstrapPath
_bootstrap_root = _BootstrapPath(__file__).resolve().parents[2]
for _bootstrap_path in (_bootstrap_root.parent, _bootstrap_root):
    if str(_bootstrap_path) not in _bootstrap_sys.path:
        _bootstrap_sys.path.insert(0, str(_bootstrap_path))

import argparse
import asyncio
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT.parent))

from jinja2 import Environment
from PIL import Image
from playwright.async_api import async_playwright
from astrbot_plugin_nikke.core.asset_manager import AssetManager
from astrbot_plugin_nikke.scripts.shared.t2i_preview_fixtures import get_cases
from astrbot_plugin_nikke.ui.renderers.t2i import T2IRenderer


def samples(output):
    return [("profile-" + name, "profile", data)
            for name, data in get_cases("profile", output).items() if name != "partial"]


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    assets = AssetManager(args.output / "cache", ROOT / "assets", remote=False)
    evidence = []
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        name = ""
        async def native(template, payload, options):
            html = Environment(autoescape=False).from_string(template).render(**payload)
            (args.output / f"{name}.html").write_text(html, encoding="utf-8")
            page = await browser.new_page(viewport={"width": payload.get("canvas", {}).get("width", 1500), "height": 800}, device_scale_factor=1)
            await page.set_content(html)
            await page.evaluate("document.fonts.ready")
            bounds = await page.evaluate("""() => ({width:document.documentElement.scrollWidth,height:document.documentElement.scrollHeight,
                viewport:innerWidth,overflow:[...document.querySelectorAll('.kv,.kv>div,.kv>span,h1')].filter(e=>e.scrollWidth>e.clientWidth+2).length})""")
            path = args.output / f"{name}.png"
            await page.screenshot(path=str(path), full_page=True)
            await page.close()
            with Image.open(path) as img:
                img.resize((432, round(img.height * 432 / img.width)), Image.Resampling.LANCZOS).save(args.output / f"{name}-mobile.png")
            evidence.append({"name": name, **bounds})
            return str(path)
        renderer = T2IRenderer(native, assets, timeout=120)
        cases = samples(args.output)
        for name, kind, data in cases:
            await renderer.render_view(kind, data)
            print(name, flush=True)
        # 对照使用基线提交的模板与 payload，人工数据与新图一致。
        base = "d123b884ff05673063289c394601e51dfb161ef1"
        name = "before-profile-full"
        data = get_cases("profile", args.output)["full-current-model"]
        from astrbot_plugin_nikke.ui.payloads.profile import ProfileT2IPayloadBuilder
        payload = ProfileT2IPayloadBuilder().build(data)
        payload["canvas"] = {"width": 1200, "height": 800}
        page_html = subprocess.check_output(["git", "show", f"{base}:templates/t2i/profile.html"], cwd=ROOT).decode("utf-8")
        shared = ROOT / "templates/t2i/_shared"
        css = "\n".join((shared / f).read_text(encoding="utf-8") for f in ("reset.css", "tokens.css", "components.css", "utilities.css"))
        template = "{% autoescape true %}" + (shared / "macros.jinja").read_text(encoding="utf-8") + page_html.replace("<!-- SHARED_CSS -->", css) + "{% endautoescape %}"
        await native(template, payload, {})
        await browser.close()
    assets.close()
    (args.output / "layout-checks.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    failures = [e for e in evidence if not e["name"].startswith("before-") and (e["width"] > e["viewport"] or e["overflow"])]
    if failures:
        raise AssertionError(f"布局溢出：{failures}")


if __name__ == "__main__":
    asyncio.run(main())
