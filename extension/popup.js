// SPDX-License-Identifier: GPL-3.0-or-later
const bindInput = document.getElementById("bindUrl");
const statusBox = document.getElementById("status");
const loginDot = document.getElementById("loginDot");
const loginStatusText = document.getElementById("loginStatusText");
const charPreview = document.getElementById("charPreview");

function setStatus(message, state) {
  if (statusBox) {
    statusBox.textContent = message;
    statusBox.dataset.state = state;
  }
}

if (typeof chrome !== "undefined" && chrome.storage?.local) {
  chrome.storage.local.get("bindUrl", ({ bindUrl }) => {
    if (bindUrl && bindInput && !bindInput.value) {
      bindInput.value = bindUrl;
    }
  });
}

// 尝试从当前激活标签页自动识别绑定 URL
if (typeof chrome !== "undefined" && chrome.tabs?.query) {
  try {
    chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
      if (tabs && tabs[0]?.url) {
        const tabUrl = tabs[0].url;
        if (tabUrl.includes("/bind/")) {
          try {
            const u = new URL(tabUrl);
            if (u.pathname.match(/^\/bind\/[A-Za-z0-9_-]{32,128}$/) && bindInput) {
              bindInput.value = tabUrl;
            }
          } catch {}
        }
      }
    });
  } catch {}
}

// 自动检测 BlaBlaLink 官网登录态
async function checkLoginStatus() {
  if (typeof chrome === "undefined" || !chrome.cookies?.getAll) return;
  try {
    const cookies = await chrome.cookies.getAll({ domain: "blablalink.com" });
    const required = ["game_token", "game_uid", "game_openid"];
    const names = new Set(cookies.map(c => c.name));
    const hasAll = required.every(name => names.has(name));

    if (hasAll) {
      if (loginDot) loginDot.className = "indicator-dot online";
      if (loginStatusText) loginStatusText.textContent = "✓ 已检测到 BlaBlaLink 登录";

      if (chrome.storage?.local) {
        const stored = await chrome.storage.local.get("xCommonParams");
        if (stored?.xCommonParams) {
          try {
            const parsed = JSON.parse(stored.xCommonParams);
            if (parsed && typeof parsed === "object" && parsed.openid && charPreview) {
              charPreview.textContent = "就绪账号 OpenID: " + String(parsed.openid).slice(0, 10) + "…";
              charPreview.style.display = "inline-block";
            }
          } catch {}
        }
      }
    } else {
      if (loginDot) loginDot.className = "indicator-dot offline";
      if (loginStatusText) loginStatusText.textContent = "未检测到 BlaBlaLink 登录";
      if (charPreview) charPreview.style.display = "none";
    }
  } catch {}
}

checkLoginStatus();

function parseBindUrl() {
  const val = bindInput ? bindInput.value.trim() : "";
  if (!val) throw new Error("请输入或粘贴机器人提供的绑定链接");
  const url = new URL(val);
  const manifest = chrome.runtime.getManifest();
  const hostPerms = manifest.host_permissions || [];
  const allowedOrigins = hostPerms
    .filter(pattern => !pattern.includes("*."))
    .map(pattern => new URL(pattern.replace(/\/\*$/, "")).origin);

  if (url.protocol !== "https:" || url.username || url.password || url.search || url.hash || !allowedOrigins.includes(url.origin)) {
    throw new Error("请使用此扩展所属机器人提供的HTTPS绑定链接");
  }
  const match = url.pathname.match(/^\/bind\/([A-Za-z0-9_-]{32,128})$/);
  if (!match) throw new Error("绑定链接格式不正确");
  return { url, token: match[1] };
}

function buildFallbackContext(cookies) {
  const openid = cookies.find((cookie) => cookie.name === "game_openid")?.value;
  if (!openid) return "";
  const gameId = cookies.find((cookie) => cookie.name === "game_gameid")?.value || "3";
  return JSON.stringify({
    openid,
    intl_game_id: gameId,
    language: "zh-TW",
    env: "prod",
    source: "outer",
    data_statistics_scene: "outer",
  });
}

const openLoginBtn = document.getElementById("openLogin");
if (openLoginBtn) {
  openLoginBtn.addEventListener("click", async () => {
    try {
      if (bindInput && bindInput.value.trim()) {
        try {
          parseBindUrl();
          if (chrome.storage?.local) {
            await chrome.storage.local.set({ bindUrl: bindInput.value.trim() });
          }
        } catch {}
      }
      if (chrome.tabs?.create) {
        await chrome.tabs.create({ url: "https://www.blablalink.com/login", active: true });
      }
      setStatus("请在新标签页完成官网登录和验证码。", "pending");
    } catch (error) {
      setStatus(error.message, "error");
    }
  });
}

const submitBtn = document.getElementById("submit");
if (submitBtn) {
  submitBtn.addEventListener("click", async () => {
    submitBtn.disabled = true;
    setStatus("正在读取并验证登录状态…", "pending");
    try {
      const { url, token } = parseBindUrl();
      const cookies = await chrome.cookies.getAll({ url: "https://www.blablalink.com/" });
      const required = ["game_token", "game_uid", "game_openid"];
      const names = new Set(cookies.map(cookie => cookie.name));
      const missing = required.filter(name => !names.has(name));
      if (missing.length) throw new Error(`尚未完成登录，缺少：${missing.join(", ")}`);

      const stored = await chrome.storage.local.get("xCommonParams");
      let cachedContext = "";
      try {
        const cached = JSON.parse(stored.xCommonParams || "null");
        const openid = cookies.find(cookie => cookie.name === "game_openid")?.value;
        if (cached && String(cached.openid) === openid) cachedContext = stored.xCommonParams;
      } catch {}

      const xCommonParams = cachedContext || buildFallbackContext(cookies);
      if (!xCommonParams) {
        throw new Error("尚未获取账号上下文。请确认已登录BlaBlaLink并刷新个人主页后重试。");
      }

      const response = await fetch(`${url.origin}/api/bind/cookies`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token, cookies, x_common_params: xCommonParams, user_agent: navigator.userAgent })
      });
      const result = await response.json();
      if (!response.ok || !result.ok) {
        const code = result.code || "";
        let errDesc = result.message || result.error || `提交失败 HTTP ${response.status}`;
        if (code === "TOKEN_EXPIRED") {
          errDesc = "绑定链接已过期，请返回 QQ 重新发送 /妮姬 账号 绑定";
        } else if (code === "TOKEN_USED") {
          errDesc = "此绑定链接已经使用过，请返回 QQ 重新生成";
        }
        throw new Error(errDesc);
      }

      await chrome.storage.local.remove(["bindUrl", "xCommonParams"]);
      const nickname = result.data?.nickname || result.nickname || "";
      const successMsg = nickname ? `绑定成功：${nickname}\n现在可以关闭或卸载本扩展。` : "绑定成功。\n现在可以关闭或卸载本扩展。";
      setStatus(successMsg, "success");
    } catch (error) {
      setStatus(error.message, "error");
    } finally {
      submitBtn.disabled = false;
    }
  });
}
