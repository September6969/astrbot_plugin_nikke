"use strict";
document.getElementById("claim").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector("button");
  button.disabled = true;
  try {
    const response = await fetch("/hall/api/claim", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Accept": "application/json" },
      body: new URLSearchParams(new FormData(form)),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "进入大厅失败，请回群重新获取。");
    window.location.replace(result.redirect || "/hall");
  } catch (error) {
    document.getElementById("claim-status").textContent = error.message;
    button.disabled = false;
  }
});
