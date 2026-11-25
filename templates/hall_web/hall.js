"use strict";

(() => {
  const state = {
    catalog: [],
    groupContext: { active: false, label: "", csrf: "" },
    lastTarot: null,
  };

  function el(id) {
    return document.getElementById(id);
  }

  function showToast(msg) {
    const toast = el("toast");
    if (!toast) return;
    toast.textContent = msg;
    toast.hidden = false;
    setTimeout(() => { toast.hidden = true; }, 2200);
  }

  async function apiFetch(url, options = {}) {
    const headers = Object.assign({ "Accept": "application/json" }, options.headers || {});
    if (options.method && options.method !== "GET" && state.groupContext.csrf) {
      headers["X-Hall-CSRF"] = state.groupContext.csrf;
    }
    const resp = await fetch(url, Object.assign({ credentials: "same-origin" }, options, { headers }));
    const data = await resp.json().catch(() => ({ ok: false, error: "响应解析失败" }));
    if (!resp.ok) {
      const err = new Error(data.message || data.error || `请求失败 (${resp.status})`);
      err.payload = data;
      throw err;
    }
    return data;
  }

  function switchTab(tabId) {
    document.querySelectorAll(".tab").forEach((btn) => {
      const active = btn.dataset.tab === tabId;
      btn.classList.toggle("active", active);
      btn.setAttribute("aria-selected", active ? "true" : "false");
    });
    document.querySelectorAll(".tab-panel").forEach((panel) => {
      panel.classList.toggle("active", panel.id === `tab-${tabId}`);
    });
  }

  function newIdempotencyKey(prefix) {
    const rand = Math.random().toString(36).slice(2, 10);
    return `${prefix}_${Date.now().toString(36)}_${rand}`;
  }

  function renderCatalog() {
    const container = el("catalog-list");
    const q = (el("catalog-search")?.value || "").trim().toLowerCase();
    const modeFilter = el("catalog-entry-filter")?.value || "all";
    const filtered = state.catalog.filter((item) => {
      if (modeFilter !== "all" && item.entry_mode !== modeFilter) return false;
      if (!q) return true;
      return (
        item.name.toLowerCase().includes(q) ||
        item.summary.toLowerCase().includes(q) ||
        item.example_command.toLowerCase().includes(q)
      );
    });
    container.replaceChildren();
    if (!filtered.length) {
      container.textContent = "没有匹配的功能条目。";
      return;
    }
    for (const item of filtered) {
      const card = document.createElement("article");
      card.className = "feature-card";

      const head = document.createElement("header");
      const title = document.createElement("strong");
      title.textContent = `${item.name} (${item.category})`;
      const tag = document.createElement("span");
      tag.className = "tag";
      tag.textContent = item.entry_mode === "hall" ? "大厅可用" : "大厅 / QQ";
      head.append(title, tag);

      const desc = document.createElement("p");
      desc.className = "muted";
      desc.textContent = item.summary;

      const cmdRow = document.createElement("div");
      cmdRow.className = "cmd-row";
      const code = document.createElement("code");
      code.textContent = item.example_command;
      const copyBtn = document.createElement("button");
      copyBtn.className = "btn";
      copyBtn.type = "button";
      copyBtn.textContent = "复制口令";
      copyBtn.addEventListener("click", async () => {
        try {
          await navigator.clipboard.writeText(item.example_command);
          showToast(`已复制：${item.example_command}`);
        } catch {
          showToast(item.example_command);
        }
      });
      cmdRow.append(code, copyBtn);

      card.append(head, desc, cmdRow);
      if (item.web_tab && item.web_tab !== "overview") {
        const goBtn = document.createElement("button");
        goBtn.className = "btn";
        goBtn.type = "button";
        goBtn.textContent = "在当前大厅打开";
        goBtn.addEventListener("click", () => switchTab(item.web_tab));
        card.append(goBtn);
      }
      container.append(card);
    }
  }

  async function loadBootstrap() {
    const data = await apiFetch("/hall/api/bootstrap");
    state.catalog = data.catalog?.features || [];
    state.groupContext = data.group_context || { active: false, label: "", csrf: "" };
    const banner = el("group-ctx-banner");
    if (state.groupContext.active) {
      banner.classList.add("active");
      banner.textContent = `已连接群聊反馈上下文：${state.groupContext.label}（可推送日程 / 随机塔罗）`;
      el("btn-push-calendar").hidden = false;
      el("btn-push-tarot").hidden = false;
    }
    if (data.flags?.counsel_available) {
      const counselCard = el("card-counsel");
      if (counselCard) counselCard.hidden = false;
    }
    renderCatalog();
  }

  async function loadCalendar() {
    const horizon = el("calendar-horizon").value;
    const box = el("calendar-items");
    box.textContent = "加载中…";
    try {
      const data = await apiFetch(`/hall/api/calendar?horizon=${encodeURIComponent(horizon)}`);
      if (!data.available) {
        box.textContent = data.fallback_text || "日程快照暂未就绪。";
        return;
      }
      box.replaceChildren();
      const items = data.items || [];
      if (!items.length) {
        const pre = document.createElement("pre");
        pre.className = "pre-box";
        pre.textContent = data.fallback_text;
        box.append(pre);
        return;
      }
      for (const row of items) {
        const div = document.createElement("div");
        div.className = "list-row";
        const left = document.createElement("div");
        const b = document.createElement("strong");
        b.textContent = `[${row.bucket}] ${row.title}`;
        left.append(b);
        const right = document.createElement("span");
        right.className = "muted";
        right.textContent = `${row.time_range} · ${row.remaining}`;
        div.append(left, right);
        box.append(div);
      }
    } catch (err) {
      box.textContent = err.message;
    }
  }

  async function drawTarot(mode) {
    el("tarot-output").textContent = "抽牌中…";
    try {
      const data = await apiFetch("/hall/api/tarot", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode }),
      });
      state.lastTarot = data;
      const grid = el("tarot-cards");
      grid.replaceChildren();
      for (const card of data.cards || []) {
        const wrap = document.createElement("div");
        wrap.className = `tarot-card ${card.orientation === "reversed" ? "reversed" : ""}`;
        if (card.image_url) {
          const img = document.createElement("img");
          img.src = card.image_url;
          img.alt = card.name_zh;
          wrap.append(img);
        }
        const title = document.createElement("div");
        const strong = document.createElement("strong");
        strong.textContent = card.name_zh;
        title.append(strong, document.createTextNode(` · ${card.orientation_label}`));
        wrap.append(title);
        grid.append(wrap);
      }
      el("tarot-output").textContent = data.text;
      if (state.groupContext.active) {
        el("btn-push-tarot").disabled = false;
      }
    } catch (err) {
      el("tarot-output").textContent = err.message;
    }
  }

  async function pushCalendarToGroup() {
    const status = el("calendar-feedback-status");
    const btn = el("btn-push-calendar");
    btn.disabled = true;
    status.textContent = "正在发送日程到当前群聊…";
    try {
      const data = await apiFetch("/hall/api/feedback/calendar", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          horizon: Number(el("calendar-horizon").value || 14),
          idempotency_key: newIdempotencyKey("cal"),
        }),
      });
      status.textContent = `发送成功：${data.target}`;
      showToast("日程已推送至 QQ 群");
    } catch (err) {
      status.textContent = err.message;
    } finally {
      btn.disabled = false;
    }
  }

  async function pushTarotToGroup() {
    if (!state.lastTarot) return;
    const status = el("tarot-feedback-status");
    const btn = el("btn-push-tarot");
    btn.disabled = true;
    status.textContent = "正在将本次占卜结果发送到当前群聊…";
    try {
      const data = await apiFetch("/hall/api/feedback/tarot", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          mode: state.lastTarot.mode,
          cards: state.lastTarot.cards,
          idempotency_key: newIdempotencyKey("tarot"),
        }),
      });
      status.textContent = `发送成功：${data.target}`;
      showToast("塔罗占卜结果已推送至 QQ 群");
    } catch (err) {
      status.textContent = err.message;
    } finally {
      btn.disabled = false;
    }
  }

  async function loadGuides(category = "") {
    const data = await apiFetch(`/hall/api/guides?category=${encodeURIComponent(category)}`);
    const pills = el("guide-categories");
    if (!pills.children.length) {
      for (const cat of data.categories || []) {
        const b = document.createElement("button");
        b.className = "btn";
        b.type = "button";
        b.textContent = cat.label;
        b.addEventListener("click", () => loadGuides(cat.id));
        pills.append(b);
      }
    }
    const out = el("guide-output");
    out.replaceChildren();
    if (!category) return;
    if (!(data.entries || []).length) {
      out.textContent = "该分类暂无已登记攻略条目。";
      return;
    }
    for (const entry of data.entries) {
      const div = document.createElement("div");
      div.className = "list-row";
      div.textContent = entry.caption + (entry.links.length ? ` | ${entry.links.join(" ")}` : "");
      out.append(div);
    }
  }

  function bindEvents() {
    document.querySelectorAll(".tab").forEach((btn) => {
      btn.addEventListener("click", () => {
        switchTab(btn.dataset.tab);
        if (btn.dataset.tab === "calendar" && el("calendar-items").textContent.includes("点击刷新")) {
          loadCalendar();
        }
        if (btn.dataset.tab === "guides" && !el("guide-categories").children.length) {
          loadGuides("");
        }
      });
    });
    el("catalog-search")?.addEventListener("input", renderCatalog);
    el("catalog-entry-filter")?.addEventListener("change", renderCatalog);
    el("btn-load-calendar")?.addEventListener("click", loadCalendar);
    el("btn-push-calendar")?.addEventListener("click", pushCalendarToGroup);
    el("btn-load-gacha")?.addEventListener("click", async () => {
      const g = el("gacha-group").value;
      const d = await apiFetch(`/hall/api/gacha?group=${encodeURIComponent(g)}`);
      el("gacha-output").textContent = d.text;
    });
    el("btn-tarot-single")?.addEventListener("click", () => drawTarot("single"));
    el("btn-tarot-three")?.addEventListener("click", () => drawTarot("three"));
    el("btn-push-tarot")?.addEventListener("click", pushTarotToGroup);
    el("btn-tower-query")?.addEventListener("click", async () => {
      const t = el("tower-name").value;
      const f = el("tower-floor").value;
      const d = await apiFetch(`/hall/api/tower?tower=${encodeURIComponent(t)}&floor=${encodeURIComponent(f)}`);
      el("tower-output").textContent = d.text;
    });
    el("btn-load-ann")?.addEventListener("click", async () => {
      const l = el("ann-locale").value;
      const q = el("ann-query").value;
      const d = await apiFetch(`/hall/api/announcements?locale=${encodeURIComponent(l)}&q=${encodeURIComponent(q)}`);
      el("ann-output").textContent = d.text;
    });
    el("btn-load-ranking")?.addEventListener("click", async () => {
      const d = await apiFetch("/hall/api/ranking");
      el("ranking-output").textContent = d.text;
    });
    el("btn-char-query")?.addEventListener("click", async () => {
      const q = el("char-query").value;
      const d = await apiFetch(`/hall/api/character?q=${encodeURIComponent(q)}`);
      const out = el("char-output");
      out.replaceChildren();
      if (!(d.matches || []).length) {
        out.textContent = "未找到匹配角色。";
        return;
      }
      for (const m of d.matches) {
        const div = document.createElement("div");
        div.className = "list-row";
        div.textContent = `${m.name} | ${m.rarity} | B${m.burst} | ${m.element} | ${m.company} / ${m.squad}`;
        out.append(div);
      }
    });
    el("btn-counsel")?.addEventListener("click", async () => {
      const d = await apiFetch("/hall/api/tools/counsel", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ character: el("counsel-char").value, keyword: el("counsel-kw").value }),
      });
      el("counsel-output").textContent = d.text;
    });
    el("btn-ol-rec")?.addEventListener("click", async () => {
      try {
        const d = await apiFetch("/hall/api/tools/overload-recommend", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ character: el("ol-char-q").value }),
        });
        el("ol-rec-output").textContent = d.text;
      } catch (err) {
        el("ol-rec-output").textContent = err.message;
      }
    });
    function collectHallCases() {
      const cases = { core_dust: {}, credits: {}, battle_data: {} };
      document.querySelectorAll(".hall-case-inp").forEach((inp) => {
        const res = inp.dataset.res;
        const hr = inp.dataset.hr;
        if (cases[res] && hr) {
          cases[res][hr] = Number(inp.value || 0);
        }
      });
      return cases;
    }

    function renderHallSyncVisual(plan) {
      const visual = el("sync-visual");
      const kpi = el("sync-kpi");
      const cards = el("sync-cards");
      if (!visual || !kpi || !cards || !plan) return;
      visual.hidden = false;
      const kpiItems = [
        {
          label: "预计达成日期",
          val: plan.eta || "无法估算",
          sub: plan.overall_days === null ? "存在零产量瓶颈" : `约需 ${plan.overall_days} 天`,
        },
        {
          label: "主要资源瓶颈",
          val: (plan.bottlenecks && plan.bottlenecks.length) ? plan.bottlenecks.join(" / ") : "无",
          sub: plan.outpost_level ? `前哨 Lv.${plan.outpost_level}` : "",
        },
        {
          label: "当前库存立即升级",
          val: plan.reachable_level ? `Lv.${plan.reachable_level} (+${plan.gainable_levels})` : "-",
          sub: "含直存与箱子",
        },
      ];
      kpi.replaceChildren(...kpiItems.map((item) => {
        const box = document.createElement("div");
        box.className = "kpi-card";
        const lb = document.createElement("div");
        lb.className = "kpi-label";
        lb.textContent = item.label;
        const val = document.createElement("div");
        val.className = "kpi-val";
        val.textContent = item.val;
        const sub = document.createElement("div");
        sub.className = "kpi-sub";
        sub.textContent = item.sub;
        box.append(lb, val, sub);
        return box;
      }));
      cards.replaceChildren(...(plan.resources || []).map((r) => {
        const card = document.createElement("div");
        card.className = "res-card";
        const head = document.createElement("div");
        head.className = "res-head";
        const strong = document.createElement("strong");
        strong.textContent = r.label;
        const tag = document.createElement("span");
        tag.className = "tag";
        tag.textContent = r.days === null ? "无法估算" : `${r.days} 天`;
        head.append(strong, tag);

        const pct = r.required > 0 ? Math.min(100, Math.round((r.stock / r.required) * 100)) : 100;
        const bar = document.createElement("progress");
        bar.className = "res-progress";
        bar.max = 100;
        bar.value = pct;

        const meta = document.createElement("div");
        meta.className = "res-meta";
        for (const text of [
          `需要 ${Number(r.required).toLocaleString()} ｜ 库存 ${Number(r.stock).toLocaleString()}`,
          `缺口 ${Number(r.missing).toLocaleString()} ｜ 日产 ${Math.round(Number(r.production || 0)).toLocaleString()}`,
        ]) {
          const line = document.createElement("div");
          line.textContent = text;
          meta.append(line);
        }
        card.append(head, bar, meta);
        return card;
      }));
    }

    el("btn-sync-calc")?.addEventListener("click", async () => {
      try {
        const d = await apiFetch("/hall/api/tools/sync", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            current: el("sync-cur").value,
            target: el("sync-tgt").value,
            outpost_level: el("sync-outpost").value,
            wipeout_count: el("sync-wipeout").value,
            inventory: {
              core_dust: el("sync-inv-dust").value,
              credits: el("sync-inv-cred").value,
              battle_data: el("sync-inv-data").value,
            },
            cases: collectHallCases(),
            extra_daily: {
              core_dust: el("sync-extra-dust").value,
              credits: el("sync-extra-cred").value,
              battle_data: el("sync-extra-data").value,
            },
          }),
        });
        renderHallSyncVisual(d.plan);
        el("sync-output").textContent = d.text;
      } catch (err) {
        el("sync-output").textContent = err.message;
      }
    });
    el("btn-wishlist")?.addEventListener("click", async () => {
      try {
        const d = await apiFetch("/hall/api/tools/wishlist", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            strategy: el("wl-strategy").value,
            owned: el("wl-owned").value,
          }),
        });
        el("wl-output").textContent = d.text;
      } catch (err) {
        el("wl-output").textContent = err.message;
      }
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    bindEvents();
    loadBootstrap().catch((err) => {
      el("catalog-list").textContent = `加载失败：${err.message}`;
    });
  });
})();
