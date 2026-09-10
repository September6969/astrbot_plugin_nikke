"""脱敏展示层基准：固定输入、重复计时、原尺寸/半尺寸/QQ压缩模拟。"""
from __future__ import annotations

import argparse
import asyncio
import copy
import hashlib
import json
import shutil
import statistics
import subprocess
import sys
import time
import types
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
# 工作树名称不必等于包名；不导入其他历史工作树。
package = types.ModuleType("astrbot_plugin_nikke")
package.__path__ = [str(ROOT)]
sys.modules[package.__name__] = package

from astrbot_plugin_nikke.asset_manager import AssetManager
from astrbot_plugin_nikke.card_models import EquipmentOption, OptionSummary
from astrbot_plugin_nikke.character_card_renderer import CharacterCardRenderer
from astrbot_plugin_nikke.profile_card_renderer import ProfileCardRenderer
from astrbot_plugin_nikke.profile_models import ProfileDashboardData
from astrbot_plugin_nikke.campaign_history_models import StageClearRecord, StageClearMember, ClearLineupStatus
from astrbot_plugin_nikke.campaign_history_renderer import CampaignHistoryRenderer
from astrbot_plugin_nikke.union_raid_models import UnionRaidOverviewData, RaidBossData, BossStatus, RaidResponseCoverage
from astrbot_plugin_nikke.union_raid_renderer import UnionRaidRenderer
from astrbot_plugin_nikke.renderer import CardRenderer
from astrbot_plugin_nikke.tests.test_card_builder import build_card
from astrbot_plugin_nikke.web_service import BindingWebService
from astrbot_plugin_nikke.guide_registry import GuideRegistry


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--baseline", help="只从指定提交读取展示模块，生成同输入基线")
    args = parser.parse_args()
    if args.baseline:
        # 在独立进程中载入已核验基线，不切换工作树或覆盖当前文件。
        modules = {"card_theme": None, "renderer": "CardRenderer",
                   "character_card_renderer": "CharacterCardRenderer",
                   "profile_card_renderer": "ProfileCardRenderer",
                   "campaign_history_renderer": "CampaignHistoryRenderer",
                   "union_raid_renderer": "UnionRaidRenderer", "web_service": "BindingWebService",
                   "guide_registry": "GuideRegistry"}
        for name, exported in modules.items():
            module = types.ModuleType(f"astrbot_plugin_nikke.{name}")
            module.__file__ = str(ROOT / f"{name}.py")
            module.__package__ = "astrbot_plugin_nikke"
            sys.modules[module.__name__] = module
            source = subprocess.check_output(["git", "show", f"{args.baseline}:{name}.py"], cwd=ROOT).decode("utf-8")
            exec(compile(source, module.__file__, "exec"), module.__dict__)
            if exported:
                globals()[exported] = getattr(module, exported)
    root = ROOT / "artifacts/ui-v03"
    output = root / args.tag
    output.mkdir(parents=True, exist_ok=True)
    manager = AssetManager(output / "cache", ROOT / "assets", remote=False)
    render = CharacterCardRenderer(output, ROOT / "fonts", manager)
    base = build_card()
    base.commander_name, base.fetched_at = "展示样本 · 非真实账号", "2026-09-10 12:00"
    base.name_cn, base.name_en, base.resource_id, base.name_code = "拉毗", "Rapi", "10", "sample"
    base.level, base.hp, base.attack, base.defense, base.combat = 526, 5429825, 176926, 35499, 174321
    base.corporation, base.element, base.spine_asset_id = "ELYSION", "Fire", "c010"
    for item in base.equipment.values():
        item.equipped = True
        item.options = [EquipmentOption("sample", "攻击力提升", .1322, "percent", position=1, tier=15),
                        EquipmentOption("sample", "最大装弹数提升", .8537, "percent", position=2, tier=12),
                        EquipmentOption("sample", "空槽", 0, "empty", position=3)]
    assets = manager.resolve_character_assets(base)
    base.option_totals = [OptionSummary("攻击力提升", .1322 * 4, "percent"),
                          OptionSummary("最大装弹数提升", .8537 * 4, "percent")]
    for name in ("c010", "c010_03"):
        if not (root / "portraits" / f"{name}-idle.png").is_file():
            raise RuntimeError(f"缺少指定 idle@0 预览素材: {name}")
    default = Image.open(root / "portraits/c010-idle.png").convert("RGBA")
    vacation = Image.open(root / "portraits/c010_03-idle.png").convert("RGBA")
    jobs = {}
    for name, portrait in (("character-c010", default), ("character-c010_03", vacation),
                           ("character-full-ol", default), ("character-missing-ol", default),
                           ("character-long-name", vacation), ("character-fallback", assets.portrait)):
        card, images = copy.deepcopy(base), copy.copy(assets)
        images.portrait = portrait
        if name.endswith("c010_03"):
            card.costume_id, card.spine_asset_id = "10005", "c010_03"
        if name.endswith("full-ol"):
            for item in card.equipment.values():
                item.options[2] = EquipmentOption("sample", "暴击率提升", .05, "percent", position=3, tier=8)
            card.option_totals.append(OptionSummary("暴击率提升", .20, "percent"))
        if name.endswith("missing-ol"):
            card.option_totals = []
            card.hp = card.attack = card.defense = None
            for item in card.equipment.values():
                item.options = []
            card.equipment["head"].equipped = False
            card.equipment["arm"].options = [EquipmentOption("unverified", "未识别词条", 1, "unknown", position=1)]
        if name.endswith("long-name"):
            card.name_cn = "繁體與简体混合超长正式角色名称排版样本"
            card.name_en = "VERY LONG OFFICIAL CHARACTER NAME / CLASSIC VACATION"
        jobs[name] = lambda c=card, a=images: render.render_character(c, a)
    for name, size in (("tall", (120, 1600)), ("wide", (1600, 250))):
        card, images = copy.deepcopy(base), copy.copy(assets)
        card.name_cn = f"合成极端轮廓 / {name}"
        card.corporation = "ABNORMAL"
        images.portrait = Image.new("RGBA", size, "#9296AD")
        jobs[f"character-{name}"] = lambda c=card, a=images: render.render_character(c, a)
    profile = ProfileDashboardData("展示指挥官", "", 526, 318, "NORMAL 34-24", "HARD 18-21", 187,
                                   526, 174321, base.fetched_at, base.plugin_version,
                                   commander_level=382, created_at="2023-01-16", roster_available=True,
                                   outpost_available=True, character_costume_count=37)
    jobs["profile"] = lambda: ProfileCardRenderer(output, ROOT / "fonts").render_profile(profile)
    generic = CardRenderer(output, ROOT / "fonts")
    roster = [{"name_code": str(i), "lv": 526-i, "combat": 174321-i*1837,
               "skill1_lv": 10, "skill2_lv": 7, "ulti_skill_lv": 10} for i in range(12)]
    names = {str(i): ["拉毗", "红莲：暗影", "爱丽丝", "普麗瓦蒂：不友善女僕"][i % 4] for i in range(12)}
    jobs["roster"] = lambda: generic.render_roster("展示样本", roster, names)
    jobs["summary"] = lambda: generic.render_summary([
        ("展示样本 A", "成功：已完成"), ("展示样本 B", "待处理：尚未开始"),
        ("展示样本 C", "不可用：接口暂无数据"), ("展示样本 D", "失败：请求未完成"),
        ("展示样本 E", "UNKNOWN_AFTER_ACTION：结果待确认，请勿自动重试")])
    record = StageClearRecord("HARD", 18, "18-21", 1, commander_name="展示样本",
                              fetched_at=base.fetched_at, plugin_version=base.plugin_version,
                              members=[StageClearMember(i, 526, 174321+i*103, i+1, name_cn=names[str(i)], resource_id="10") for i in range(5)])
    campaign = CampaignHistoryRenderer(output, ROOT / "fonts", manager)
    jobs["campaign"] = lambda: campaign.render_campaign_history(record)
    empty = copy.deepcopy(record)
    empty.status, empty.members, empty.status_message = ClearLineupStatus.UNAVAILABLE, [], "暂无已保存的通关阵容"
    jobs["campaign-unavailable"] = lambda: campaign.render_campaign_history(empty)
    raid = UnionRaidOverviewData("联盟展示样本", 5, 3, .625, 150000000, 400000000,
         [RaidBossData("fixture", "拦截目标 · 合成记录", 150000000, 400000000, .375, .625, BossStatus.CURRENT),
          RaidBossData("unknown", "未确认目标", None, None, None, None, BossStatus.UNKNOWN)],
         None, base.fetched_at, base.plugin_version, response_coverage=RaidResponseCoverage.CURRENT_RESPONSE)
    jobs["raid"] = lambda: UnionRaidRenderer(output, ROOT / "fonts").render_raid_overview(raid)
    report = {"evidence": "sanitized fixture data; cached Spine idle portraits; local QQ compression simulation only", "renders": {}}
    try:
        for name, job in jobs.items():
            samples = []
            for iteration in range(args.repeat):
                start = time.perf_counter()
                path = Path(job())
                samples.append((time.perf_counter()-start)*1000)
                shutil.move(str(path), output / f"{name}-{iteration}.png")
            source = output / f"{name}-0.png"
            with Image.open(source) as im:
                for scale, suffix in ((.5, "50"), (.3, "30")):
                    im.resize((round(im.width*scale), round(im.height*scale)), Image.Resampling.LANCZOS).convert("RGB").save(output / f"{name}-{suffix}.jpg", quality=75)
            report["renders"][name] = {"samples_ms": samples, "median_ms": statistics.median(samples),
                                       "native": str(source), "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}
        for valid in (True, False):
            service = object.__new__(BindingWebService)
            service.store = types.SimpleNamespace(get_bind_session=lambda token: {"expires_at": 9999999999 if valid else 0, "used_at": None})
            request = types.SimpleNamespace(match_info={"token": "x"*43}, url="本地界面预览（无真实绑定凭据）")
            response = asyncio.run(service.bind_page(request))
            (output / f"binding-{'valid' if valid else 'expired'}.html").write_text(response.text, encoding="utf-8")
        popup = (subprocess.check_output(["git", "show", f"{args.baseline}:extension/popup.html"], cwd=ROOT).decode("utf-8")
                 if args.baseline else (ROOT / "extension/popup.html").read_text(encoding="utf-8"))
        # 浏览器预览不加载任何登录/提交代码；真实行为由扩展合同测试验证。
        (output / "popup.html").write_text(popup.replace('<script src="popup.js"></script>', '<!-- 仅静态 UI 预览 -->'), encoding="utf-8")
        (output / "guide-captions.txt").write_text("\n\n---\n\n".join(
            entry.caption() for entry in GuideRegistry(ROOT / "assets/guides").entries), encoding="utf-8")
        (output / "measurements.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({name: round(row["median_ms"], 1) for name, row in report["renders"].items()}, ensure_ascii=False))
    finally:
        manager.close()


if __name__ == "__main__":
    main()
