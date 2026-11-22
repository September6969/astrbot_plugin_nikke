"""视觉修订的语义与结构回归，不依赖外部截图服务。"""
import re
from pathlib import Path

import pytest
from jinja2 import Environment

from astrbot_plugin_nikke.scripts.shared.t2i_preview_fixtures import get_cases
from astrbot_plugin_nikke.ui.t2i_templates import T2ITemplateLoader

ROOT = Path(__file__).resolve().parents[1]


def render(page, data):
    return Environment().from_string(T2ITemplateLoader().load(page)).render(**data)


def test_calendar_operations_feed_layout_and_single_footer(tmp_path):
    cases = get_cases("calendar_schedule", tmp_path)
    data = cases["long-title"]
    html = render("calendar_schedule", {**data, **data["pages"][0]})
    assert html.count("<footer") == 1
    assert "1600px" in html
    assert "height: 360px" in html
    assert "font-size: 64px" in html
    assert 'class="key-visual' in html
    assert 'class="panel"' not in html
    assert "妮姬日程" in html
    assert "进行中" in html
    assert "即将开始" in html
    assert "progress-bar" not in html
    assert "progress-track" not in html
    assert "ENDING SOON / 即将结束" not in html
    assert "default-src 'none'" in html
    assert "script-src 'none'" in html
    assert "img-src data:" in html
    for item in data["pages"][0]["active_items"]:
        assert item["title"] in html
        assert item["remaining"] in html
    many = cases["many-events"]
    assert len(many["pages"]) > 1
    first_page_html = render("calendar_schedule", {**many, **many["pages"][0]})
    assert first_page_html.count("<footer") == 1
    assert "第 1 /" in first_page_html


@pytest.mark.parametrize("state", ["AVAILABLE", "PARTIAL", "UNAVAILABLE", "UNKNOWN", "EMPTY"])
def test_state_badges_preserve_explicit_state(state):
    macros = (ROOT / "templates/t2i/_shared/macros.jinja").read_text(encoding="utf-8")
    template = Environment(autoescape=True).from_string(macros + "{{ status_badge(state) }}")
    html = template.render(state=state)
    assert f"state-{state.lower()}" in html and f">{state}</span>" in html
    injected = template.render(state='<img src=x onerror=1>')
    assert '<img src=x' not in injected and 'state-neutral' in injected


def _luminance(value):
    channels = [int(value[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    linear = [c / 12.92 if c <= .04045 else ((c + .055) / 1.055) ** 2.4 for c in channels]
    return sum(c * weight for c, weight in zip(linear, (.2126, .7152, .0722)))


def _contrast(foreground, background):
    low, high = sorted((_luminance(foreground), _luminance(background)))
    return (high + .05) / (low + .05)


def _token_block(css, selector):
    body = re.search(rf"(?:^|\n){re.escape(selector)}\s*\{{([^}}]+)\}}", css)[1]
    return dict(re.findall(r"--([a-z0-9-]+):\s*#([0-9a-f]{6})", body))


# AUD-017：旧用例假设 .today 为深色底（#222a33），而 profile.html 的 .today 实际是浅蓝底
# （#eaf2f9），导致暗色徽标在真实底色上只有 1.59–1.87:1。现改为读取共享令牌与模板中的
# 真实底色计算对比度；状态色均由 tokens.css 的 :root（暗色）/.theme-light（亮色）提供。
@pytest.mark.parametrize("state", ["available", "partial", "unavailable", "rate-limited", "error"])
def test_state_token_contrast_on_real_backgrounds(state):
    tokens = (ROOT / "templates/t2i/_shared/tokens.css").read_text(encoding="utf-8")
    dark, light = _token_block(tokens, ":root"), _token_block(tokens, ".theme-light")
    profile = (ROOT / "templates/t2i/profile.html").read_text(encoding="utf-8")
    today = re.search(r"\.profile \.today \{background:#([0-9a-f]{6})", profile)[1]
    page = re.search(r"\.profile \{[^}]*background:#([0-9a-f]{6})", profile)[1]
    surface = re.search(r"--surface:#([0-9a-f]{3,6})", profile)[1]
    surface = "".join(ch * 2 for ch in surface) if len(surface) == 3 else surface
    for background in (today, page, surface):
        assert _contrast(light[f"state-{state}"], background) >= 4.5, (state, background)
    for background in (dark["bg"], dark["panel"]):
        assert _contrast(dark[f"state-{state}"], background) >= 4.5, (state, background)


def test_profile_uses_light_state_tokens_without_dark_today_override():
    components = (ROOT / "templates/t2i/_shared/components.css").read_text(encoding="utf-8")
    profile = (ROOT / "templates/t2i/profile.html").read_text(encoding="utf-8")
    raid = (ROOT / "templates/t2i/_shared/raid.css").read_text(encoding="utf-8")
    assert '<main class="profile theme-light">' in profile
    # 已删除：.profile .today .state-*（暗色值落在浅蓝底）与无对应元素的 .schedule .state-*。
    assert ".today .state-" not in components + profile
    assert ".schedule" not in components
    assert all("var(--state-" in rule for rule in re.findall(r"\.badge\.state-(?:available|partial|unavailable|rate-limited|error)\s*\{[^}]+\}", components))
    # raid.css 每个选择器只声明一次，不再出现同文件自覆写。
    selectors = [selector.strip() for selector in re.findall(r"([^{}]+)\{[^{}]*\}", re.sub(r"/\*.*?\*/", "", raid, flags=re.S))]
    assert len(selectors) == len(set(selectors))
