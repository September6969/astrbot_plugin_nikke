// SPDX-License-Identifier: GPL-3.0-or-later
const bindInput = document.getElementById("bindUrl");
const statusBox = document.getElementById("status");
function setStatus(message, state) {
  statusBox.textContent = message;
  statusBox.dataset.state = state;
}

chrome.storage.local.get("bindUrl", ({ bindUrl }) => {
  if (bindUrl) bindInput.value = bindUrl;
});

function parseBindUrl() {
  const url = new URL(bindInput.value.trim());
  const allowedOrigins = chrome.runtime.getManifest().host_permissions
    .filter(pattern => !pattern.includes("*.")).map(pattern => new URL(pattern).origin);
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
  // 官网请求头中的字段均为公开请求上下文，不包含密码或验证码。
  return JSON.stringify({
    openid,
    intl_game_id: gameId,
    language: "zh-TW",
    env: "prod",
    source: "outer",
    data_statistics_scene: "outer",
  });
}

document.getElementById("openLogin").addEventListener("click", async () => {
  try {
    parseBindUrl();
    await chrome.storage.local.set({ bindUrl: bindInput.value.trim() });
    await chrome.tabs.create({ url: "https://www.blablalink.com/login", active: true });
    setStatus("请在新标签页完成官网登录和验证码。", "pending");
  } catch (error) {
    setStatus(error.message, "error");
  }
});

document.getElementById("submit").addEventListener("click", async () => {
  const submitButton = document.getElementById("submit");
  submitButton.disabled = true;
  setStatus("正在读取并验证登录状态…", "pending");
  try {
    const { url, token } = parseBindUrl();
    // 与浏览器访问官网时的 Cookie 选择规则保持一致，避免同名跨子域 Cookie 串入。
    const cookies = await chrome.cookies.getAll({ url: "https://www.blablalink.com/" });
    const required = ["game_token", "game_uid", "game_openid"];
    const names = new Set(cookies.map(cookie => cookie.name));
    const missing = required.filter(name => !names.has(name));
    if (missing.length) throw new Error(`尚未完成登录，缺少：${missing.join(", ")}`);
    const stored = await chrome.storage.local.get("xCommonParams");
    // 切换账号后不复用旧账号的请求上下文；损坏缓存同样使用当前Cookie重建。
    let cachedContext = "";
    try {
      const cached = JSON.parse(stored.xCommonParams || "null");
      const openid = cookies.find(cookie => cookie.name === "game_openid")?.value;
      if (cached && String(cached.openid) === openid) cachedContext = stored.xCommonParams;
    } catch {
      // 无效缓存不阻断绑定。
    }
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
    if (!response.ok || !result.ok) throw new Error(result.error || `提交失败 HTTP ${response.status}`);
    await chrome.storage.local.remove(["bindUrl", "xCommonParams"]);
    // 成功界面不回显账号标识，便于用户安全截图。
    setStatus("绑定成功。\n现在可以关闭或卸载本扩展。", "success");
  } catch (error) {
    setStatus(error.message, "error");
  } finally {
    submitButton.disabled = false;
  }
});
