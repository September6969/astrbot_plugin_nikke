"""使用生产模板加载器为 P4 页面生成合成 DTO 预览和布局检查。"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))

from PIL import Image, ImageDraw
from jinja2 import Environment
from playwright.sync_api import sync_playwright

from astrbot_plugin_nikke.features.character.application import CharacterInfoData
from astrbot_plugin_nikke.features.daily.models import DailyTaskResult, DailyTaskStatus
from astrbot_plugin_nikke.ui.payloads.character_info import CharacterInfoT2IPayloadBuilder
from astrbot_plugin_nikke.ui.payloads.daily_summary import DailySummaryT2IPayloadBuilder
from astrbot_plugin_nikke.ui.t2i_templates import T2ITemplateLoader


def _fixture_data():
    icon = Image.new("RGBA", (256, 256), (65, 117, 137, 255))
    draw = ImageDraw.Draw(icon)
    draw.ellipse((65, 35, 190, 160), fill=(245, 201, 167, 255))
    draw.rounded_rectangle((42, 145, 215, 270), radius=60, fill=(42, 52, 75, 255))
    assets = SimpleNamespace(
        character_master=SimpleNamespace(
            resolve_resource_id=lambda resource_id: SimpleNamespace(resource_id=95)
            if str(resource_id) == "95"
            else None
        ),
        get_character_asset=lambda resource_id, kind: SimpleNamespace(
            image=icon, exact_match=resource_id == 95 and kind == "icon"
        ),
    )
    character = CharacterInfoData(
        name="测试妮姬",
        title="妮姬基础资料",
        rows=(
            ("名称（简体别名 / 繁中 / 英文）", "测试妮姬 / 測試妮姬 / Synthetic Nikke"),
            ("稀有度", "SSR"),
            ("属性", "火力"),
            ("武器", "火箭发射器"),
            ("爆裂阶段", "III"),
            ("企业", "合成企业"),
        ),
        resource_id="95",
    )
    character_payload = CharacterInfoT2IPayloadBuilder(assets).build(character)

    statuses = tuple(DailyTaskStatus)
    daily_results = []
    for index in range(48):
        status = statuses[index % len(statuses)]
        if index == 40:
            status = DailyTaskStatus.UNKNOWN_AFTER_ACTION
        elif index == 46:
            status = DailyTaskStatus.FAILED
        elif index == 47:
            status = DailyTaskStatus.UNKNOWN_AFTER_ACTION
        if index < 10:
            detail = "签到结果待确认，暂不重复提交。" * 8
        elif index == 10:
            detail = "单账号超长详情必须跨页完整保留；" * 600
        elif index == 40:
            detail = "第 41 个合成账号结果待确认，不得重试。"
        elif index == 46:
            detail = "第 47 个合成账号执行失败，具体结果需保留。"
        elif index == 47:
            detail = ("WARNING " + "W" * 32 + " ") * 100
        elif status is DailyTaskStatus.UNKNOWN_AFTER_ACTION:
            detail = "提交后的状态尚未确认，系统不会自动重复执行"
        else:
            detail = f"合成结果详情 {index + 1:02d}，此处用于检查长文本和多页边界。"
        account_name = (
            "合成账号长名称与窄屏换行检查样例，中文姓名继续显示"
            if index == 7
            else f"合成账号 {index + 1:02d}"
        )
        items = tuple(
            {
                "name": f"日常奖励示例{reward_index + 1}",
                "status": ("success", "pending", "failed", "unknown", "already_done")[reward_index],
                "detail": (
                    "已领取"
                    if index == 47
                    else f"奖励状态详情{reward_index + 1}，保留完整字段。" * 2
                ),
            }
            for reward_index in range(5)
        ) if index < 10 or index == 47 else ()
        daily_results.append(
            DailyTaskResult(
                account_name=account_name,
                status=status,
                detail=detail,
                items=items,
            )
        )
    daily_payload = DailySummaryT2IPayloadBuilder().build(
        daily_results, scope="合成管理员手动执行"
    )
    return character_payload, daily_payload


def _audit_page(page, page_name: str, width: int, height: int):
    return page.evaluate(
        """({pageName, width, height}) => {
          const root = document.querySelector('main');
          const rect = (node) => {
            const r = node.getBoundingClientRect();
            return {left:r.left, top:r.top, right:r.right, bottom:r.bottom,
                    width:r.width, height:r.height};
          };
          const rootRect = rect(root);
          const footer = document.querySelector('footer');
          const errors = [];
          if (Math.abs(rootRect.width - width) > 1) errors.push('root-width');
          if (Math.abs(rootRect.height - height) > 1) errors.push('root-height');
          if (root.scrollHeight > root.clientHeight + 1) errors.push('root-content-overflow');
          if (footer.getBoundingClientRect().bottom > rootRect.bottom + 1)
            errors.push('footer-outside-canvas');
          if (document.documentElement.scrollHeight > height + 1)
            errors.push('document-outside-canvas');
          const cards = Array.from(document.querySelectorAll('.daily .row, .info .row'));
          const cardDetails = cards.map((card, index) => {
            const cardRect = rect(card);
            const textNodes = Array.from(card.querySelectorAll(
              '.account, .badge, .continuation-label, .detail, .reward, .label, .value'
            ));
            const textRects = textNodes.map((node) => ({
              className: node.className,
              text: node.innerText,
              ...rect(node),
              scrollWidth: node.scrollWidth,
              clientWidth: node.clientWidth,
              scrollHeight: node.scrollHeight,
              clientHeight: node.clientHeight,
            }));
            for (const text of textRects) {
              if (text.top < cardRect.top - 1 || text.bottom > cardRect.bottom + 1)
                errors.push(`card-${index}-content-outside`);
              if (text.scrollWidth > text.clientWidth + 1)
                errors.push(`card-${index}-text-width-overflow`);
            }
            return {
              index,
              resultIndex: Number(card.dataset.resultIndex || 0),
              fragmentIndex: Number(card.dataset.fragmentIndex || 0),
              fragmentCount: Number(card.dataset.fragmentCount || 0),
              status: card.dataset.status || '',
              ...cardRect,
              text: textRects
            };
          });
          for (let index = 1; index < cardDetails.length; index++) {
            const previous = cardDetails[index - 1];
            const current = cardDetails[index];
            const overlapsHorizontally = Math.min(previous.right, current.right) >
              Math.max(previous.left, current.left) + 1;
            const overlapsVertically = Math.min(previous.bottom, current.bottom) >
              Math.max(previous.top, current.top) + 1;
            if (overlapsHorizontally && overlapsVertically)
              errors.push(`adjacent-card-overlap-${index - 1}-${index}`);
            for (const text of previous.text) {
              const overlapsCurrent = Math.min(text.right, current.right) >
                Math.max(text.left, current.left) + 1 &&
                Math.min(text.bottom, current.bottom) > Math.max(text.top, current.top) + 1;
              if (overlapsCurrent) errors.push(`adjacent-text-overlap-${index - 1}-${index}`);
            }
          }
          const images = Array.from(document.images).map((image) => ({
            complete: image.complete,
            naturalWidth: image.naturalWidth,
            naturalHeight: image.naturalHeight,
          }));
          if (images.some((image) => !image.complete || image.naturalWidth < 1))
            errors.push('image-not-decoded');
          return {pageName, viewport:{width,height}, root:rootRect,
                  rootScroll:{width:root.scrollWidth,height:root.scrollHeight},
                  document:{width:document.documentElement.scrollWidth,
                            height:document.documentElement.scrollHeight},
                  footer:rect(footer),
                  cards:cardDetails, images, fonts:document.fonts.status, errors};
        }""",
        {"pageName": page_name, "width": width, "height": height},
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--browser",
        type=Path,
        default=Path(
            r"C:\Users\September\AppData\Local\ms-playwright\chromium-1234\chrome-win64\chrome.exe"
        ),
    )
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    character_payload, daily_payload = _fixture_data()
    loader = T2ITemplateLoader()
    environment = Environment(autoescape=True)
    cases = [("character_info", "public-info", character_payload)]
    cases.extend(
        ("daily_summary", f"daily-{index + 1:02d}", payload)
        for index, payload in enumerate(daily_payload["pages"])
    )
    checks = []
    browser_version = "unknown"
    rendered_files = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=str(args.browser), headless=True
        )
        browser_version = browser.version
        for page_name, case_name, payload in cases:
            html = environment.from_string(loader.load(page_name)).render(**payload)
            (args.output_dir / f"{case_name}.html").write_text(html, encoding="utf-8")
            width = payload["canvas"]["width"]
            height = payload["canvas"]["height"]
            page = browser.new_page(viewport={"width": width, "height": height})
            page.set_content(html, wait_until="load")
            page.evaluate(
                "() => document.fonts.ready.then(() => document.fonts.status)"
            )
            page.evaluate(
                "async () => Promise.all(Array.from(document.images, image => image.decode().catch(() => null)))"
            )
            check = _audit_page(page, case_name, width, height)
            checks.append(check)
            original = args.output_dir / f"{case_name}-original.png"
            page.screenshot(path=str(original), full_page=True)
            with Image.open(original) as image:
                if image.size != (width, height):
                    raise SystemExit(
                        f"PNG 尺寸与声明画布不一致：{case_name} {image.size} != {(width, height)}"
                    )
                target_height = round(image.height * 432 / image.width)
                scaled = image.convert("RGB").resize(
                    (432, target_height), Image.Resampling.LANCZOS
                )
                scaled_path = args.output_dir / f"{case_name}-432.png"
                scaled.save(scaled_path, format="PNG", optimize=True)
            rendered_files.extend([original, scaled_path])
            page.close()
        browser.close()

    thumbs = []
    for path in rendered_files:
        if path.name.endswith("-432.png"):
            thumbs.append((path.name, Image.open(path).convert("RGB")))
    cell_w = 432
    cell_h = max(image.height for _, image in thumbs) + 34
    columns = 2
    rows = (len(thumbs) + columns - 1) // columns
    contact = Image.new("RGB", (columns * cell_w, rows * cell_h), "#dde5e7")
    draw = ImageDraw.Draw(contact)
    for index, (label, image) in enumerate(thumbs):
        x = (index % columns) * cell_w
        y = (index // columns) * cell_h
        draw.text((x + 8, y + 8), label, fill="#23343b")
        contact.paste(image, (x, y + 30))
    contact_path = args.output_dir / "contact-432.png"
    contact.save(contact_path, format="PNG", optimize=True)

    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()
    visible_rows = [
        card
        for check in checks
        for card in check["cards"]
        if card["resultIndex"]
    ]
    expected_indices = set(range(1, daily_payload["total_count"] + 1))
    actual_indices = {card["resultIndex"] for card in visible_rows}
    if actual_indices != expected_indices:
        raise SystemExit(
            f"日常汇总结果 ID 有遗漏：缺失={sorted(expected_indices - actual_indices)}"
        )
    if [card["resultIndex"] for card in visible_rows] != sorted(
        card["resultIndex"] for card in visible_rows
    ):
        raise SystemExit("日常汇总结果顺序不稳定")
    for result_index in expected_indices:
        fragments = [
            card for card in visible_rows if card["resultIndex"] == result_index
        ]
        expected_parts = list(range(1, fragments[0]["fragmentCount"] + 1))
        if [card["fragmentIndex"] for card in fragments] != expected_parts:
            raise SystemExit(f"日常汇总续页不完整：结果 {result_index}")
    for item in checks:
        if item["errors"]:
            raise SystemExit(f"布局检查失败：{item['pageName']} {item['errors']}")
    manifest = {
        "kind": "synthetic-local-playwright-preview",
        "branch": subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip(),
        "head": sha,
        "browser": {"name": "Chromium", "version": browser_version},
        "viewports": [check["viewport"] for check in checks],
        "daily_total": daily_payload["total_count"],
        "daily_pages": len(daily_payload["pages"]),
        "daily_visible_result_indices": sorted(actual_indices),
        "files": {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in rendered_files + [contact_path]
        },
        "layout_checks": checks,
        "limits": [
            "合成账号与合成头像，不包含真实账户资料",
            "本地 Chromium 与生产模板加载器，不等同 AstrBot 原生 html_render 或 CI",
        ],
    }
    (args.output_dir / "layout_checks.json").write_text(
        json.dumps(checks, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (args.output_dir / "preview_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({"pages": len(checks), "errors": 0, "contact": str(contact_path)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
