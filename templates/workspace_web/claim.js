"use strict";
document.getElementById("claim").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector("button");
  button.disabled = true;
  try {
    const response = await fetch("/workspace/api/claim", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Accept": "application/json" },
      body: new URLSearchParams(new FormData(form)),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "工作台会话领取失败，请回 QQ 重新获取。");
    window.location.replace(result.redirect || "/workspace");
  } catch (error) {
    document.getElementById("claim-status").textContent = error.message;
    button.disabled = false;
  }
});
