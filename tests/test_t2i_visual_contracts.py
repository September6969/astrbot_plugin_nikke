"""视觉修订的语义与结构回归，不依赖外部截图服务。"""
import re
from pathlib import Path

import pytest
from jinja2 import Environment

from astrbot_plugin_nikke.scripts.t2i_preview_fixtures import get_cases
from astrbot_plugin_nikke.ui.t2i_templates import T2ITemplateLoader

ROOT = Path(__file__).resolve().parents[1]


def render(page, data):
    return Environment().from_string(T2ITemplateLoader().load(page)).render(**data)


def test_calendar_operations_feed_layout_and_single_footer(tmp_path):
    cases = get_cases("calendar_schedule", tmp_path)
    data = cases["long-title"]
    html = render("calendar_schedule", data)
    assert html.count("<footer") == 1
    assert "1600" in html
    assert "730px" in html and "1180px" in html
    assert "ACTIVE OPERATIONS" in html
    assert "progress-bar" not in html
    assert "progress-track" not in html
    assert "ENDING SOON / 即将结束" not in html
    for item in data["pages"][0]["active_items"]:
        assert item["title"] in html
        assert item["remaining"] in html
    many = cases["many-events"]
    assert len(many["pages"]) > 1
    first_page_html = render("calendar_schedule", {**many, **many["pages"][0]})
    assert first_page_html.count("<footer") == 1
    assert "PAGE 1 /" in first_page_html


@pytest.mark.parametrize("state", ["AVAILABLE", "PARTIAL", "UNAVAILABLE", "UNKNOWN", "EMPTY"])
def test_state_badges_preserve_explicit_state(state):
    macros = (ROOT / "templates/t2i/_shared/macros.jinja").read_text(encoding="utf-8")
    template = Environment(autoescape=True).from_string(macros + "{{ status_badge(state) }}")
    html = template.render(state=state)
    assert f"state-{state.lower()}" in html and f">{state}</span>" in html
    injected = template.render(state='<img src=x onerror=1>')
    assert '<img src=x' not in injected and 'state-neutral' in injected


@pytest.mark.parametrize("selector,background", [
    (".profile .state-available", "eeefed"),
    (".profile .state-partial", "eeefed"),
    (".profile .state-unavailable", "eeefed"),
    (".profile .today .state-available", "222a33"),
    (".profile .today .state-partial", "222a33"),
    (".profile .today .state-unavailable", "222a33"),
])
def test_state_text_contrast_on_light_and_today(selector, background):
    css = (ROOT / "templates/t2i/_shared/components.css").read_text(encoding="utf-8")
    rule = next(body for selectors, body in re.findall(r"([^{}]+)\{([^{}]+)\}", css)
                if selector in [s.strip() for s in selectors.split(",")])
    color = re.search(r"(?:^|;)\s*color:#([0-9a-f]{6})", rule)[1]
    def luminance(value):
        channels = [int(value[i:i+2], 16) / 255 for i in (0, 2, 4)]
        linear = [c / 12.92 if c <= .04045 else ((c + .055) / 1.055) ** 2.4 for c in channels]
        return sum(c * weight for c, weight in zip(linear, (.2126, .7152, .0722)))
    low, high = sorted((luminance(color), luminance(background)))
    assert (high + .05) / (low + .05) >= 4.5
