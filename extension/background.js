// SPDX-License-Identifier: GPL-3.0-or-later
// 默认只观察账号上下文；用户额外选择后才保留官方 Login 的白名单字段。
chrome.webRequest.onBeforeSendHeaders.addListener(
  async (details) => {
    const headers = details.requestHeaders || [];
    const common = headers.find((item) => item.name.toLowerCase() === "x-common-params");
    if (!common?.value) return;
    try {
      const parsed = JSON.parse(common.value);
      if (parsed && typeof parsed === "object" && parsed.openid) {
        await chrome.storage.local.set({ xCommonParams: common.value });
      }
    } catch {
      // 非JSON或不完整请求头不保存，等待官网后续完整请求。
    }
  },
  // 新版官网会先从多个 BlaBlaLink 子域发起请求，不能只监听 api 子域。
  { urls: ["https://*.blablalink.com/*"] },
  ["requestHeaders", "extraHeaders"]
);

chrome.webRequest.onBeforeRequest.addListener(
  async (details) => {
    const preference = await chrome.storage.local.get("keepRenewalMaterial");
    if (preference.keepRenewalMaterial !== true || details.method !== "POST") return;
    try {
      const raw = details.requestBody?.raw;
      if (!raw?.length || raw.length !== 1 || !raw[0].bytes) return;
      const bytes = raw[0].bytes;
      if (bytes.byteLength > 16384) return;
      const payload = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes));
      const keys = ["game_openid", "game_channelid", "game_token", "game_id", "game_expire_time",
        "game_uid", "game_user_name", "game_user_region", "game_adult_status"];
      const saved = Object.fromEntries(keys.filter(key => Object.hasOwn(payload, key)).map(key => [key, payload[key]]));
      if (!saved.game_token || !saved.game_openid || !Number.isInteger(saved.game_expire_time)) return;
      await chrome.storage.local.set({ renewalLoginPayload: saved });
    } catch {
      // 不完整或非预期请求体不保存，绝不记录原始内容。
    }
  },
  { urls: ["https://api.blablalink.com/api/user/Login"] },
  ["requestBody"]
);
