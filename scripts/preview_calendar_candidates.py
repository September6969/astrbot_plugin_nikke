"""按固定时间和本地素材生成日程 UI 回归样例与截图。"""

import argparse
import asyncio
import hashlib
import json
import platform
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from jinja2 import Environment
from PIL import Image, ImageDraw
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))

from astrbot_plugin_nikke.core.asset_manager import AssetManager
from astrbot_plugin_nikke.features.calendar.application import CalendarApplication
from astrbot_plugin_nikke.features.calendar.canonical_models import CanonicalEvent, SourceHealth
from astrbot_plugin_nikke.features.calendar.service import CalendarService
from astrbot_plugin_nikke.integrations.calendar.visual_cache import CalendarVisualCache
from astrbot_plugin_nikke.ui.payloads.calendar import CalendarT2IPayloadBuilder
from astrbot_plugin_nikke.ui.renderers.t2i import T2IRenderer
from astrbot_plugin_nikke.ui.t2i_templates import T2ITemplateLoader

NOW = datetime(2026, 10, 13, 6, 21, 41, 863426, tzinfo=timezone.utc)
CASE_IDS = (
    "normal",
    "long-title",
    "title-layout-boundaries",
    "multi-page",
    "story-dual",
    "future-only",
    "active-only",
    "empty",
    "precision-mix",
    "partial-snapshot",
    "old-snapshot",
    "bright-kv",
    "dark-kv",
    "horizontal-kv",
    "portrait-kv",
    "missing-kv",
    "corrupt-kv",
    "multilingual-injection",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_event(
    event_id: str,
    title: str,
    *,
    start: datetime | None = None,
    end: datetime | None = None,
    event_type: str = "event",
    start_precision: str = "EXACT",
    end_precision: str = "EXACT",
    has_started_evidence: bool = False,
    metadata: dict | None = None,
) -> CanonicalEvent:
    return CanonicalEvent(
        id=event_id,
        title=title,
        event_type=event_type,
        start_at=start,
        end_at=end,
        start_precision=start_precision,
        end_precision=end_precision,
        sources=["gamekee"],
        primary_source="gamekee",
        fetched_at=NOW,
        updated_at=NOW,
        has_started_evidence=has_started_evidence,
        metadata=metadata or {},
    )


def current_event(event_id: str, title: str, **kwargs) -> CanonicalEvent:
    options = dict(start=NOW - timedelta(days=2), end=NOW + timedelta(days=5))
    options.update(kwargs)
    return make_event(event_id, title, **options)


def upcoming_event(event_id: str, title: str, *, day: int = 2, **kwargs) -> CanonicalEvent:
    options = dict(start=NOW + timedelta(days=day), end=NOW + timedelta(days=day + 8))
    options.update(kwargs)
    return make_event(event_id, title, **options)


def case_events(case_id: str) -> tuple[list[CanonicalEvent], dict]:
    if case_id == "normal":
        events = [
            current_event("fixture:coop", "协同作战：钢铁巨兽", event_type="coop", end=NOW + timedelta(hours=9)),
            current_event(
                "gamekee:7887",
                "MOST BEAUTIFUL MAID",
                start=datetime(2026, 10, 7, 16, tzinfo=timezone.utc),
                end=datetime(2026, 10, 28, 14, 59, tzinfo=timezone.utc),
            ),
            upcoming_event("fixture:recruit", "限时招募：新角色", day=1, event_type="recruit"),
            current_event("fixture:pass", "月度 PASS · 十月", event_type="pass", end=NOW + timedelta(days=12)),
            upcoming_event("fixture:story", "剧情活动 · 先导预告", day=5, event_type="story_event"),
        ]
        return events, {"description": "五条混合进行中与即将开始活动；使用已核验的本地横幅。", "visual_event_id": "gamekee:7887", "visual_kind": "cached-public"}
    if case_id == "long-title":
        events = [
            current_event(
                f"fixture:long-{index:02}",
                f"周年庆特别协同作战·{index:02}号：含有足够长度的中文活动标题用于检查真实换行与手机缩图阅读",
                end=NOW + timedelta(hours=index + 2),
                event_type="coop" if index % 2 else "story_event",
            )
            for index in range(1, 9)
        ]
        return events, {"description": "八条长标题进行中记录；检查换行、长行高度和最后一行边界。"}
    if case_id == "title-layout-boundaries":
        cjk_title = "这是一个二十五个汉字左右的正常长度活动标题验证"
        mixed_title = "NIKKE-活动Story限定2026联动招募"
        wide_title = "🌌🌟🧡NIKKE联动"
        full_title = (
            "超长标题完整可见验证："
            + "周年庆剧情活动限定招募与专属角色故事，开放时间和奖励说明完整展示。" * 3
        )
        upcoming_title = "即将开始标题必须完整显示以及所有信息都应与标题一起可读验证"
        assert len(cjk_title) == len(mixed_title)
        events = [
            current_event("layout-active-cjk", cjk_title, end=NOW + timedelta(hours=12)),
            current_event("layout-active-mixed", mixed_title, end=NOW + timedelta(days=4)),
            current_event("layout-active-wide", wide_title, end=NOW + timedelta(days=5)),
            current_event("layout-active-full", full_title, end=NOW + timedelta(days=6)),
            upcoming_event("layout-next-cjk", upcoming_title, day=1),
            upcoming_event("layout-next-wide", wide_title, day=2),
        ]
        return events, {"description": "真实 CanonicalEvent 边界样例：等码点数中英混排、短宽字符、即将结束标签与完整长标题。"}
    if case_id == "multi-page":
        events = [
            current_event(
                f"fixture:page-{index:02}",
                (
                    f"剧情活动 {index:02} · 超长标题检查，完整活动名称不能被其他记录覆盖"
                    if index in {3, 8, 12, 16}
                    else f"活动 {index:02} · 稳定事件分页样例"
                ),
                end=NOW + timedelta(hours=index + 3),
                event_type="story_event" if index % 3 == 0 else "event",
            )
            for index in range(1, 18)
        ]
        return events, {"description": "17 条同时进行活动，ID 稳定且唯一；预期分页并逐页复核。"}
    if case_id == "story-dual":
        rows = (
            ("story-a-1", "剧情活动 A · Story 1", -1, 8),
            ("story-a-2", "剧情活动 A · Story 2", -2, 9),
            ("story-b-1", "剧情活动 B · Story 1", -3, 10),
            ("story-b-hard", "剧情活动 B · Hard", -4, 11),
        )
        return [
            current_event(
                event_id,
                title,
                start=NOW + timedelta(days=start_day),
                end=NOW + timedelta(days=end_day),
                event_type="story_event",
            )
            for event_id, title, start_day, end_day in rows
        ], {"description": "两个剧情活动及各自阶段保留为四个独立事件，不推断父子关系。"}
    if case_id == "future-only":
        return [
            upcoming_event(f"fixture:future-{index}", f"即将开始活动 {index}", day=index)
            for index in range(1, 4)
        ], {"description": "只有将来活动；全局进行中状态必须如实显示为空。"}
    if case_id == "active-only":
        return [
            current_event(f"fixture:active-{index}", f"进行中活动 {index}", end=NOW + timedelta(days=index))
            for index in range(1, 4)
        ], {"description": "只有进行中活动；不应插入即将开始的虚假记录。"}
    if case_id == "empty":
        return [], {"description": "有可用快照但没有记录；文案不能宣称游戏内没有活动。"}
    if case_id == "precision-mix":
        return [
            current_event("fixture:exact", "EXACT · 精确时间与倒计时", end=NOW + timedelta(hours=2)),
            current_event(
                "fixture:date-only",
                "DATE_ONLY · 仅日期精度",
                start_precision="DATE_ONLY",
                end_precision="DATE_ONLY",
                start=NOW - timedelta(days=2),
                end=NOW + timedelta(days=4),
            ),
            current_event(
                "fixture:unknown",
                "UNKNOWN · 截止时间待确认",
                end=None,
                end_precision="UNKNOWN",
                has_started_evidence=True,
            ),
            upcoming_event(
                "fixture:date-only-start",
                "DATE_ONLY · 日期级开始",
                day=4,
                start_precision="DATE_ONLY",
                end_precision="DATE_ONLY",
            ),
            upcoming_event(
                "fixture:unknown-start",
                "UNKNOWN · 开始时间待确认",
                day=5,
                start_precision="UNKNOWN",
                end_precision="UNKNOWN",
            ),
        ], {"description": "覆盖 EXACT、DATE_ONLY 和 UNKNOWN 起止精度；只有 EXACT 显示时分倒计时。"}
    if case_id == "partial-snapshot":
        events = [
            current_event(
                f"fixture:partial-{index}",
                f"部分来源失败后保留的快照活动 {index}",
                metadata={"source_stale": index == 1},
            )
            for index in range(1, 5)
        ]
        return events, {"description": "来源同步部分失败，旧快照保留并明确来源异常。", "coverage": "PARTIAL", "sync_error": "固定样例：一个来源同步失败，使用已有快照。"}
    if case_id == "old-snapshot":
        events = [
            current_event(f"fixture:old-{index}", f"旧快照中的活动 {index}")
            for index in range(1, 5)
        ]
        return events, {"description": "使用七天前成功同步的旧快照，不能标为刚刚完成全量同步。", "freshness": "EXPIRED", "health_age_days": 7}
    if case_id in {"bright-kv", "horizontal-kv", "dark-kv"}:
        event_id, title = {
            "bright-kv": ("gamekee:7887", "MOST BEAUTIFUL MAID"),
            "horizontal-kv": ("gamekee:7889", "CINDERELLA SPECIAL"),
            "dark-kv": ("gamekee:7886", "OCCULTIST PASS"),
        }[case_id]
        return [
            current_event(
                event_id,
                title,
                start=datetime(2026, 10, 7, 16, tzinfo=timezone.utc),
                end=NOW + timedelta(days=5),
            )
        ], {"description": "使用已保存的横版活动 KV，逐图验证明暗与主体可见性。", "visual_event_id": event_id, "visual_kind": "cached-public"}
    if case_id == "portrait-kv":
        return [
            current_event("fixture:portrait", "竖版 KV 几何样例（合成素材）")
        ], {"description": "由核验横幅构造的版式几何合成图，不代表真实活动视觉素材。", "visual_event_id": "fixture:portrait", "visual_kind": "synthetic-geometry"}
    if case_id == "missing-kv":
        return [
            current_event("fixture:missing", "缺少活动图片时仍保留的日程记录")
        ], {"description": "无可用图片；应显示同版式渐变占位且保留正文。", "visual_kind": "missing"}
    if case_id == "corrupt-kv":
        return [
            current_event("fixture:corrupt", "损坏活动图片时仍保留的日程记录")
        ], {"description": "缓存清单指向无效图片；图片解码失败不能影响正文渲染。", "visual_event_id": "fixture:corrupt", "visual_kind": "corrupt"}
    if case_id == "multilingual-injection":
        return [
            current_event(
                "fixture:multilingual",
                "妮姬日程 / English / 日本語 / <img src=x onerror=alert(1)> & 引号“‘ ✦",
            )
        ], {"description": "中英日混排、特殊符号及 HTML 注入字符串；完整文本应转义并保留在回退数据。"}
    raise ValueError(f"未知场景：{case_id}")


def write_fixture_cache(
    destination: Path,
    event_id: str,
    source_visual_cache: CalendarVisualCache,
    *,
    synthetic: bool = False,
    corrupt: bool = False,
) -> tuple[CalendarVisualCache, dict]:
    destination.mkdir(parents=True, exist_ok=True)
    visual_dir = destination / "visuals"
    visual_dir.mkdir(parents=True, exist_ok=True)
    filename = hashlib.sha256(event_id.encode("utf-8")).hexdigest()[:32] + ".webp"
    image_path = visual_dir / filename
    metadata = {"event_id": event_id, "visual_kind": "cached-public"}
    source_id = "gamekee:7887" if synthetic or corrupt else event_id
    source_path = source_visual_cache.resolve_path(source_id)
    if source_path is None:
        raise RuntimeError(f"无法解析所需的本地几何来源素材：{source_id}")
    source_entry = source_visual_cache._manifest.get(source_id, {})
    with Image.open(source_path) as opened:
        source_image = opened.convert("RGB")
        source_size = list(source_image.size)
        if synthetic:
            canvas = Image.new("RGB", (900, 1500))
            draw = ImageDraw.Draw(canvas)
            top = (12, 24, 42)
            bottom = (25, 43, 66)
            for y in range(canvas.height):
                ratio = y / max(1, canvas.height - 1)
                color = tuple(round(top[i] * (1 - ratio) + bottom[i] * ratio) for i in range(3))
                draw.line((0, y, canvas.width, y), fill=color)
            banner = source_image.copy()
            banner.thumbnail((820, 420), Image.Resampling.LANCZOS)
            x = (canvas.width - banner.width) // 2
            y = (canvas.height - banner.height) // 2
            canvas.paste(banner, (x, y))
            label = "SYNTHETIC PORTRAIT GEOMETRY ONLY"
            draw = ImageDraw.Draw(canvas)
            draw.rounded_rectangle((35, 35, 865, 115), radius=18, fill=(5, 10, 18))
            draw.text((55, 63), label, fill=(244, 247, 250))
            canvas.save(image_path, "WEBP", quality=88, method=4)
            metadata.update({
                "visual_kind": "synthetic-geometry",
                "derived_from_event_id": source_id,
                "derived_from_sha256": sha256(source_path),
                "source_dimensions": source_size,
                "dimensions": [canvas.width, canvas.height],
                "synthetic_sha256": sha256(image_path),
            })
        elif corrupt:
            image_path.write_bytes(b"fixture-corrupt-image-not-decodable")
            metadata.update({
                "visual_kind": "corrupt-test-data",
                "derived_from_event_id": source_id,
                "derived_from_sha256": sha256(source_path),
                "dimensions": None,
                "synthetic_sha256": sha256(image_path),
            })
        else:
            shutil.copyfile(source_path, image_path)
            metadata.update({
                "source_url": source_entry.get("source_url"),
                "fetched_at": source_entry.get("fetched_at"),
                "source_sha256": sha256(source_path),
                "dimensions": list(source_image.size),
                "synthetic_sha256": sha256(image_path),
            })
    manifest = {
        "schema": 1,
        "updated_at": NOW.isoformat(),
        "entries": {
            event_id: {
                "filename": filename,
                "source_url": "synthetic://calendar-preview-fixture" if synthetic or corrupt else source_entry.get("source_url", ""),
                "fetched_at": NOW.isoformat() if synthetic or corrupt else source_entry.get("fetched_at"),
            }
        },
    }
    (destination / "visual_cache.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    metadata["path"] = str(image_path)
    metadata["sha256"] = sha256(image_path)
    metadata["source_url"] = manifest["entries"][event_id]["source_url"]
    return CalendarVisualCache(destination), metadata


def font_families() -> list[str]:
    font_dir = ROOT / "fonts"
    return sorted(path.name for path in font_dir.glob("*") if path.is_file())


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--visual-cache-source", type=Path, required=True)
    parser.add_argument("--template-root", type=Path)
    parser.add_argument("--variant", default="current")
    parser.add_argument("--case", action="append", choices=CASE_IDS)
    args = parser.parse_args()

    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    selected_cases = args.case or list(CASE_IDS)
    source_visual_cache = CalendarVisualCache(args.visual_cache_source)
    assets = AssetManager(output / "renderer-assets", ROOT / "assets", remote=False)
    records: list[dict] = []
    browser_metadata: dict = {}
    active_html_path: Path | None = None
    active_image_path: Path | None = None

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        browser_metadata = {
            "version": browser.version,
            "executable": playwright.chromium.executable_path,
        }

        async def native(template, payload, options):
            nonlocal active_html_path, active_image_path
            html = Environment(autoescape=True).from_string(template).render(**payload)
            if active_html_path is None or active_image_path is None:
                raise RuntimeError("当前场景没有设置 HTML 与图片输出路径。")
            active_html_path.write_text(html, encoding="utf-8")
            viewport = options.get("viewport") or {"width": 1600, "height": 900}
            page = await browser.new_page(viewport=viewport, device_scale_factor=1)
            await page.set_content(html, wait_until="load")
            await page.evaluate("document.fonts.ready")
            image_metrics = await page.evaluate(r'''async () => {
                const sources = [...document.images].map(image => image.currentSrc || image.src);
                for (const element of document.querySelectorAll("*")) {
                    const background = getComputedStyle(element).backgroundImage;
                    for (const match of background.matchAll(/url\(([^)]+)\)/g)) {
                        sources.push(match[1].replace(/^["']|["']$/g, ""));
                    }
                }
                return await Promise.all([...new Set(sources.filter(Boolean))].map(async src => {
                    const image = new Image();
                    image.src = src;
                    try {
                        await image.decode();
                        return {ok: true, width: image.naturalWidth, height: image.naturalHeight, srcPrefix: src.slice(0, 32)};
                    } catch {
                        return {ok: false, width: image.naturalWidth, height: image.naturalHeight, srcPrefix: src.slice(0, 32)};
                    }
                }));
            }''')
            metrics = await page.evaluate(r'''() => {
                const rect = element => {
                    const box = element.getBoundingClientRect();
                    return {x: box.x, y: box.y, width: box.width, height: box.height, right: box.right, bottom: box.bottom};
                };
                const textElements = [...document.querySelectorAll("body *")].filter(element =>
                    element.children.length === 0 && (element.textContent || "").trim()
                );
                const text = textElements.map(element => {
                    const style = getComputedStyle(element);
                    return {
                        tag: element.tagName.toLowerCase(),
                        className: typeof element.className === "string" ? element.className : "",
                        text: (element.textContent || "").trim().slice(0, 180),
                        box: rect(element),
                        clientWidth: element.clientWidth,
                        scrollWidth: element.scrollWidth,
                        clientHeight: element.clientHeight,
                        scrollHeight: element.scrollHeight,
                        fontSize: style.fontSize,
                        lineHeight: style.lineHeight,
                        fontFamily: style.fontFamily,
                        clippedX: element.scrollWidth > element.clientWidth + 2,
                        clippedY: element.scrollHeight > element.clientHeight + 2
                    };
                });
                const textRects = element => {
                    const range = document.createRange();
                    range.selectNodeContents(element);
                    return [...range.getClientRects()].filter(box => box.width > 0 && box.height > 0)
                        .map(box => ({x: box.x, y: box.y, right: box.right, bottom: box.bottom, width: box.width, height: box.height}));
                };
                const eventCards = [...document.querySelectorAll(".active-card, .next-row")].map(row => {
                    const active = row.classList.contains("active-card");
                    const title = row.querySelector(active ? ".card-title" : ".next-title");
                    const selectors = active
                        ? [".card-meta", ".card-title", ".card-side"]
                        : [".next-time", ".next-category", ".next-title", ".next-starts"];
                    const rowBox = rect(row);
                    const contentRects = selectors.flatMap(selector => [...row.querySelectorAll(selector)])
                        .flatMap(textRects);
                    const titleRects = textRects(title);
                    return {
                        eventId: row.dataset.eventId,
                        kind: active ? "active" : "upcoming",
                        title: title.textContent,
                        row: rowBox,
                        titleBox: rect(title),
                        titleRects,
                        contentRects,
                        titleInsideCard: titleRects.length > 0 && titleRects.every(box =>
                            box.y >= rowBox.y + 1 && box.bottom <= rowBox.bottom - 1
                        ),
                        textInsideCard: contentRects.length > 0 && contentRects.every(box =>
                            box.y >= rowBox.y + 1 && box.bottom <= rowBox.bottom - 1
                        )
                    };
                });
                const adjacentTextOverlaps = [];
                for (const list of document.querySelectorAll(".active-list, .next-list")) {
                    const rows = [...list.children].map(row => eventCards.find(card => card.eventId === row.dataset.eventId));
                    for (let index = 1; index < rows.length; index += 1) {
                        const previous = rows[index - 1];
                        const current = rows[index];
                        const previousBottom = Math.max(...previous.contentRects.map(box => box.bottom));
                        const currentTop = Math.min(...current.contentRects.map(box => box.y));
                        if (previousBottom > currentTop + 1) {
                            adjacentTextOverlaps.push({previous: previous.eventId, current: current.eventId, previousBottom, currentTop});
                        }
                    }
                }
                const contentArea = document.querySelector(".content-area");
                const footer = document.querySelector(".panel-footer");
                const structure = {
                    contentTag: contentArea?.tagName || null,
                    contentParentTag: contentArea?.parentElement?.tagName || null,
                    footerParentTag: footer?.parentElement?.tagName || null
                };
                const named = ["html", "body", ".canvas-bg", ".canvas-overlay", ".panel", ".panel-header", ".panel-body", ".panel-footer", "footer", ".active-card", ".next-row", ".card-title"];
                const boxes = {};
                for (const selector of named) {
                    const element = document.querySelector(selector);
                    if (element) boxes[selector] = rect(element);
                }
                return {
                    document: {width: document.documentElement.scrollWidth, height: document.documentElement.scrollHeight, clientWidth: document.documentElement.clientWidth, clientHeight: document.documentElement.clientHeight},
                    body: {width: document.body.scrollWidth, height: document.body.scrollHeight, clientWidth: document.body.clientWidth, clientHeight: document.body.clientHeight},
                    fontStatus: document.fonts.status,
                    text,
                    boxes,
                    eventCards,
                    adjacentTextOverlaps,
                    structure,
                    injectionElementCount: document.querySelectorAll("img,svg,iframe,script").length,
                    hasInjectionText: document.body.innerText.includes("onerror=alert(1)")
                };
            }''')
            metrics["images"] = image_metrics
            escaping_cards = [
                card["eventId"] for card in metrics["eventCards"]
                if not card["titleInsideCard"] or not card["textInsideCard"]
            ]
            if escaping_cards:
                raise RuntimeError(f"{case_id} 标题或元信息越出所属卡片：{escaping_cards}")
            if metrics["adjacentTextOverlaps"]:
                raise RuntimeError(f"{case_id} 相邻卡片文字交叠：{metrics['adjacentTextOverlaps']}")
            if metrics["structure"] != {
                "contentTag": "SECTION",
                "contentParentTag": "MAIN",
                "footerParentTag": "MAIN",
            }:
                raise RuntimeError(f"{case_id} HTML 节点嵌套错误：{metrics['structure']}")
            active_html_path.with_name(active_html_path.stem + ".layout.json").write_text(
                json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            image_path = active_image_path
            await page.screenshot(path=str(image_path), full_page=True)
            await page.close()
            with Image.open(image_path) as rendered:
                original = rendered.convert("RGB")
                for label, width in (
                    ("432", 432),
                    ("30pct", round(original.width * 0.30)),
                    ("50pct", round(original.width * 0.50)),
                ):
                    height = round(original.height * width / original.width)
                    original.resize((width, height), Image.Resampling.LANCZOS).save(
                        image_path.with_name(image_path.stem + f"-{label}.png")
                    )
                mobile = original.resize(
                    (432, round(original.height * 432 / original.width)),
                    Image.Resampling.LANCZOS,
                )
                mobile.save(image_path.with_name(image_path.stem + "-q85.jpg"), "JPEG", quality=85)
            return str(image_path)

        renderer = T2IRenderer(native, assets, timeout=120)
        if args.template_root:
            renderer.loader = T2ITemplateLoader(root=args.template_root.resolve())

        for case_id in selected_cases:
            case_root = output / "cases" / case_id / args.variant
            html_root = case_root / "html"
            image_root = case_root / "images"
            html_root.mkdir(parents=True, exist_ok=True)
            image_root.mkdir(parents=True, exist_ok=True)
            events, details = case_events(case_id)
            visual_cache = None
            visual_metadata = None
            visual_event_id = details.get("visual_event_id")

            if details.get("visual_kind") == "cached-public":
                visual_cache, visual_metadata = write_fixture_cache(
                    output / "visual-caches" / case_id,
                    visual_event_id,
                    source_visual_cache,
                )
            elif details.get("visual_kind") == "synthetic-geometry":
                visual_cache, visual_metadata = write_fixture_cache(
                    output / "visual-caches" / case_id,
                    visual_event_id,
                    source_visual_cache,
                    synthetic=True,
                )
            elif details.get("visual_kind") == "corrupt":
                visual_cache, visual_metadata = write_fixture_cache(
                    output / "visual-caches" / case_id,
                    visual_event_id,
                    source_visual_cache,
                    corrupt=True,
                )

            service = CalendarService(
                output / "samples" / case_id,
                visual_cache=visual_cache,
            )
            health_age = timedelta(days=details.get("health_age_days", 0))
            health_at = NOW - health_age
            freshness = details.get("freshness", "FRESH")
            coverage = details.get("coverage", "COMPLETE")
            service._update_health_state = lambda: None
            service._source_datasets = {"gamekee": list(events)}
            service._has_snapshot = True
            service.freshness = freshness
            service.coverage = coverage
            service.last_success_at = health_at
            service.last_updated_at = health_at.isoformat()
            service.last_sync_error = details.get("sync_error", "")
            service._source_health["gamekee"] = SourceHealth(
                "gamekee",
                last_success_at=health_at,
                completeness=coverage,
                last_error_type="FIXTURE_FAILURE" if service.last_sync_error else "",
            )
            service._events = {event.id: event for event in events}

            snapshot = CalendarApplication(service).query_schedule(now=NOW)
            if visual_event_id and details.get("visual_kind") in {"cached-public", "synthetic-geometry"}:
                expected_path = visual_cache.resolve_path(visual_event_id)
                if snapshot.background_path is None or snapshot.background_path.resolve() != expected_path.resolve():
                    raise RuntimeError(f"{case_id} 的背景图没有按本地事件 ID 解析。")
            bundle = CalendarT2IPayloadBuilder().build(snapshot)
            case_meta = {
                "case_id": case_id,
                "description": details["description"],
                "variant": args.variant,
                "fixed_clock": NOW.isoformat(),
                "freshness": freshness,
                "coverage": coverage,
                "health_at": health_at.isoformat(),
                "input_events": [event.to_dict() for event in events],
                "visual_asset": visual_metadata,
                "page_count": len(bundle["pages"]),
                "displayed_event_ids": [
                    item["event_id"]
                    for page_data in bundle["pages"]
                    for item in page_data.get("active_items", []) + page_data.get("next_items", [])
                ],
                "fallback_text": snapshot.fallback_text,
                "payload_summary": {
                    "active_count": bundle.get("active_count_total"),
                    "next_count": bundle.get("next_count_total"),
                    "freshness": bundle.get("freshness"),
                    "coverage": bundle.get("coverage"),
                    "health_display": bundle.get("health_display"),
                    "source_display": bundle.get("source_display"),
                },
            }
            fixture_path = output / "cases" / case_id / "fixture.json"
            payload_path = output / "cases" / case_id / f"payload-{args.variant}.json"
            fixture_path.parent.mkdir(parents=True, exist_ok=True)
            fixture_path.write_text(
                json.dumps(case_meta, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            payload_path.write_text(
                json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8"
            )

            page_outputs = []
            for page_payload in bundle["pages"]:
                page_number = int(page_payload["page_number"])
                page_name = f"page-{page_number:02}"
                active_html_path = html_root / f"{page_name}.html"
                active_image_path = image_root / f"{page_name}.png"
                renderer_output = await renderer.render_payload(
                    "calendar_schedule",
                    {**bundle, **page_payload, "pages": [page_payload]},
                )
                if Path(renderer_output).resolve() != active_image_path.resolve():
                    raise RuntimeError("本地预览渲染器返回的输出路径与样例目录不匹配。")
                layout_path = active_html_path.with_name(active_html_path.stem + ".layout.json")
                image_path = Path(renderer_output)
                page_ids = [
                    item["event_id"]
                    for item in page_payload.get("active_items", []) + page_payload.get("next_items", [])
                ]
                page_outputs.append({
                    "page_number": page_number,
                    "event_ids": page_ids,
                    "html": str(active_html_path),
                    "html_sha256": sha256(active_html_path),
                    "layout": str(layout_path),
                    "layout_sha256": sha256(layout_path),
                    "image": str(image_path),
                    "image_sha256": sha256(image_path),
                    "image_dimensions": list(Image.open(image_path).size),
                    "preview_432": str(image_path.with_name(image_path.stem + "-432.png")),
                    "preview_30pct": str(image_path.with_name(image_path.stem + "-30pct.png")),
                    "preview_50pct": str(image_path.with_name(image_path.stem + "-50pct.png")),
                    "preview_jpeg_q85": str(image_path.with_name(image_path.stem + "-q85.jpg")),
                })

            expected_ids = [event.id for event in events]
            actual_ids = case_meta["displayed_event_ids"]
            if case_id == "multi-page":
                if set(actual_ids) != set(expected_ids) or len(actual_ids) != len(expected_ids):
                    raise AssertionError(f"17 条活动分页丢失或重复：expected={expected_ids}, actual={actual_ids}")
                if len(bundle["pages"]) < 2:
                    raise AssertionError("17 条活动没有分页，无法验收跨页行为。")
            if case_id == "story-dual":
                if set(actual_ids) != set(expected_ids) or len(actual_ids) != len(expected_ids):
                    raise AssertionError("两个剧情活动的阶段 ID 丢失或重复。")
            if case_id == "precision-mix":
                active_by_id = {item["event_id"]: item for item in bundle["active_items"]}
                next_by_id = {item["event_id"]: item for item in bundle["next_items"]}
                if "小时" not in active_by_id["fixture:exact"]["remaining"]:
                    raise AssertionError("EXACT 活动未提供精确剩余时间。")
                if active_by_id["fixture:date-only"]["end_precision"] != "DATE_ONLY":
                    raise AssertionError("DATE_ONLY 截止精度丢失。")
                if active_by_id["fixture:unknown"]["remaining"] != "结束时间未知":
                    raise AssertionError("UNKNOWN 截止时间未保持待确认状态。")
                if "日期级" not in next_by_id["fixture:date-only-start"]["starts_in"]:
                    raise AssertionError("DATE_ONLY 开始时间未保持日期级精度。")
                unknown_start = next_by_id["fixture:unknown-start"]
                if unknown_start["start_time_display"] != "时间待定" or unknown_start["starts_in"] != "即将开始":
                    raise AssertionError("UNKNOWN 开始时间错误显示为具体日期或倒计时。")
            if case_id == "multilingual-injection":
                if events[0].title not in snapshot.fallback_text:
                    raise AssertionError("文本回退异常移除了或改写了原始长标题。")
                layout = json.loads(Path(page_outputs[0]["layout"]).read_text(encoding="utf-8"))
                if layout["injectionElementCount"] != 0 or not layout["hasInjectionText"]:
                    raise AssertionError("HTML 字符串未安全转义或特殊标题未显示。")

            records.append({
                **case_meta,
                "fixture": str(fixture_path),
                "fixture_sha256": sha256(fixture_path),
                "payload": str(payload_path),
                "payload_sha256": sha256(payload_path),
                "pages": page_outputs,
                "template_root": str(renderer.loader.root),
            })

        await browser.close()

    assets.close()
    index = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "fixed_clock": NOW.isoformat(),
        "repository_base_sha": "70e109888090415e5d4dd761e6c8453d1e8292f7",
        "variant": args.variant,
        "renderer": "T2IRenderer + T2ITemplateLoader + local Playwright Chromium",
        "python": {"executable": sys.executable, "version": platform.python_version()},
        "browser": browser_metadata,
        "font_files": font_families(),
        "visual_cache_source": str(args.visual_cache_source.resolve()),
        "template_root": str(renderer.loader.root),
        "cases": records,
    }
    index_path = output / f"CASE_INDEX-{args.variant}.json"
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已生成 {len(records)} 个场景，索引：{index_path}")


if __name__ == "__main__":
    asyncio.run(main())
