/* 主逻辑：状态管理、实时渲染、因子详情、回测与设置 */
const S = {
  cfg: null,
  symbol: null,
  snap: null,
  factors: [],
  history: null,
  strategies: [],
  strategy: "multi_factor",
  lib: [],
  ws: null,
  wsOk: false,
  lastMsgAt: 0,
  currentFactor: null,
  quotes: {},
  view: "dashboard",
};

const UP_COLORS = ["#16c784", "#4ade80", "#94a3b8", "#fb7185", "#f6465d"];
const HEAT_COLORS = ["#475569", "#64748b", "#94a3b8", "#fbbf24", "#ef4444"];

/* ---------------- 工具 ---------------- */
const $ = (sel, root) => (root || document).querySelector(sel);
const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));

function fmt(n, digits = 2) {
  if (n === null || n === undefined || Number.isNaN(Number(n))) return "--";
  return Number(n).toLocaleString("zh-CN", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}
function signed(n, digits = 2, suffix = "") {
  if (n === null || n === undefined) return "--";
  const v = Number(n);
  return (v > 0 ? "+" : "") + v.toFixed(digits) + suffix;
}
function rgba(hex, a) {
  const h = hex.replace("#", "");
  const v = parseInt(h.length === 3 ? h.split("").map((c) => c + c).join("") : h, 16);
  return `rgba(${(v >> 16) & 255},${(v >> 8) & 255},${v & 255},${a})`;
}
function levelColor(f) {
  const palette = f.weight > 0 ? UP_COLORS : HEAT_COLORS;
  return palette[Math.max(0, Math.min(4, f.level || 0))];
}
function stateClass(pct) {
  return pct > 0 ? "up" : pct < 0 ? "down" : "";
}

function toast(msg, type = "info") {
  let el = $(".toast");
  if (!el) {
    el = document.createElement("div");
    el.className = "toast";
    document.body.appendChild(el);
  }
  el.textContent = msg;
  el.dataset.type = type;
  el.classList.add("show");
  clearTimeout(el._t);
  el._t = setTimeout(() => el.classList.remove("show"), 3200);
}

function timeNow() {
  return new Date().toLocaleTimeString("zh-CN", { hour12: false });
}

/* ---------------- 初始化 ---------------- */
async function init() {
  bindEvents();
  startClock();
  try {
    const [cfg, syms, lib, strat, status] = await Promise.all([
      API.get("/api/config"),
      API.get("/api/symbols"),
      API.get("/api/factor-library"),
      API.get("/api/strategies"),
      API.get("/api/status"),
    ]);
    S.cfg = cfg;
    S.lib = lib.factors;
    S.strategies = strat.items;
    S.symbol = cfg.active_symbol || cfg.symbols[0];
    S.symbols = syms.items;
    renderWatchlist();
    renderLibrary();
    renderStrategies();
    renderFactorIds();
    applyStatus(status);
    updateSourceBadge(status.data);
  } catch (e) {
    toast("初始化失败：" + e.message, "error");
  }
  connectWS();
  setInterval(pollFallback, 5000);
}

function startClock() {
  const el = $("#clock");
  const tick = () => (el.textContent = timeNow());
  tick();
  setInterval(tick, 1000);
}

/* ---------------- WebSocket ---------------- */
function setWsStatus(ok) {
  S.wsOk = ok;
  const dot = $("#ws-dot");
  const badge = $("#live-badge");
  dot.className = "dot " + (ok ? "ok" : "off");
  $("#ws-state").textContent = ok ? "实时推送中" : "连接断开，重试中…";
  $("#live-text").textContent = ok ? "实时" : "离线";
  const pulse = $(".pulse", badge);
  if (pulse) pulse.classList.toggle("stop", !ok);
}

function connectWS() {
  try {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${location.host}/ws`);
    S.ws = ws;
    ws.onopen = () => {
      setWsStatus(true);
      if (S.symbol) ws.send(JSON.stringify({ action: "switch", symbol: S.symbol }));
    };
    ws.onmessage = (ev) => {
      S.lastMsgAt = Date.now();
      let msg;
      try { msg = JSON.parse(ev.data); } catch (e) { return; }
      if (msg.type === "snapshot") renderSnapshot(msg);
      else if (msg.type === "tick") updateTick(msg);
    };
    ws.onclose = () => {
      setWsStatus(false);
      setTimeout(connectWS, 2000);
    };
    ws.onerror = () => ws.close();
  } catch (e) {
    setTimeout(connectWS, 3000);
  }
}

async function pollFallback() {
  if (S.wsOk || !S.symbol) return;
  if (Date.now() - S.lastMsgAt < 4000) return;
  try {
    const snap = await API.get(`/api/snapshot?symbol=${S.symbol}&refresh=0`);
    renderSnapshot(snap);
  } catch (e) {}
}

/* ---------------- 自选列表 ---------------- */
function renderWatchlist(filter = "") {
  const box = $("#watchlist");
  const q = filter.trim().toLowerCase();
  const codes = (S.cfg && S.cfg.symbols) || [];
  const all = S.symbols || [];
  let items = all.filter((i) => codes.includes(i.code));
  if (q) {
    items = all.filter((i) => i.code.includes(q) || i.name.toLowerCase().includes(q)).slice(0, 30);
  }
  if (!items.length) {
    box.innerHTML = `<div class="hint" style="padding:6px">未找到标的，输入6位代码后点 + 添加</div>`;
    return;
  }
  box.innerHTML = items
    .map((i) => {
      const chg = S.quotes[i.code];
      const cls = chg === undefined ? "" : stateClass(chg);
      const chgTxt = chg === undefined ? "" : signed(chg, 2, "%");
      return `<div class="w-item ${i.code === S.symbol ? "active" : ""}" data-code="${i.code}">
        <div><span class="w-name">${i.name}</span><span class="w-code">${i.code}</span></div>
        <div class="w-chg ${cls}">${chgTxt}</div>
      </div>`;
    })
    .join("");
}

async function switchSymbol(code) {
  if (!code || code === S.symbol) return;
  S.symbol = code;
  S.quotes[code] = undefined;
  renderWatchlist($("#symbol-search").value);
  if (S.ws && S.ws.readyState === 1) {
    S.ws.send(JSON.stringify({ action: "switch", symbol: code }));
  } else {
    try {
      renderSnapshot(await API.get(`/api/snapshot?symbol=${code}`));
    } catch (e) {
      toast(e.message, "error");
    }
  }
}

/* ---------------- 快照渲染 ---------------- */
function updateSourceBadge(data) {
  if (!data) return;
  $("#side-source").textContent = data.source_label || "--";
  $("#q-source").textContent = data.source_label || "--";
  const sim = $("#q-sim");
  sim.classList.toggle("hidden", !data.simulated);
}

function renderSnapshot(snap) {
  S.snap = snap;
  S.symbol = snap.symbol;
  S.factors = snap.factors.slice();
  S.history = snap.factor_history;
  S.quotes[snap.symbol] = snap.quote.change_pct;

  $("#q-name").textContent = snap.name;
  $("#q-code").textContent = snap.symbol;
  $("#q-date").textContent = snap.quote.date;
  updateSourceBadge(snap.source);
  updateQuote(snap.quote, snap);
  renderFactorCards();
  Charts.initDashboard(snap, snap.factor_history);
  buildFactorToggles(snap.factor_history);
  updateScorePanel(snap.composite);
  updateLibraryLive();
  renderWatchlist($("#symbol-search").value);
  $("#side-updated").textContent = snap.time.slice(11, 19);
  if (S.currentFactor) refreshDrawerData();
}

function updateQuote(q, snap) {
  const priceEl = $("#q-price");
  const prev = S.lastPrice;
  S.lastPrice = q.price;
  priceEl.textContent = fmt(q.price, 2);
  priceEl.className = "price " + stateClass(q.change_pct);
  if (prev !== undefined && q.price !== prev) {
    priceEl.style.transition = "none";
    priceEl.style.opacity = "0.45";
    requestAnimationFrame(() => {
      priceEl.style.transition = "opacity .35s";
      priceEl.style.opacity = "1";
    });
  }
  $("#q-chg").textContent = `${signed(q.change, 2)}  ${signed(q.change_pct, 2, "%")}`;
  $("#q-chg").className = "chg " + stateClass(q.change_pct);
  $("#q-open").textContent = fmt(q.open);
  $("#q-high").textContent = fmt(q.high);
  $("#q-low").textContent = fmt(q.low);
  $("#q-turnover").textContent = fmt(q.turnover, 2) + "%";
  if (snap) {
    $("#q-name").textContent = snap.name;
    $("#q-code").textContent = snap.symbol;
    $("#q-date").textContent = q.date;
  }
}

function updateScorePanel(comp) {
  $("#qh-score").textContent = (comp.score > 0 ? "+" : "") + comp.score;
  $("#qh-score").style.color =
    comp.score >= 20 ? "#f6465d" : comp.score <= -20 ? "#16c784" : "#93a2bb";
  $("#qh-label").textContent = comp.label;
  $("#qh-counts").textContent = `多 ${comp.bull} · 空 ${comp.bear}`;
  $("#score-desc").textContent = comp.desc;
  ["bull", "neutral", "bear"].forEach((k) => {
    const el = $("#c-" + k);
    if (el) el.textContent = comp[k];
  });
  Charts.setGauge(comp.score);
}

/* ---------------- 因子卡 ---------------- */
function sparkPath(vals) {
  const w = 100, h = 34, n = vals.length || 1;
  const pts = [];
  vals.forEach((v, i) => {
    if (v === null || v === undefined) return;
    const x = n === 1 ? w / 2 : (i / (n - 1)) * w;
    const y = h / 2 - (Math.max(-100, Math.min(100, v)) / 100) * (h / 2 - 3);
    pts.push(`${x.toFixed(1)},${y.toFixed(1)}`);
  });
  return pts.length ? "M" + pts.join(" L") : "";
}

function renderFactorCards() {
  const grid = $("#factor-grid");
  grid.innerHTML = S.factors
    .map(
      (f) => `<div class="fcard" data-id="${f.id}" style="--c:#94a3b8">
        <div class="fcard-top">
          <div class="fcard-name">${f.name}<span class="fcat">${f.category}</span></div>
          <div class="fw">${f.weight > 0 ? "权重 " + f.weight : "辅助"}</div>
        </div>
        <div class="fcard-mid">
          <div class="fval">--</div>
          <div class="fstate">--</div>
        </div>
        <div class="bar"><div class="bar-fill"></div></div>
        <div class="fcard-spark"><svg viewBox="0 0 100 34" preserveAspectRatio="none"><path d="" fill="none" stroke="#94a3b8" stroke-width="1.2"/></svg></div>
        <div class="fcard-foot"><span class="sc">评分 --</span><span class="pct">分位 --</span></div>
      </div>`
    )
    .join("");
  S.factors.forEach(updateFactorCard);
}

function updateFactorCard(f) {
  const card = $(`.fcard[data-id="${f.id}"]`);
  if (!card) return;
  const color = levelColor(f);
  card.style.setProperty("--c", color);
  $(".fval", card).textContent = f.display;
  const state = $(".fstate", card);
  state.textContent = f.state;
  state.style.color = color;
  state.style.background = rgba(color, 0.01);
  state.style.border = `1px solid ${rgba(color, 0.35)}`;
  state.style.background = rgba(color, 0.12);
  const scoreTxt = `评分 ${f.score > 0 ? "+" : ""}${f.score}`;
  $(".sc", card).textContent = scoreTxt;
  const pct = $(".pct", card);
  if (f.pct_rank !== undefined) {
    pct.textContent = `分位 ${f.pct_rank}% · ${f.duration ?? 0}日`;
  }
  const path = $(".fcard-spark path", card);
  if (path && f.spark) {
    path.setAttribute("d", sparkPath(f.spark));
    path.setAttribute("stroke", color);
  }
  const fill = $(".bar-fill", card);
  if (fill) {
    const w = Math.min(50, Math.abs(f.score) / 2);
    fill.style.width = w + "%";
    fill.style.left = (f.score >= 0 ? 50 : 50 - w) + "%";
    fill.style.background = color;
  }
}

/* ---------------- 因子走势切换 ---------------- */
function buildFactorToggles(history) {
  const box = $("#factor-toggles");
  box.innerHTML = S.factors
    .map((f) => {
      const on = Charts.trendIds.includes(f.id);
      const idx = Charts.trendIds.indexOf(f.id);
      const color = idx >= 0 ? C.palette[idx % C.palette.length] : "#64748b";
      return `<span class="ft ${on ? "on" : ""}" data-id="${f.id}"><i style="background:${color}"></i>${f.short}</span>`;
    })
    .join("");
  box.onclick = (e) => {
    const t = e.target.closest(".ft");
    if (!t) return;
    const id = t.dataset.id;
    const idx = Charts.trendIds.indexOf(id);
    if (idx >= 0) {
      if (Charts.trendIds.length <= 1) return;
      Charts.trendIds.splice(idx, 1);
    } else {
      if (Charts.trendIds.length >= 8) Charts.trendIds.shift();
      Charts.trendIds.push(id);
    }
    buildFactorToggles(history);
    Charts.setTrend(history);
  };
}

/* ---------------- 实时Tick ---------------- */
function updateTick(t) {
  if (!S.snap || t.symbol !== S.symbol) return;
  S.quotes[S.symbol] = t.quote.change_pct;
  const map = new Map(S.factors.map((f) => [f.id, f]));
  const changed = [];
  t.factors.forEach((tf) => {
    const f = map.get(tf.id);
    if (!f) return;
    Object.assign(f, tf);
    updateFactorCard(f);
    changed.push(f);
  });
  updateQuote(t.quote, null);
  updateScorePanel({ ...S.snap.composite, ...t.composite });
  Charts.setRadar(S.factors);
  Charts.updateLastBar(t.bar, t.bar_volume, t.quote.date);
  const trendVals = {};
  S.factors.forEach((f) => (trendVals[f.id] = f.score));
  Charts.updateTrendLast(trendVals);
  $("#side-updated").textContent = t.time.slice(11, 19);
  const active = $(`.w-item[data-code="${S.symbol}"] .w-chg`);
  if (active) {
    active.textContent = signed(t.quote.change_pct, 2, "%");
    active.className = "w-chg " + stateClass(t.quote.change_pct);
  }
  updateLibraryLive();
  if (S.currentFactor) refreshDrawerData();
}

/* ---------------- 因子抽屉 ---------------- */
function openDrawer(factor) {
  S.currentFactor = factor;
  const d = $("#drawer");
  $("#d-name").textContent = factor.name;
  $("#d-sub").textContent = `${factor.category}类因子 · ${factor.weight > 0 ? "参与综合评分（权重 " + factor.weight + "）" : factor.weight_note}`;
  $("#d-meaning").textContent = factor.meaning;
  $("#d-role").textContent = factor.role;
  $("#d-formula").textContent = factor.formula;
  $("#d-levels").innerHTML = factor.levels
    .map((label, i) => {
      const color = (factor.weight > 0 ? UP_COLORS : HEAT_COLORS)[i];
      const rng = ["≤ -60", "-60 ~ -20", "-20 ~ 20", "20 ~ 60", "≥ 60"][i];
      return `<div class="ladder-row ${i === factor.level ? "current" : ""}" style="--c:${color}">
        <i></i><span>${label}</span><span class="rng">评分 ${rng}</span></div>`;
    })
    .join("");
  refreshDrawerData();
  $("#d-ai-text").textContent = "点击上方按钮，结合当前行情生成该因子的实时解读。";
  $("#d-ai-text").classList.remove("streaming");
  d.classList.add("show");
  $("#drawer-mask").classList.add("show");
}

function refreshDrawerData() {
  const f = S.currentFactor;
  if (!f) return;
  const color = levelColor(f);
  const pill = $("#d-state");
  pill.textContent = f.state;
  pill.style.color = color;
  pill.style.borderColor = rgba(color, 0.4);
  const score = `评分 ${f.score > 0 ? "+" : ""}${f.score}`;
  $("#d-kpis").innerHTML = `
    <div class="kpi"><label>当前读数</label><b>${f.display}</b></div>
    <div class="kpi"><label>${score}</label><b style="color:${color}">${f.weight > 0 ? f.score : "—"}</b></div>
    <div class="kpi"><label>近一年分位</label><b>${f.pct_rank ?? "--"}%</b></div>
    <div class="kpi"><label>连续天数</label><b>${f.duration ?? "--"}</b></div>`;
  const dsub = `近5日评分变化 ${f.delta5 > 0 ? "+" : ""}${f.delta5 ?? 0} · ${f.weight_note || ""}`;
  $("#d-sub").textContent = `${f.category}类因子 · ${dsub}`;
  $$(".ladder-row", $("#d-levels")).forEach((row, i) =>
    row.classList.toggle("current", i === f.level)
  );
}

async function generateExplain() {
  const f = S.currentFactor;
  if (!f || !S.symbol) return;
  const box = $("#d-ai-text");
  const btn = $("#d-ai-btn");
  box.textContent = "";
  box.classList.add("streaming");
  btn.disabled = true;
  let text = "";
  try {
    await API.stream("/api/llm/explain", { symbol: S.symbol, factor_id: f.id }, (ev) => {
      if (ev.delta) {
        text += ev.delta;
        box.textContent = text;
      }
      if (ev.done) {
        box.classList.remove("streaming");
        if (ev.local) box.textContent = text + "\n\n（当前使用本地规则解读；在设置中配置大模型可得到更深入的分析。）";
        if (ev.error) box.textContent = text + "\n\n[提示] " + ev.error;
      }
    });
  } catch (e) {
    box.textContent = "生成失败：" + e.message;
    box.classList.remove("streaming");
  } finally {
    btn.disabled = false;
  }
}

/* ---------------- 因子库 ---------------- */
function renderLibrary() {
  const cats = ["all", ...new Set(S.lib.map((f) => f.category))];
  $("#lib-filter").innerHTML = cats
    .map((c) => `<button class="chip ${c === "all" ? "active" : ""}" data-cat="${c}">${c === "all" ? "全部" : c}</button>`)
    .join("");
  $("#lib-filter").onclick = (e) => {
    const btn = e.target.closest(".chip");
    if (!btn) return;
    $$("#lib-filter .chip").forEach((b) => b.classList.toggle("active", b === btn));
    renderLibraryList(btn.dataset.cat);
  };
  renderLibraryList("all");
}

function renderLibraryList(cat = "all") {
  const list = S.lib.filter((f) => cat === "all" || f.category === cat);
  $("#lib-list").innerHTML = list
    .map((f) => {
      const live = S.factors.find((x) => x.id === f.id);
      const color = live ? levelColor(live) : "#64748b";
      return `<div class="lib-item" data-id="${f.id}" style="--c:${color}">
        <div class="lib-name">
          <div class="n">${f.name}</div>
          <div class="c">${f.category} · ${f.weight > 0 ? "权重 " + f.weight : "辅助观察"}</div>
        </div>
        <div class="lib-desc">${f.meaning}<br/><span style="color:#64748b">${f.role}</span></div>
        <div class="lib-desc"><code class="formula">${f.formula}</code><br/><span style="color:#64748b">${f.levels.join(" / ")}</span></div>
        <div class="lib-state">
          <div class="v" style="color:${color}">${live ? live.display : "--"}</div>
          <div class="s">${live ? live.state : "等待行情"}</div>
        </div>
      </div>`;
    })
    .join("");
}

function updateLibraryLive() {
  $$(".lib-item").forEach((row) => {
    const f = S.factors.find((x) => x.id === row.dataset.id);
    if (!f) return;
    const color = levelColor(f);
    row.style.setProperty("--c", color);
    const v = $(".v", row);
    const s = $(".s", row);
    v.textContent = f.display;
    v.style.color = color;
    s.textContent = f.state;
  });
}

/* ---------------- 策略回测 ---------------- */
function renderStrategies() {
  const sel = $("#bt-strategy");
  sel.innerHTML = S.strategies
    .map((t) => `<option value="${t.id}">${t.name}</option>`)
    .join("");
  const def = S.strategies.find((t) => t.id === S.strategy) || S.strategies[0];
  S.strategy = def.id;
  sel.value = def.id;
  renderStrategyParams(def);
}

function currentStrategy() {
  return S.strategies.find((t) => t.id === S.strategy);
}

function renderStrategyParams(tpl) {
  if (!tpl) return;
  $("#strategy-desc").textContent = tpl.desc;
  const box = $("#bt-params");
  box.innerHTML = tpl.params
    .map((p) => {
      if (p.type === "code") {
        const code = p.default || tpl.default_code || "";
        return `<div class="p-item full"><label class="mini-label">${p.label}</label>
          <textarea class="input code-like" rows="10" data-key="${p.key}" data-type="code">${code.replace(/</g, "&lt;")}</textarea></div>`;
      }
      if (p.type === "bool") {
        return `<div class="p-item full"><label class="check"><input type="checkbox" data-key="${p.key}" data-type="bool" ${p.default ? "checked" : ""}/> ${p.label}</label></div>`;
      }
      return `<div class="p-item"><label class="mini-label">${p.label}</label>
        <input class="input" type="number" data-key="${p.key}" data-type="${p.type}" value="${p.default}"
          step="${p.step || 1}" min="${p.min ?? ""}" max="${p.max ?? ""}"/></div>`;
    })
    .join("");
}

function collectParams() {
  const params = {};
  $$("#bt-params [data-key]").forEach((el) => {
    const key = el.dataset.key;
    const type = el.dataset.type;
    if (type === "bool") params[key] = el.checked;
    else if (type === "int") params[key] = parseInt(el.value || "0", 10);
    else if (type === "float") params[key] = parseFloat(el.value || "0");
    else params[key] = el.value;
  });
  return params;
}

async function runBacktest() {
  const btn = $("#bt-run");
  btn.disabled = true;
  $("#bt-status").textContent = "回测计算中…";
  const body = {
    symbol: S.symbol,
    strategy: S.strategy,
    params: collectParams(),
    settings: {
      initial_cash: parseFloat($("#bt-cash").value) || 100000,
      fee_rate: parseFloat($("#bt-fee").value) || 0.0003,
      slippage: parseFloat($("#bt-slip").value) || 0.0002,
      allow_short: $("#bt-short").checked,
    },
  };
  try {
    const r = await API.post("/api/backtest", body);
    renderBacktest(r);
    $("#bt-status").textContent = `样本 ${r.dates.length} 根K线 · 数据源 ${r.source.source_label || ""} · 信号次日开盘成交`;
  } catch (e) {
    toast(e.message, "error");
    $("#bt-status").textContent = e.message;
  } finally {
    btn.disabled = false;
  }
}

function renderBacktest(r) {
  const m = r.metrics;
  const cards = [
    ["总收益", m.total_return, "%", m.total_return >= 0],
    ["年化收益", m.annual_return, "%", m.annual_return >= 0],
    ["夏普比率", m.sharpe, "", m.sharpe >= 0],
    ["最大回撤", m.max_drawdown, "%", m.max_drawdown >= 0],
    ["胜率", m.win_rate, "%", m.win_rate >= 50],
    ["交易次数", m.trades, "笔", true],
    ["超额收益", m.excess_return, "%", m.excess_return >= 0],
    ["期末资金", m.final_equity, "元", m.final_equity >= 0],
  ];
  $("#bt-metrics").innerHTML = cards
    .map(([label, val, unit, good]) => {
      const isPct = unit === "%";
      const txt = isPct ? signed(val, 2) : label === "期末资金" ? fmt(val, 0) : fmt(val, 0);
      return `<div class="metric ${good ? "up" : "down"}"><label>${label}</label><b>${txt}<span class="unit">${unit}</span></b></div>`;
    })
    .join("");
  $("#bt-result-meta").textContent = `${r.name} ${r.symbol} · ${r.strategy}`;
  Charts.setEquity(r);
  Charts.setDrawdown(r);
  const rows = r.trades
    .map(
      (t) => `<tr>
        <td>${t.direction}</td><td>${t.entry_date}</td><td>${t.exit_date}</td>
        <td>${fmt(t.entry_price)}</td><td>${fmt(t.exit_price)}</td><td>${t.qty}</td>
        <td>${t.hold_days}天</td>
        <td class="${t.pnl >= 0 ? "up" : "down"}">${signed(t.pnl, 0)}</td>
        <td class="${t.pnl >= 0 ? "up" : "down"}">${signed(t.pnl_pct, 2, "%")}</td>
      </tr>`
    )
    .join("");
  $("#bt-trades tbody").innerHTML =
    rows || `<tr><td class="empty" colspan="9">该参数下没有产生交易，试着放宽阈值或更换策略</td></tr>`;
  $("#trade-count").textContent = `共 ${r.trades.length} 笔（倒序）`;
  Charts.resizeAll();
}

async function generateStrategy() {
  const req = $("#ai-req").value.trim();
  if (!req) {
    toast("请先描述策略需求", "error");
    return;
  }
  const out = $("#ai-out");
  out.classList.remove("hidden");
  out.textContent = "正在生成…";
  $("#ai-gen").disabled = true;
  let text = "";
  try {
    await API.stream("/api/llm/strategy", { symbol: S.symbol, requirement: req }, (ev) => {
      if (ev.delta) {
        text += ev.delta;
        out.textContent = text;
      }
      if (ev.done) {
        if (ev.error) out.textContent = text + "\n\n[提示] " + ev.error;
        const codeMatch = text.match(/```(?:python|py)?\s*([\s\S]*?)```/);
        if (codeMatch && codeMatch[1].includes("generate_signals")) {
          S.strategy = "custom";
          $("#bt-strategy").value = "custom";
          renderStrategyParams(currentStrategy());
          const ta = $('#bt-params textarea[data-key="code"]');
          if (ta) ta.value = codeMatch[1].trim();
          toast("已把生成的策略填入自定义代码，可直接回测", "ok");
        }
        setTimeout(() => Charts.resizeAll(), 60);
      }
    });
  } catch (e) {
    out.textContent = "生成失败：" + e.message;
  } finally {
    $("#ai-gen").disabled = false;
  }
}

function renderFactorIds() {
  $("#factor-ids").innerHTML = S.lib
    .map((f) => `<span class="fid">${f.id}</span>`)
    .join("");
}

/* ---------------- 设置 ---------------- */
function openSettings() {
  const cfg = S.cfg;
  if (!cfg) return;
  $("#set-source").value = cfg.data_source || "auto";
  $("#set-tick").value = cfg.tick_interval ?? 2;
  $("#set-bars").value = cfg.bars ?? 600;
  $("#set-llm-url").value = cfg.llm.base_url || "";
  $("#set-llm-model").value = cfg.llm.model || "";
  $("#set-llm-key").value = "";
  $("#set-llm-keyhint").textContent = cfg.llm.has_key ? `（已配置 ${cfg.llm.key_hint}，留空不修改）` : "（未配置，将使用本地规则解读）";
  $("#set-qmt-path").value = (cfg.qmt && cfg.qmt.mini_qmt_path) || "";
  $("#set-qmt-acc").value = (cfg.qmt && cfg.qmt.account_id) || "";
  $("#set-symbols").value = (cfg.symbols || []).join(",");
  const status = S.lastStatus;
  if (status && status.data) {
    const s = status.data.sources || {};
    $("#set-source-hint").textContent = Object.entries(s)
      .map(([k, v]) => `${v.label}：${v.available ? "可用" : "不可用"}`)
      .join("；");
  }
  $("#modal-mask").classList.add("show");
}

async function saveSettings() {
  const symbols = $("#set-symbols").value
    .split(/[,，\s]+/)
    .map((s) => s.trim())
    .filter((s) => /^\d{6}$/.test(s));
  const patch = {
    data_source: $("#set-source").value,
    tick_interval: parseFloat($("#set-tick").value) || 2,
    bars: parseInt($("#set-bars").value) || 600,
    symbols: symbols.length ? symbols : S.cfg.symbols,
    llm: {
      base_url: $("#set-llm-url").value.trim(),
      model: $("#set-llm-model").value.trim(),
    },
    qmt: {
      mini_qmt_path: $("#set-qmt-path").value.trim(),
      account_id: $("#set-qmt-acc").value.trim(),
    },
  };
  const key = $("#set-llm-key").value.trim();
  if (key) patch.llm.api_key = key;
  const btn = $("#m-save");
  btn.disabled = true;
  try {
    const res = await API.post("/api/config", patch);
    S.cfg = res.config;
    $("#modal-mask").classList.remove("show");
    toast("设置已保存，正在重载行情…", "ok");
    await refreshAll();
  } catch (e) {
    toast(e.message, "error");
  } finally {
    btn.disabled = false;
  }
}

async function refreshAll() {
  const [syms, status] = await Promise.all([API.get("/api/symbols"), API.get("/api/status")]);
  S.symbols = syms.items;
  applyStatus(status);
  updateSourceBadge(status.data);
  renderWatchlist($("#symbol-search").value);
  if (S.ws && S.ws.readyState === 1) S.ws.send(JSON.stringify({ action: "refresh" }));
  else {
    try { renderSnapshot(await API.get(`/api/snapshot?symbol=${S.symbol}&refresh=1`)); } catch (e) {}
  }
}

function applyStatus(status) {
  S.lastStatus = status;
  const dot = $("#llm-dot");
  const configured = status.llm_configured;
  dot.className = "dot " + (configured ? "ok" : "warn");
  $("#llm-state").textContent = configured ? `大模型已就绪 · ${status.llm_model || ""}` : "大模型未配置（本地解读）";
}

/* ---------------- 事件绑定 ---------------- */
function bindEvents() {
  document.querySelectorAll(".tab").forEach((btn) =>
    btn.addEventListener("click", () => switchView(btn.dataset.view))
  );
  $("#watchlist").addEventListener("click", (e) => {
    const item = e.target.closest(".w-item");
    if (item) switchSymbol(item.dataset.code);
  });
  $("#symbol-search").addEventListener("input", (e) => renderWatchlist(e.target.value));
  $("#btn-add-symbol").addEventListener("click", async () => {
    const code = $("#symbol-search").value.trim();
    if (!/^\d{6}$/.test(code)) {
      toast("请输入6位股票代码，例如 600519", "error");
      return;
    }
    const symbols = Array.from(new Set([...(S.cfg.symbols || []), code]));
    try {
      const res = await API.post("/api/config", { symbols });
      S.cfg = res.config;
      const syms = await API.get("/api/symbols");
      S.symbols = syms.items;
      $("#symbol-search").value = "";
      renderWatchlist();
      switchSymbol(code);
      toast("已添加 " + code, "ok");
    } catch (e) {
      toast(e.message, "error");
    }
  });

  const grid = $("#factor-grid");
  grid.addEventListener("click", (e) => {
    const card = e.target.closest(".fcard");
    if (!card) return;
    const f = S.factors.find((x) => x.id === card.dataset.id);
    if (f) openDrawer(f);
  });
  $("#lib-list").addEventListener("click", (e) => {
    const row = e.target.closest(".lib-item");
    if (!row) return;
    const f = S.factors.find((x) => x.id === row.dataset.id);
    if (f) openDrawer(f);
  });

  $("#d-close").addEventListener("click", closeDrawer);
  $("#drawer-mask").addEventListener("click", closeDrawer);
  $("#d-ai-btn").addEventListener("click", generateExplain);

  $("#btn-settings").addEventListener("click", openSettings);
  $("#btn-side-llm").addEventListener("click", openSettings);
  $("#m-close").addEventListener("click", () => $("#modal-mask").classList.remove("show"));
  $("#m-cancel").addEventListener("click", () => $("#modal-mask").classList.remove("show"));
  $("#m-save").addEventListener("click", saveSettings);
  $("#modal-mask").addEventListener("click", (e) => {
    if (e.target.id === "modal-mask") $("#modal-mask").classList.remove("show");
  });

  $("#btn-help").addEventListener("click", () => $("#help-mask").classList.add("show"));
  $("#h-close").addEventListener("click", () => $("#help-mask").classList.remove("show"));
  $("#h-ok").addEventListener("click", () => $("#help-mask").classList.remove("show"));
  $("#help-mask").addEventListener("click", (e) => {
    if (e.target.id === "help-mask") $("#help-mask").classList.remove("show");
  });

  $("#btn-refresh").addEventListener("click", async () => {
    $("#btn-refresh").style.transform = "rotate(180deg)";
    setTimeout(() => ($("#btn-refresh").style.transform = ""), 400);
    if (S.ws && S.ws.readyState === 1) S.ws.send(JSON.stringify({ action: "refresh" }));
    else refreshAll();
  });

  $("#bt-strategy").addEventListener("change", (e) => {
    S.strategy = e.target.value;
    renderStrategyParams(currentStrategy());
  });
  $("#bt-run").addEventListener("click", runBacktest);
  $("#ai-gen").addEventListener("click", generateStrategy);

  $$(".chip[data-chart]").forEach((btn) =>
    btn.addEventListener("click", () => {
      $$(".chip[data-chart]").forEach((b) => b.classList.toggle("active", b === btn));
      const mode = btn.dataset.chart;
      $("#chart-price").style.display = mode === "kline" ? "block" : "none";
      $("#chart-factor-trend").style.display = mode === "factor" ? "block" : "none";
      $("#factor-toggles").style.display = mode === "factor" ? "flex" : "none";
      if (mode === "kline") Charts.kline && Charts.kline.resize();
      else Charts.trend && Charts.trend.resize();
    })
  );

  window.addEventListener("resize", debounce(() => Charts.resizeAll(), 150));
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      closeDrawer();
      $("#modal-mask").classList.remove("show");
      $("#help-mask").classList.remove("show");
    }
  });
}

function closeDrawer() {
  $("#drawer").classList.remove("show");
  $("#drawer-mask").classList.remove("show");
  S.currentFactor = null;
}

function switchView(name) {
  S.view = name;
  $$(".tab").forEach((b) => b.classList.toggle("active", b.dataset.view === name));
  $$(".view").forEach((v) => v.classList.toggle("active", v.id === "view-" + name));
  setTimeout(() => Charts.resizeAll(), 60);
}

function debounce(fn, ms) {
  let t;
  return (...args) => {
    clearTimeout(t);
    t = setTimeout(() => fn(...args), ms);
  };
}

document.addEventListener("DOMContentLoaded", init);
