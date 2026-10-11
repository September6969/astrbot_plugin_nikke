"""用人工固定样本回放正式突袭模板，输出整图、手机缩图与布局检查。"""
import argparse
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import types

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))

from jinja2 import Environment
from PIL import Image
from playwright.async_api import async_playwright
from astrbot_plugin_nikke.core.asset_manager import AssetManager
from astrbot_plugin_nikke.features.raid.experience import analyze, paginate
from astrbot_plugin_nikke.features.raid.models import RaidState
from astrbot_plugin_nikke.scripts.t2i_preview_fixtures import get_cases
from astrbot_plugin_nikke.ui.renderers.t2i import T2IRenderer


def attack(index):
    return {"openid": f"synthetic-{index % 18}", "nickname": f"测试成员 {index % 18 + 1:02}",
        "boss_id": "2420020214", "day": index // 3 + 1, "difficulty": 2, "level": 7, "step": 3,
        "total_damage": 923456789 - index * 10000000, "is_final_hit": index == 0,
        "squad": [{"tid": tid, "slot": slot, "lv": 441, "combat": 232663 + slot * 1000}
            for slot, tid in enumerate([433004, 301704, 447105, 423401, 235207], 1)]}


def samples(output):
    rows = [attack(i) for i in range(18)]
    rows[2]["nickname"] = "很长的测试昵称用来验证换行与列宽"
    ranking = analyze({"participate_data": rows}, season_id="1000007")
    mine = [dict(attack(i), openid="me", nickname="测试指挥官") for i in range(12)]
    member = analyze({"participate_data": mine}, member_id="me", season_id="1000007")
    for data in (ranking, member):
        data.guild_name = "星海观测站 · 人工样本"
        data.fetched_at = "2026-10-10 12:00:00"
    overview = deepcopy(get_cases("union_overview", output)["normal"])
    overview.guild_name = ranking.guild_name
    overview.ranking, overview.member = ranking, member
    overview.current_season_name = "第 7 季"
    overview.fetched_at = ranking.fetched_at
    off = deepcopy(overview)
    off.raid_state = RaidState.OFFSEASON
    off.ranking.scope = "LAST_SEASON"
    off.member.scope = "LAST_SEASON_MEMBER"
    partial = deepcopy(overview)
    partial.member = None
    partial.notices = ["个人记录暂不可用，其他区域已保留"]
    partial.ranking = analyze({"participate_data": [rows[0], {}, dict(rows[1], squad=[])]})
    huge = analyze({"participate_data": [dict(rows[0], total_damage=9223372036854775807)]})
    zero = analyze({"participate_data": [dict(rows[0], total_damage=0)]})
    broken = analyze({"participate_data": [dict(mine[0], squad=[]), mine[1], {}]}, member_id="me")
    return [
        ("overview-active", "union_overview", overview),
        ("overview-offseason", "union_overview", off),
        ("overview-partial", "union_overview", partial),
        ("ranking-page1", "union_records", paginate(ranking, 1)),
        ("ranking-page2", "union_records", paginate(ranking, 2)),
        ("ranking-large-number", "union_records", paginate(huge, 1)),
        ("member-offseason", "union_member", paginate(off.member, 1, member=True)),
        ("ranking-zero", "union_records", paginate(zero, 1)),
        ("ranking-empty", "union_records", analyze({"participate_data": []})),
        ("member-page1", "union_member", paginate(member, 1, member=True)),
        ("member-page3", "union_member", paginate(member, 3, member=True)),
        ("member-missing-details", "union_member", paginate(broken, 1, member=True)),
        ("member-empty", "union_member", analyze({"participate_data": []}, member_id="me")),
    ]


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
                viewport:innerWidth,overflow:[...document.querySelectorAll('main td,.unit-name,.heading')].filter(e=>e.scrollWidth>e.clientWidth+2).length})""")
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
        for new_name, kind, data in [case for case in cases if case[0] in {"overview-active", "ranking-page1", "member-page1"}]:
            name = "before-" + new_name
            payload_file = {"union_overview": "raid_overview", "union_records": "raid_records", "union_member": "raid_member"}[kind]
            module = types.ModuleType("baseline_" + payload_file)
            module.__package__ = "astrbot_plugin_nikke.ui.payloads"
            source = subprocess.check_output(["git", "show", f"{base}:ui/payloads/{payload_file}.py"], cwd=ROOT).decode("utf-8")
            exec(compile(source, payload_file, "exec"), module.__dict__)
            cls = {"union_overview": "UnionOverviewT2IPayloadBuilder", "union_records": "UnionRecordsT2IPayloadBuilder", "union_member": "UnionMemberT2IPayloadBuilder"}[kind]
            builder = getattr(module, cls)(renderer.payload_builder.assets, renderer.payload_builder.resolver) if kind != "union_records" else getattr(module, cls)()
            payload = builder.build(data)
            page_html = subprocess.check_output(["git", "show", f"{base}:templates/t2i/{kind}.html"], cwd=ROOT).decode("utf-8")
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
