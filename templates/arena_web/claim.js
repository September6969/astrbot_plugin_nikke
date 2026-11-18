"use strict";
// 使用同源 Fetch 兑换，避免导航表单在 no-referrer 策略下发送空 Origin。
document.getElementById("claim").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector("button");
  button.disabled = true;
  try {
    const response = await fetch("/arena/api/claim", {
      method: "POST", credentials: "same-origin", headers: {"Accept": "application/json"},
      body: new URLSearchParams(new FormData(form)),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "兑换失败，请回 QQ 获取新链接。");
    window.location.replace("/arena/edit");
  } catch (error) {
    document.getElementById("claim-status").textContent = error.message;
    button.disabled = false;
  }
});
