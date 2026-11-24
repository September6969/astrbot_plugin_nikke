"use strict";
// 同源 Fetch 兑换一次性入口，避免导航表单在 no-referrer 策略下发送空 Origin。
document.getElementById("claim").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector("button");
  const status = document.getElementById("claim-status");
  button.disabled = true;
  if (status) status.textContent = "正在验证入口并建立会话…";
  try {
    const response = await fetch("/shiftypad/api/claim", {
      method: "POST",
      credentials: "same-origin",
      headers: {"Accept": "application/json"},
      body: new URLSearchParams(new FormData(form)),
    });
    let result = {};
    try {
      result = await response.json();
    } catch (_err) {
      result = {};
    }
    if (!response.ok || result.ok === false) {
      throw new Error(result.message || result.error || "兑换失败，请回私聊重新获取入口。");
    }
    window.location.replace(result.redirect || "/shiftypad/edit");
  } catch (error) {
    if (status) {
      status.className = "err";
      status.textContent = error && error.message ? error.message : "兑换失败，请回私聊重新获取入口。";
    }
    button.disabled = false;
  }
});
