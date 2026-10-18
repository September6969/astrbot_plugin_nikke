"""用人工固定样本回放正式突袭模板，输出整图、手机缩图与布局检查。"""
import argparse
import asyncio
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import re
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
from astrbot_plugin_nikke.features.raid.models import BossStatus, PreviousSeasonSummary, RaidResponseCoverage, RaidState
from astrbot_plugin_nikke.scripts.t2i_preview_fixtures import get_cases
from astrbot_plugin_nikke.ui.renderers.t2i import T2IRenderer


def attack(index):
    return {"openid": f"synthetic-{index}", "nickname": f"测试成员 {index + 1:02}",
        "boss_id": "2420020214", "day": index // 3 + 1, "difficulty": 2, "level": 7, "step": 3,
        "total_damage": 923456789 - index * 10000000, "is_final_hit": index == 0,
        "squad": [{"tid": tid, "slot": slot, "lv": 441, "combat": 232663 + slot * 1000}
            for slot, tid in enumerate([433004, 301704, 447105, 423401, 235207], 1)]}


def samples(output):
    rows = [attack(i) for i in range(20)]
    rows[15]["total_damage"] = rows[14]["total_damage"]
    rows[2]["nickname"] = "很长的测试昵称用来验证换行与列宽"
    ranking = analyze({"participate_data": rows}, season_id="1000007")
    mine = [dict(attack(i), openid="me", nickname="验证五槽队伍与长名称的中文指挥官昵称") for i in range(12)]
    mine[0]["squad"][0]["tid"] = "231301"
    mine[0]["squad"][1]["tid"] = "999999"
    unknown_attack = dict(mine[0], day="unknown", is_final_hit="unknown", total_damage=123456789, squad=[])
    mine.append(unknown_attack)
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
    off.previous_season = PreviousSeasonSummary(
        season_id="1000007", season_number=7,
        start_at="2026-10-01T00:00:00+08:00",
        end_at="2026-10-10T00:00:00+08:00",
    )
    partial = deepcopy(overview)
    partial.member = None
    partial.notices = ["个人记录暂不可用，其他区域已保留"]
    partial.ranking = analyze({"participate_data": [rows[0], {}, dict(rows[1], squad=[])]})
    if len(partial.bosses) < 2:
        raise AssertionError("Boss 样例不足两项，无法展示缺失字段与显式占位")
    partial.bosses = [
        replace(partial.bosses[0], current_hp=0, hp_percent=0.0, cleared_percent=1.0, status=BossStatus.DEFEATED),
        replace(partial.bosses[1], current_hp=None, hp_percent=None, cleared_percent=None, status=BossStatus.UNKNOWN),
    ]
    partial.partial_boss_records = True
    partial.response_coverage = RaidResponseCoverage.UNKNOWN_COVERAGE
    off_no_history = deepcopy(off)
    off_no_history.previous_season = None
    huge = analyze({"participate_data": [dict(rows[0], total_damage=9223372036854775807)]})
    zero = analyze({"participate_data": [dict(rows[0], total_damage=0)]})
    broken = analyze({"participate_data": [mine[-1], mine[1], {}]}, member_id="me")
    partial_ranking = analyze({"participate_data": rows + [{}]}, season_id="1000007")
    ranking_pages = [paginate(ranking, page) for page in range(1, (len(ranking.participants) + 14) // 15 + 1)]
    def attack_key(item):
        return (item.day, item.boss_id, item.level, item.step, item.total_damage)
    def participant_key(item):
        return (item.nickname, item.total_damage, tuple(attack_key(row) for row in item.attacks))
    ranking_keys = [participant_key(item) for page in ranking_pages for item in page.participants]
    expected_ranking_keys = [participant_key(item) for item in ranking.participants]
    member_count = sum(len(item.attacks) for item in member.participants)
    member_pages = [paginate(member, page, member=True) for page in range(1, (member_count + 4) // 5 + 1)]
    member_records = [item for page in member_pages for participant in page.participants for item in participant.attacks]
    expected_member_records = sorted(member.participants[0].attacks, key=lambda item: (item.day is None, item.day or 0))
    pagination = {
        "ranking": {
            "page_size": 15,
            "page_counts": [len(page.participants) for page in ranking_pages],
            "source_count": len(expected_ranking_keys),
            "rendered_count": len(ranking_keys),
            "unique_count": len(set(ranking_keys)),
            "preserved": ranking_keys == expected_ranking_keys,
            "cross_page_tie": {
                "last_rank_page_1": ranking_pages[0].participants[-1].rank,
                "first_rank_page_2": ranking_pages[1].participants[0].rank,
                "same_damage": ranking_pages[0].participants[-1].total_damage == ranking_pages[1].participants[0].total_damage,
                "preserved": ranking_pages[0].participants[-1].rank == ranking_pages[1].participants[0].rank == 15
                    and ranking_pages[0].participants[-1].total_damage == ranking_pages[1].participants[0].total_damage,
            },
        },
        "member": {
            "page_size": 5,
            "page_counts": [sum(len(item.attacks) for item in page.participants) for page in member_pages],
            "source_count": len(expected_member_records),
            "rendered_count": len(member_records),
            "unique_count": len({attack_key(item) for item in member_records}),
            "preserved": [attack_key(item) for item in member_records] == [attack_key(item) for item in expected_member_records],
        },
    }
    return [
        ("overview-active", "union_overview", overview),
        ("overview-offseason", "union_overview", off),
        ("overview-offseason-no-history", "union_overview", off_no_history),
        ("overview-partial", "union_overview", partial),
        ("ranking-page1", "union_records", paginate(ranking, 1)),
        ("ranking-page2", "union_records", paginate(ranking, 2)),
        ("ranking-partial-scope", "union_records", paginate(partial_ranking, 1)),
        ("ranking-large-number", "union_records", paginate(huge, 1)),
        ("member-offseason", "union_member", paginate(off.member, 1, member=True)),
        ("ranking-zero", "union_records", paginate(zero, 1)),
        ("ranking-empty", "union_records", analyze({"participate_data": []})),
        ("member-page1", "union_member", paginate(member, 1, member=True)),
        ("member-page2", "union_member", paginate(member, 2, member=True)),
        ("member-page3", "union_member", paginate(member, 3, member=True)),
        ("member-missing-details", "union_member", paginate(broken, 1, member=True)),
        ("member-empty", "union_member", analyze({"participate_data": []}, member_id="me")),
    ], pagination


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
            viewport_match = re.search(r'<meta name="viewport" content="width=(\d+)"', html)
            viewport_width = int(viewport_match.group(1)) if viewport_match else payload.get("canvas", {}).get("width", 1500)
            page = await browser.new_page(viewport={"width": viewport_width, "height": 800}, device_scale_factor=1)
            await page.set_content(html)
            await page.evaluate("document.fonts.ready")
            bounds = await page.evaluate("""() => {
                const rect = e => { const r=e.getBoundingClientRect(); return {left:r.left,top:r.top,right:r.right,bottom:r.bottom,width:r.width,height:r.height}; };
                const inside = (child,parent) => child.left >= parent.left - 1 && child.top >= parent.top - 1 && child.right <= parent.right + 1 && child.bottom <= parent.bottom + 1;
                const textSelector = 'h1,h2,p,th,td,.badge,.chip,.boss strong,.percentage,.damage,.unit-name,.unit-name small,.share-value,.empty,.day,.scope,.footer';
                const textOverflow = [...document.querySelectorAll(textSelector)].filter(e => e.scrollWidth > e.clientWidth + 2 || e.scrollHeight > e.clientHeight + 2).map(e => ({tag:e.tagName,cls:e.className,text:(e.innerText||'').slice(0,80),scroll:[e.scrollWidth,e.scrollHeight],client:[e.clientWidth,e.clientHeight]}));
                const tableCellErrors = [...document.querySelectorAll("table")].flatMap(table => { const expected=table.querySelectorAll("thead th").length; return [...table.querySelectorAll("tbody tr")].filter(row => row.cells.length !== expected).map(row => ({expected, actual:row.cells.length})); });
                const boundaryErrors = [];
                for (const e of document.querySelectorAll(textSelector)) {
                    const owner=e.closest('.unit')||e.closest('.boss')||e.closest('.attack')||e.closest('.panel')||e.closest('main');
                    if (owner && !inside(rect(e),rect(owner))) boundaryErrors.push({text:(e.innerText||'').slice(0,80),owner:owner.className||owner.tagName,child:rect(e),parent:rect(owner)});
                }
                const overlapErrors=[];
                for (const parent of document.querySelectorAll('main,.panel,.attack,.squad,.stats,.boss,.heading,.attack-head,table thead,table tbody')) {
                    const children=[...parent.children].filter(e=>{const r=e.getBoundingClientRect();return r.width>0&&r.height>0;});
                    for(let i=0;i<children.length;i++) for(let j=i+1;j<children.length;j++) {
                        const a=rect(children[i]),b=rect(children[j]);
                        const w=Math.min(a.right,b.right)-Math.max(a.left,b.left),h=Math.min(a.bottom,b.bottom)-Math.max(a.top,b.top);
                        if(w>1&&h>1) overlapErrors.push({parent:parent.className||parent.tagName,a:children[i].className||children[i].tagName,b:children[j].className||children[j].tagName,overlap:[w,h]});
                    }
                }
                return {width:document.documentElement.scrollWidth,height:document.documentElement.scrollHeight,viewport:innerWidth,
                    overflow:textOverflow.length,textOverflow,tableCellErrors,boundaryErrors,overlapErrors,
                    cards:{panels:document.querySelectorAll('.panel').length,bossRows:document.querySelectorAll('.boss').length,rankingRows:document.querySelectorAll('tbody tr').length,attacks:document.querySelectorAll('.attack').length,units:document.querySelectorAll('.unit').length}};
            }""")
            path = args.output / f"{name}.png"
            await page.screenshot(path=str(path), full_page=True)
            await page.close()
            with Image.open(path) as img:
                img.resize((432, round(img.height * 432 / img.width)), Image.Resampling.LANCZOS).save(args.output / f"{name}-mobile.png")
            evidence.append({"name": name, **bounds})
            return str(path)
        renderer = T2IRenderer(native, assets, timeout=120)
        cases, pagination = samples(args.output)
        (args.output / "pagination-checks.json").write_text(json.dumps(pagination, ensure_ascii=False, indent=2), encoding="utf-8")
        if not all(item["preserved"] and item["source_count"] == item["rendered_count"] and item["unique_count"] == item["source_count"] for item in pagination.values()) or not pagination["ranking"]["cross_page_tie"]["preserved"]:
            raise AssertionError(f"分页记录不完整：{pagination}")
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
    failures = [e for e in evidence if e["width"] > e["viewport"] or e["overflow"] or e["tableCellErrors"] or e["boundaryErrors"] or e["overlapErrors"]]
    if failures:
        raise AssertionError(f"布局溢出：{failures}")


if __name__ == "__main__":
    asyncio.run(main())
