# SPDX-License-Identifier: GPL-3.0-or-later
"""BlaBlaLink 账号安全绑定向导页面模板生成器。

特性：
1. 状态机驱动（VALID / EXPIRED / USED / SUCCESS / FAILED）；
2. 实时倒计时与自动失效；
3. Edge 与 Chrome 双浏览器标签页完整解压与安装教程；
4. 轮询同步与成功页面无跳转平滑切换（显示脱敏 QQ 与昵称）；
5. 响应式布局（适配 1920x1080、1366x768 及手机移动端窄屏）；
6. 常见问题 (FAQ) 折叠卡片。
"""

from __future__ import annotations

import html
import time
from typing import Any


def render_bind_page(token: str, session: dict[str, Any] | None, base_url: str) -> str:
    now = int(time.time())
    safe_token = html.escape(token)

    if not session:
        initial_state = "INVALID"
        remaining_seconds = 0
    elif session.get("used_at") is not None or session.get("status") == "consumed":
        initial_state = "USED"
        remaining_seconds = 0
    elif session.get("expires_at", 0) < now:
        initial_state = "EXPIRED"
        remaining_seconds = 0
    else:
        initial_state = "VALID"
        remaining_seconds = max(0, session.get("expires_at", 0) - now)

    initial_minutes = remaining_seconds // 60
    initial_secs = remaining_seconds % 60
    time_str = f"{initial_minutes:02d}:{initial_secs:02d}"

    page_html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, shrink-to-fit=no">
  <title>NIKKE · BlaBlaLink 安全绑定</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
      background: #111318;
      color: #f2f3f5;
      margin: 0;
      padding: 20px 16px;
      line-height: 1.6;
    }}
    .container {{
      max-width: 820px;
      margin: 20px auto;
      background: #1a1e25;
      border: 1px solid #343b46;
      border-top: 4px solid #e9b85a;
      border-radius: 12px;
      padding: 32px 28px;
      box-shadow: 0 8px 24px rgba(0, 0, 0, 0.45);
    }}
    h1 {{
      font-size: clamp(22px, 3.5vw, 28px);
      margin: 0 0 16px 0;
      color: #ffffff;
      display: flex;
      align-items: center;
      gap: 12px;
    }}
    .status-bar {{
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding: 14px 18px;
      border-radius: 8px;
      margin-bottom: 24px;
      font-weight: 600;
    }}
    .status-valid {{
      background: rgba(143, 188, 162, 0.12);
      border: 1px solid #8fbca2;
      color: #8fbca2;
    }}
    .status-expired, .status-invalid {{
      background: rgba(227, 161, 161, 0.12);
      border: 1px solid #e3a1a1;
      color: #e3a1a1;
    }}
    .status-used {{
      background: rgba(233, 184, 90, 0.12);
      border: 1px solid #e9b85a;
      color: #e9b85a;
    }}
    .timer-badge {{
      font-variant-numeric: tabular-nums;
      background: rgba(0, 0, 0, 0.3);
      padding: 4px 10px;
      border-radius: 6px;
      font-size: 15px;
    }}
    .notice-box {{
      background: #222731;
      border-left: 4px solid #e9b85a;
      padding: 14px 16px;
      border-radius: 6px;
      margin-bottom: 24px;
      font-size: 14px;
      color: #d1d5db;
    }}
    .step-card {{
      background: #20252e;
      border: 1px solid #2e3542;
      border-radius: 10px;
      padding: 22px;
      margin-bottom: 20px;
    }}
    .step-header {{
      display: flex;
      align-items: center;
      gap: 12px;
      margin-bottom: 14px;
    }}
    .step-num {{
      width: 28px;
      height: 28px;
      background: #e9b85a;
      color: #111318;
      border-radius: 50%;
      display: flex;
      align-items: center;
      justify-content: center;
      font-weight: bold;
      font-size: 15px;
      flex-shrink: 0;
    }}
    .step-title {{
      font-size: 17px;
      font-weight: 700;
      color: #ffffff;
      margin: 0;
    }}
    .btn {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      padding: 10px 20px;
      border-radius: 8px;
      font-weight: 600;
      font-size: 14px;
      text-decoration: none;
      transition: all 0.2s ease;
      cursor: pointer;
      border: none;
    }}
    .btn-primary {{
      background: #e9b85a;
      color: #111318;
    }}
    .btn-primary:hover {{
      background: #f0c575;
      color: #000000;
    }}
    .btn-secondary {{
      background: #2b3240;
      color: #e5e7eb;
      border: 1px solid #434c5e;
      margin-left: 10px;
    }}
    .btn-secondary:hover {{
      background: #374052;
      color: #ffffff;
    }}
    .btn-copy {{
      background: #2b3240;
      color: #e9b85a;
      border: 1px solid #e9b85a;
      padding: 6px 14px;
      font-size: 13px;
    }}
    .tabs-nav {{
      display: flex;
      gap: 8px;
      border-bottom: 1px solid #374151;
      margin-bottom: 16px;
    }}
    .tab-btn {{
      background: transparent;
      border: none;
      color: #9ca3af;
      padding: 8px 16px;
      font-size: 14px;
      font-weight: 600;
      cursor: pointer;
      border-bottom: 2px solid transparent;
      transition: all 0.2s;
    }}
    .tab-btn.active {{
      color: #e9b85a;
      border-bottom-color: #e9b85a;
    }}
    .tab-pane {{
      display: none;
    }}
    .tab-pane.active {{
      display: block;
    }}
    ol.guide-steps {{
      padding-left: 20px;
      margin: 10px 0;
    }}
    ol.guide-steps li {{
      padding: 6px 0;
      color: #d1d5db;
    }}
    code.path {{
      background: #111318;
      color: #e9b85a;
      padding: 2px 6px;
      border-radius: 4px;
      font-family: Consolas, monospace;
      font-size: 13px;
      word-break: break-all;
    }}
    .callout-warn {{
      background: rgba(233, 184, 90, 0.1);
      border-left: 3px solid #e9b85a;
      padding: 10px 14px;
      margin: 12px 0;
      font-size: 13px;
      color: #e9b85a;
      border-radius: 4px;
    }}
    details.faq-item {{
      background: #20252e;
      border: 1px solid #2e3542;
      border-radius: 8px;
      margin-bottom: 10px;
      padding: 12px 16px;
    }}
    details.faq-item summary {{
      font-weight: 600;
      color: #e5e7eb;
      cursor: pointer;
      outline: none;
    }}
    details.faq-item .faq-ans {{
      margin-top: 10px;
      font-size: 14px;
      color: #9ca3af;
      padding-left: 6px;
    }}
    .success-card {{
      text-align: center;
      padding: 40px 20px;
    }}
    .success-icon {{
      width: 64px;
      height: 64px;
      border-radius: 50%;
      background: rgba(143, 188, 162, 0.2);
      color: #8fbca2;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 32px;
      margin: 0 auto 20px;
    }}
    .info-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
      gap: 16px;
      margin: 24px 0;
      text-align: left;
    }}
    .info-item {{
      background: #222731;
      border: 1px solid #343b46;
      border-radius: 8px;
      padding: 14px 16px;
    }}
    .info-label {{
      font-size: 12px;
      color: #9ca3af;
      margin-bottom: 4px;
    }}
    .info-value {{
      font-size: 16px;
      font-weight: 600;
      color: #f3f4f6;
    }}
    @media (max-width: 600px) {{
      .container {{ padding: 20px 16px; margin: 10px auto; }}
      .status-bar {{ flex-direction: column; align-items: flex-start; }}
      .btn {{ width: 100%; margin-left: 0 !important; margin-top: 8px; }}
    }}
  </style>
</head>
<body>
  <div class="container">
    <h1>NIKKE · BlaBlaLink 安全绑定</h1>

    <div id="statusHeader" class="status-bar status-{initial_state.lower()}">
      <span id="statusText">
        {"● 链接有效" if initial_state == "VALID" else ("● 链接已过期（链接无效）" if initial_state == "EXPIRED" else ("● 此绑定链接已经使用（链接无效）" if initial_state == "USED" else "● 链接无效"))}
      </span>
      <span id="timerBadge" class="timer-badge" {"style='display:none'" if initial_state != "VALID" else ""}>
        剩余有效时间：<span id="countdown">{time_str}</span>
      </span>
    </div>

    <!-- 成功视图 -->
    <div id="viewSuccess" class="success-card" style="display: none;">
      <div class="success-icon">✓</div>
      <h2 style="color:#ffffff; margin-bottom: 8px;">绑定成功！</h2>
      <p style="color:#9ca3af; margin-bottom: 20px;">游戏数据已经与你的 QQ 账号成功关联。</p>
      <div class="info-grid">
        <div class="info-item">
          <div class="info-label">BlaBlaLink 昵称</div>
          <div id="succNickname" class="info-value">—</div>
        </div>
        <div class="info-item">
          <div class="info-label">绑定的 QQ 账号</div>
          <div id="succQQ" class="info-value">—</div>
        </div>
      </div>
      <div class="notice-box" style="text-align: left;">
        <strong>后续说明：</strong><br>
        1. 绑定助手扩展已不再需要，可将其卸载或在扩展管理中停用；<br>
        2. 返回 QQ 发送 <code>/妮姬 账号 状态</code> 可查验绑定有效性；<br>
        3. 发送 <code>/妮姬 我的</code> 或 <code>/妮姬 查询 角色 &lt;名字&gt;</code> 即可生成你的游戏数据卡片。
      </div>
    </div>

    <!-- 过期 / 已使用视图 -->
    <div id="viewInvalid" style="{"display:none" if initial_state == "VALID" else ""}">
      <div class="notice-box" style="border-left-color: #e3a1a1; color: #fca5a5;">
        <strong>提示：</strong>
        <span id="invalidDesc">
          {"本链接已过期。请返回 QQ，私聊重新发送 /妮姬 账号 绑定 获取新链接。" if initial_state == "EXPIRED" else "此绑定链接已经使用过。如需重新绑定，请返回 QQ 重新生成。"}
        </span>
      </div>
    </div>

    <!-- 主教程流程 (仅在 VALID 时展示) -->
    <div id="viewTutorial" style="{"display:none" if initial_state != "VALID" else ""}">
      <div class="notice-box">
        <strong>安全说明：</strong>本链接仅供你本人使用，成功绑定后立即失效。账号密码<strong>只在 BlaBlaLink 官网输入</strong>，机器人不会接收或保存你的密码。
      </div>

      <!-- Step 1 -->
      <div class="step-card">
        <div class="step-header">
          <div class="step-num">1</div>
          <h2 class="step-title">下载 NIKKE QQ 安全绑定助手</h2>
        </div>
        <p style="color: #9ca3af; font-size: 14px; margin-top: 0;">
          扩展仅负责读取当前 BlaBlaLink 登录会话中完成绑定所需的 Cookie，不会读取、保存或上传你的账号密码。
        </p>
        <div style="margin-top: 14px;">
          <a href="/download" class="btn btn-primary" download="nikke-bind-extension.zip">下载扩展 (ZIP)</a>
          <a href="https://github.com/September6969/astrbot_plugin_nikke/releases" target="_blank" class="btn btn-secondary">GitHub Releases 备用下载</a>
        </div>
      </div>

      <!-- Step 2 -->
      <div class="step-card">
        <div class="step-header">
          <div class="step-num">2</div>
          <h2 class="step-title">安装浏览器扩展 (Edge / Chrome)</h2>
        </div>
        <div class="tabs-nav" role="tablist">
          <button type="button" class="tab-btn active" onclick="switchTab('edge')">Microsoft Edge</button>
          <button type="button" class="tab-btn" onclick="switchTab('chrome')">Google Chrome</button>
        </div>

        <div id="tabEdge" class="tab-pane active">
          <ol class="guide-steps">
            <li>下载完成后，将 ZIP 压缩包<strong>解压到一个固定的文件夹</strong>（绑定完成前不要删除或移动该文件夹）。</li>
            <li>在 Edge 地址栏输入 <code class="path">edge://extensions</code> 并回车。</li>
            <li>打开页面<strong>左下角</strong>的「开发人员模式」开关。</li>
            <li>点击顶部的<strong>「加载解压缩的扩展」</strong>按钮。</li>
            <li>在弹出的窗口中，选择刚才解压出来的扩展文件夹。</li>
            <li>安装成功后，点击浏览器右上角的“拼图”扩展图标，找到「NIKKE QQ 安全绑定助手」并点击<strong>固定到工具栏</strong>。</li>
          </ol>
        </div>

        <div id="tabChrome" class="tab-pane">
          <ol class="guide-steps">
            <li>将下载的 ZIP 压缩包<strong>解压到一个固定的文件夹</strong>。</li>
            <li>在 Chrome 地址栏输入 <code class="path">chrome://extensions</code> 并回车。</li>
            <li>打开页面<strong>右上角</strong>的「开发者模式」开关。</li>
            <li>点击左上角的<strong>「加载已解压的扩展程序」</strong>。</li>
            <li>选择解压出的扩展文件夹。</li>
            <li>点击浏览器右上角的扩展图标，将「NIKKE QQ 安全绑定助手」固定到工具栏。</li>
          </ol>
        </div>

        <div class="callout-warn">
          <strong>避坑提示：</strong>请勿直接将未解压的 ZIP 文件拖拽进扩展页面！必须先解压到文件夹，然后点击【加载解压的扩展】选择该文件夹。
        </div>
      </div>

      <!-- Step 3 -->
      <div class="step-card">
        <div class="step-header">
          <div class="step-num">3</div>
          <h2 class="step-title">登录 BlaBlaLink 官网</h2>
        </div>
        <ol class="guide-steps">
          <li>点击下方按钮打开 BlaBlaLink 官网。</li>
          <li>正常登录你的 NIKKE / BlaBlaLink 账号。</li>
          <li>登录后，确认网页右侧已成功出现你的游戏角色资料。</li>
        </ol>
        <div style="margin-top: 14px;">
          <a href="https://www.blablalink.com/" target="_blank" class="btn btn-primary">打开 BlaBlaLink 官网</a>
        </div>
        <div class="callout-warn">
          <strong>重要：</strong>账号和密码只在 BlaBlaLink 官网填写！切勿将密码填入任何其他页面或发送给机器人。若浏览器中已经登录，可直接进入第 4 步。
        </div>
      </div>

      <!-- Step 4 -->
      <div class="step-card">
        <div class="step-header">
          <div class="step-num">4</div>
          <h2 class="step-title">打开扩展完成绑定</h2>
        </div>
        <ol class="guide-steps">
          <li>保持当前的 BlaBlaLink 页面打开。</li>
          <li>点击浏览器右上角工具栏的<strong>「NIKKE QQ 安全绑定助手」</strong>图标。</li>
          <li>扩展会自动检测登录状态并填入本次绑定地址；若未自动填入，可点击下方复制链接并粘贴：</li>
        </ol>
        <div style="display: flex; gap: 8px; margin: 10px 0 16px 20px; align-items: center; flex-wrap: wrap;">
          <input type="text" id="bindUrlBox" value="{base_url}/bind/{safe_token}" readonly style="flex:1; min-width:260px; background:#111318; border:1px solid #434c5e; color:#f3f4f6; padding:8px 12px; border-radius:6px; font-size:13px;">
          <button type="button" class="btn btn-copy" onclick="copyBindUrl()">复制链接</button>
        </div>
        <ol class="guide-steps" start="4">
          <li>确认扩展显示“已检测到 BlaBlaLink 登录”，点击扩展内的<strong>「已登录，提交绑定」</strong>。</li>
          <li>提交成功后，扩展将提示成功，本网页也会自动同步刷新！</li>
        </ol>
      </div>

      <!-- FAQ -->
      <h3 style="color: #ffffff; margin: 28px 0 14px 0;">常见问题 (FAQ)</h3>
      <details class="faq-item">
        <summary>找不到“开发者模式”开关？</summary>
        <div class="faq-ans">
          Microsoft Edge 位于扩展页面 (<code>edge://extensions</code>) 的<strong>左下角</strong>；<br>
          Google Chrome 位于扩展页面 (<code>chrome://extensions</code>) 的<strong>右上角</strong>。
        </div>
      </details>
      <details class="faq-item">
        <summary>找不到扩展图标？</summary>
        <div class="faq-ans">
          点击浏览器右上角地址栏右侧的“拼图”图标，在弹出的下拉列表中找到「NIKKE QQ 安全绑定助手」，点击旁边的图钉图标即可将其固定到工具栏。
        </div>
      </details>
      <details class="faq-item">
        <summary>扩展中提示“未检测到 BlaBlaLink 登录”？</summary>
        <div class="faq-ans">
          请确认你已经登录了 <code>https://www.blablalink.com/</code> 并能看到个人主页，登录后请刷新一次该网页，再重新点击打开扩展图标。
        </div>
      </details>
      <details class="faq-item">
        <summary>绑定错了账号怎么办？</summary>
        <div class="faq-ans">
          请先在 BlaBlaLink 官网退出当前账号并登录正确账号。然后返回 QQ 发送 <code>/妮姬 账号 解绑</code>，再重新发送 <code>/妮姬 账号 绑定</code> 获取新链接完成绑定。
        </div>
      </details>
    </div>
    <p style="color: #9ca3af; font-size: 13px; margin-top: 24px; text-align: center; border-top: 1px solid #2e3542; padding-top: 16px;">
      绑定链接仅供本人使用，请勿转发或公开截图。有效链接可从浏览器地址栏复制到扩展；失效后请向机器人重新申请。
    </p>
  </div>

  <script>
    var token = "{safe_token}";
    var remainingSeconds = {remaining_seconds};
    var currentState = "{initial_state}";

    function switchTab(tab) {{
      var edgeBtn = document.querySelectorAll('.tab-btn')[0];
      var chromeBtn = document.querySelectorAll('.tab-btn')[1];
      var edgePane = document.getElementById('tabEdge');
      var chromePane = document.getElementById('tabChrome');
      if (tab === 'edge') {{
        edgeBtn.classList.add('active');
        chromeBtn.classList.remove('active');
        edgePane.classList.add('active');
        chromePane.classList.remove('active');
      }} else {{
        chromeBtn.classList.add('active');
        edgeBtn.classList.remove('active');
        chromePane.classList.add('active');
        edgePane.classList.remove('active');
      }}
    }}

    function copyBindUrl() {{
      var input = document.getElementById('bindUrlBox');
      if (!input) return;
      input.select();
      input.setSelectionRange(0, 99999);
      if (navigator.clipboard && navigator.clipboard.writeText) {{
        navigator.clipboard.writeText(input.value).then(function() {{
          alert('绑定链接已复制到剪贴板！');
        }});
      }} else {{
        document.execCommand('copy');
        alert('绑定链接已复制到剪贴板！');
      }}
    }}

    // 倒计时逻辑
    if (remainingSeconds > 0 && currentState === 'VALID') {{
      var timerElem = document.getElementById('countdown');
      var interval = setInterval(function() {{
        remainingSeconds--;
        if (remainingSeconds <= 0) {{
          clearInterval(interval);
          setExpiredUI();
        }} else {{
          var m = Math.floor(remainingSeconds / 60);
          var s = remainingSeconds % 60;
          timerElem.textContent = (m < 10 ? '0' : '') + m + ':' + (s < 10 ? '0' : '') + s;
        }}
      }}, 1000);
    }}

    function setExpiredUI() {{
      currentState = 'EXPIRED';
      var header = document.getElementById('statusHeader');
      var text = document.getElementById('statusText');
      var badge = document.getElementById('timerBadge');
      header.className = 'status-bar status-expired';
      text.textContent = '● 链接已过期';
      badge.style.display = 'none';

      document.getElementById('viewTutorial').style.display = 'none';
      var invalidView = document.getElementById('viewInvalid');
      invalidView.style.display = 'block';
      document.getElementById('invalidDesc').textContent = '本链接已过期。请返回 QQ，私聊重新发送 /妮姬 账号 绑定 获取新链接。';
    }}

    function setSuccessUI(nickname, maskedQQ) {{
      currentState = 'SUCCESS';
      var header = document.getElementById('statusHeader');
      var text = document.getElementById('statusText');
      var badge = document.getElementById('timerBadge');
      header.className = 'status-bar status-valid';
      text.textContent = '● 绑定成功';
      badge.style.display = 'none';

      document.getElementById('viewTutorial').style.display = 'none';
      document.getElementById('viewInvalid').style.display = 'none';

      var succView = document.getElementById('viewSuccess');
      document.getElementById('succNickname').textContent = nickname || '指挥官';
      document.getElementById('succQQ').textContent = maskedQQ || '******';
      succView.style.display = 'block';
    }}

    // 轮询检查绑定状态
    if (currentState === 'VALID') {{
      var pollInterval = setInterval(function() {{
        if (currentState !== 'VALID') {{
          clearInterval(pollInterval);
          return;
        }}
        fetch('/api/bind/status?token=' + encodeURIComponent(token))
          .then(function(res) {{ return res.json(); }})
          .then(function(data) {{
            if (data.ok && (data.status === 'consumed' || data.status === 'bound')) {{
              clearInterval(pollInterval);
              setSuccessUI(data.nickname, data.masked_qq);
            }} else if (data.expired) {{
              clearInterval(pollInterval);
              setExpiredUI();
            }}
          }})
          .catch(function() {{}});
      }}, 2500);
    }}
  </script>
</body>
</html>"""
    return page_html
