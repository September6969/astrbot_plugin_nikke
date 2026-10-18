"""绑定扩展面板的静态可访问性与安全序列化合同。"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_extension_announces_login_and_submission_statuses():
    html = (ROOT / "extension" / "popup.html").read_text(encoding="utf-8")
    assert 'id="loginStatusText" role="status" aria-live="polite"' in html
    assert 'id="status" class="status" role="status" aria-live="polite"' in html
    assert 'id="openLogin" class="secondary" type="button"' in html
    assert 'id="submit" class="primary" type="button"' in html
    assert 'max-width: 100vw' in html
    assert 'overflow-wrap: anywhere' in html


def test_extension_uses_text_and_json_serialization_for_dynamic_session_data():
    script = (ROOT / "extension" / "popup.js").read_text(encoding="utf-8")
    assert "JSON.stringify({ token, cookies, x_common_params: xCommonParams, user_agent: navigator.userAgent })" in script
    assert "textContent =" in script
    assert "innerHTML" not in script
    assert "url.password" in script
    assert "allowedOrigins.includes(url.origin)" in script
