// Seoul Fried Chicken — 손님 주문 화면.
//
// 손님은 요리를 주문한다. 주문은 재료로 풀려 그 지점 재고에서 빠지고, 온체인 이체 1건으로
// 결제되고(메모 = 주문번호), 재료가 안전선을 깨면 지점 에이전트가 그 자리에서 조달을 시작한다.
// 이 화면의 일은 그 반응을 손님 자리에서 끝까지 보여주는 것 — 지어내는 상태(조리 중·배달 중)는 없다.
// 결제(tx)·재고 이동·에이전트 판단, 전부 라이브 시스템의 실제 기록이다.

import { startI18n } from "/assets/i18n.js";
startI18n();

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const fmt = (n) => Number(n ?? 0).toFixed(2);
const explorer = (tx, net) =>
  `https://explorer.solana.com/tx/${encodeURIComponent(tx)}?cluster=${encodeURIComponent(net || "devnet")}`;

let toastTimer;
function toast(html, warn = false) {
  document.querySelector(".toast")?.remove();
  const el = document.createElement("div");
  el.className = `toast ${warn ? "warn" : ""}`;
  el.innerHTML = html;
  document.body.appendChild(el);
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.remove(), 7000);
}

// ── 상태 ────────────────────────────────────────────────────────────
const state = { board: null, storeId: null, cart: new Map() };  // cart: itemId → qty

async function loadWallet() {
  try {
    const w = await (await fetch("/api/shop/wallet")).json();
    $("gw-usdc").innerHTML = w.usdc == null
      ? "<small>slow to load — refreshing shortly</small>"
      : `${w.usdc} <small>USDC</small>`;
    $("gw-addr").textContent = w.address ? `${w.address.slice(0, 6)}…${w.address.slice(-6)}` : "";
  } catch { /* 지갑 조회가 늦어도 메뉴판은 산다 */ }
}

async function loadBoard() {
  const res = await fetch("/api/shop/menu");
  if (!res.ok) throw new Error(`menu ${res.status}`);
  state.board = await res.json();
  $("brand-name").textContent = state.board.brand.name;
  $("brand-tag").textContent = state.board.brand.tagline ? `${state.board.brand.tagline} ` : "";
  document.title = `${state.board.brand.name} — order`;
  if (!state.storeId || !state.board.stores.some((s) => s.id === state.storeId)) {
    state.storeId = state.board.stores[0].id;
  }
}

const currentStore = () => state.board.stores.find((s) => s.id === state.storeId);

// 재료 이름 — 메뉴판의 레시피에서 모은다 (주문 문서는 SKU만 들고 있다)
function nameOf(sku) {
  for (const s of state.board?.stores ?? []) {
    for (const it of s.items) {
      const r = it.recipe.find((x) => x.sku === sku);
      if (r) return r.name;
    }
  }
  return sku;
}

// ── 라우팅 — /shop (메뉴판) · /shop/orders/{id} (주문 추적) ──────────
function route() {
  const m = location.pathname.match(/^\/shop\/orders\/([^/]+)/);
  if (m) return showOrder(decodeURIComponent(m[1]));
  return showMenu();
}
function go(path) {
  history.pushState({}, "", path);
  route();
}
window.addEventListener("popstate", route);

// ── 메뉴판 ──────────────────────────────────────────────────────────
async function showMenu() {
  stopLive();
  clearInterval(orderPoll);
  if (!state.board) {
    $("view").innerHTML = '<div class="empty">Loading the menu…</div>';
    try { await loadBoard(); } catch { $("view").innerHTML = '<div class="empty">Could not load the menu. Try again shortly.</div>'; return; }
  }
  renderMenu();
  $("cart").hidden = false;
  renderCart();
}

function regionOf(storeName) {
  const m = /\(([^)]+)\)/.exec(storeName);  // "Store A (Gangnam)" → Gangnam
  return m ? m[1] : storeName;
}

function renderMenu() {
  const store = currentStore();
  const tabs = state.board.stores.map((s) =>
    `<button class="sf-tab ${s.id === state.storeId ? "on" : ""}" data-store="${esc(s.id)}">${esc(s.name)}</button>`).join("");
  const cards = store.items.map((it) => {
    const out = it.servings <= 0;
    const qty = state.cart.get(it.id) || 0;
    const uses = it.recipe.map((r) => esc(r.name) + (r.qty > 1 ? ` ×${r.qty}` : "")).join(", ");
    return `
      <article class="sf-item ${out ? "out" : ""}">
        <div class="sf-item-top"><h3>${esc(it.name)}</h3><span class="sf-price">${fmt(it.price_usdc)} <small>USDC</small></span></div>
        ${it.exclusive ? `<span class="sf-badge">${esc(regionOf(store.name))} only</span>` : ""}
        <p class="sf-blurb">${esc(it.blurb)}</p>
        <p class="sf-uses">Uses: ${uses}</p>
        <div class="sf-item-foot">
          <span class="sf-servings ${!out && it.servings <= 2 ? "low" : ""}">
            ${out ? "Sold out — the store's agent is restocking" : `${it.servings} serving${it.servings === 1 ? "" : "s"} left`}
          </span>
          <div class="sf-qty">
            <button data-dec="${esc(it.id)}" ${qty ? "" : "disabled"} aria-label="remove one ${esc(it.name)}">−</button>
            <b>${qty}</b>
            <button data-inc="${esc(it.id)}" ${out || qty >= it.servings ? "disabled" : ""} aria-label="add one ${esc(it.name)}">+</button>
          </div>
        </div>
      </article>`;
  }).join("");

  $("view").innerHTML = `
    <nav class="sf-tabs" aria-label="Stores">${tabs}</nav>
    <p class="sf-store-note">${esc(store.id)} · every order here is real demand — when an ingredient drops below its
      safety line, this store's agent starts procuring on the spot (a peer trade with a neighbouring store, or an order from HQ).</p>
    <div class="sf-grid">${cards}</div>`;

  $("view").querySelectorAll("[data-store]").forEach((b) => b.addEventListener("click", () => {
    if (b.dataset.store === state.storeId) return;
    state.storeId = b.dataset.store;
    state.cart.clear();  // 장바구니는 한 지점의 것 — 주문도 한 지점에 한 번
    renderMenu(); renderCart();
  }));
  $("view").querySelectorAll("[data-inc]").forEach((b) => b.addEventListener("click", () => bump(b.dataset.inc, +1)));
  $("view").querySelectorAll("[data-dec]").forEach((b) => b.addEventListener("click", () => bump(b.dataset.dec, -1)));
}

const totalServings = () => [...state.cart.values()].reduce((a, b) => a + b, 0);

function bump(itemId, d) {
  const max = state.board.max_servings;
  if (d > 0 && totalServings() >= max) { toast(`Up to ${max} servings per order — this keeps the shelves fair for the next visitor.`, true); return; }
  const q = (state.cart.get(itemId) || 0) + d;
  if (q <= 0) state.cart.delete(itemId); else state.cart.set(itemId, q);
  renderMenu(); renderCart();
}

function renderCart() {
  const store = currentStore();
  const items = new Map(store.items.map((i) => [i.id, i]));
  const lines = [...state.cart].map(([id, q]) => ({ it: items.get(id), q })).filter((l) => l.it);
  const total = lines.reduce((s, l) => s + l.it.price_usdc * l.q, 0);
  $("cart-store").textContent = store.name;
  $("cart-count").textContent = `${totalServings()} / ${state.board.max_servings} servings`;
  $("cart-lines").innerHTML = lines.length
    ? lines.map((l) => `<li><span>${esc(l.it.name)} <i>×${l.q}</i></span><b>${fmt(l.it.price_usdc * l.q)}</b></li>`).join("")
    : '<li class="sf-empty">Your cart is empty — add something from the menu.</li>';
  $("cart-total").textContent = fmt(total);
  $("cart-pay").disabled = !lines.length;
}

async function placeOrder() {
  const btn = $("cart-pay");
  if (btn.disabled) return;
  btn.disabled = true; btn.textContent = "Paying on-chain…";
  try {
    const res = await fetch("/api/shop/order", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        store_id: state.storeId,
        items: [...state.cart].map(([item_id, qty]) => ({ item_id, qty })),
      }),
    });
    const data = await res.json();
    if (!res.ok) { toast(esc(data.detail ?? "Order failed"), true); return; }
    state.cart.clear();
    state.board = null;  // 재고가 바뀌었다 — 다음 메뉴판은 새로 읽는다
    go(`/shop/orders/${encodeURIComponent(data.id)}`);
    loadWallet();
  } catch {
    toast("Connection failed.", true);
  } finally {
    btn.disabled = false; btn.textContent = "Place order";
  }
}
$("cart-pay").addEventListener("click", placeOrder);

// ── 주문 추적 ──────────────────────────────────────────────────────
let orderPoll = null;
const finished = (o) => (o.agent || []).some((e) => e.action === "shop.procured" || e.action === "shop.procure_failed");

async function showOrder(id) {
  clearInterval(orderPoll);
  $("cart").hidden = true;
  $("view").innerHTML = '<div class="empty">Loading your order…</div>';
  if (!state.board) { try { await loadBoard(); } catch { /* 이름 없이도 그린다 */ } }
  const res = await fetch(`/api/shop/orders/${encodeURIComponent(id)}`);
  if (!res.ok) {
    $("view").innerHTML = `<div class="empty">No such order: ${esc(id)}. <a href="/shop">Back to the menu</a></div>`;
    return;
  }
  const order = await res.json();
  renderOrder(order);
  if (order.trigger === "started" || order.trigger === "tick_running") {
    startLive(order.store_id, order.store_name, order.trigger);
  }
  if (order.trigger && !finished(order)) {
    orderPoll = setInterval(async () => {
      try {
        const r = await fetch(`/api/shop/orders/${encodeURIComponent(id)}`);
        if (!r.ok) return;
        const o = await r.json();
        renderOrder(o);
        if (finished(o)) clearInterval(orderPoll);
      } catch { /* 다음 폴링 */ }
    }, 5000);
  }
}

function agentStep(o) {
  const last = (o.agent || []).at(-1);
  const p = last?.payload || {};
  if (!o.trigger) return ["idle", "Every ingredient stayed above its safety line — no reorder needed."];
  if (last?.action === "shop.procured") {
    const route = p.route === "p2p" ? "arranged a peer trade with a neighbouring store"
      : p.route === "hq_order" ? "ordered from HQ"
      : p.route === "hold" ? "held off — too many open invoices" : (p.route || "finished");
    const tail = [p.invoice_id && `invoice ${p.invoice_id}`, p.status].filter(Boolean).join(" · ");
    return ["done", `Procurement finished — ${route}${tail ? ` · ${tail}` : ""}.`];
  }
  if (last?.action === "shop.procure_failed") {
    return ["failed", `This round was recorded as a failure — the next tick retries.${p.status ? ` (${p.status})` : ""}`];
  }
  if (o.trigger === "tick_running") return ["running", "The economy tick already running will handle this store shortly."];
  return ["running", "The store's agent is procuring now — its log is streaming below."];
}

function renderOrder(o) {
  const paid = o.status === "paid";
  const [agentState, agentText] = agentStep(o);
  const when = o.created_at ? new Date(o.created_at).toLocaleString() : "";
  $("view").innerHTML = `
    <div class="sf-order">
      <div class="sf-order-head">
        <div>
          <span class="sf-eyebrow">Order</span>
          <h2>${esc(o.id)}</h2>
          <p>${esc(o.store_name)}${when ? ` · ${esc(when)}` : ""}</p>
        </div>
        <a class="sf-link" href="/shop" data-nav>← Back to the menu</a>
      </div>
      <ul class="sf-lines">
        ${o.lines.map((l) => `<li><span>${esc(l.name)} <i>×${l.qty}</i></span><b>${fmt(l.subtotal_usdc)}</b></li>`).join("")}
        <li class="total"><span>Total</span><b>${fmt(o.total_usdc)} USDC</b></li>
      </ul>
      <ol class="sf-steps">
        <li class="${paid ? "ok" : "warn"}">
          <b>${paid ? "Paid on-chain" : "Payment did not go through"}</b>
          <span>${paid
            ? `${fmt(o.paid_usdc)} USDC from your wallet to the franchise HQ, in one transaction with this order number in the memo. <a href="${explorer(o.tx, o.network)}" target="_blank" rel="noopener">View on Solana Explorer ↗</a>`
            : "The sale was still recorded at the store; the transfer failed (usually the customer wallet or the RPC). No fees were charged."}</span>
        </li>
        <li class="ok">
          <b>Ingredients drawn from the store's stock</b>
          <span>${Object.entries(o.ingredients || {}).map(([sku, n]) => `${esc(nameOf(sku))} ×${n}`).join(" · ")}</span>
        </li>
        <li class="${(o.low_stock || []).length ? "warn" : "ok"}">
          <b>Safety-line check</b>
          <span>${(o.low_stock || []).length
            ? `Below the line now: ${o.low_stock.map((s) => esc(nameOf(s))).join(", ")}. Your order is what tipped it.`
            : "Everything is still above the line."}</span>
        </li>
        <li class="${agentState}">
          <b>Store agent</b>
          <span>${esc(agentText)}</span>
        </li>
      </ol>
      <p class="sf-fineprint">Nothing on this page was staged for you: the payment, the stock movement and the agent's decisions are the live
        system's own records. To follow the invoice the agent raised, <a href="/" target="_blank" rel="noopener">open the dashboard ↗</a>
        and choose <b>System Administrator</b>.</p>
    </div>`;
  $("view").querySelector("[data-nav]")?.addEventListener("click", (e) => { e.preventDefault(); go("/shop"); });
}

// ── 실시간 기록 — 대시보드의 SSE(/api/stream)를 그대로 구독한다 ────
let live = null; // { source, timer, store, invoices }

function stopLive(note) {
  if (!live) return;
  live.source.close();
  clearTimeout(live.timer);
  $("live").classList.remove("running");
  if (note) $("live-sub").textContent = note;
  live = null;
}

function liveRow(e) {
  const t = (e.ts ?? "").slice(11, 19) || "--:--:--";
  const p = e.payload ?? {};
  const bits = [];
  if (p.invoice_id) bits.push(esc(p.invoice_id));
  if (p.status) bits.push(esc(p.status));
  if (p.decision) bits.push(esc(p.decision));
  if (p.route) bits.push(esc(p.route));
  if (p.amount_usdc != null) bits.push(`${esc(String(p.amount_usdc))} USDC`);
  if (p.tx) bits.push(`<a href="${explorer(p.tx)}" target="_blank" rel="noopener">tx ↗</a>`);
  return `<li><time>${esc(t)}</time><span class="sl-who">${esc(e.actor)}</span><span class="sl-what">${esc(e.action)}</span><span class="sl-detail">${bits.join(" · ")}</span></li>`;
}

function startLive(storeId, storeName, mode) {
  stopLive();
  const panel = $("live");
  panel.hidden = false;
  panel.classList.add("running");
  $("live-title").textContent = mode === "started"
    ? `${storeName} — agents are moving now`
    : `${storeName} — the running tick will handle procurement shortly`;
  $("live-sub").textContent = "Events pile up here as they arrive";
  $("live-list").innerHTML = "";

  const source = new EventSource("/api/stream");
  live = { source, store: storeId, invoices: new Set(), timer: null };
  live.timer = setTimeout(() => stopLive("You can keep watching in the dashboard's activity log"), 150000);

  source.addEventListener("activity", (ev) => {
    if (!live) return;
    let e;
    try { e = JSON.parse(ev.data); } catch { return; }
    const p = e.payload ?? {};
    const mine = (typeof e.actor === "string" && e.actor.startsWith(storeId))
      || p.store_id === storeId
      || (p.invoice_id && live.invoices.has(p.invoice_id));
    if (!mine) return;
    if (p.invoice_id) live.invoices.add(p.invoice_id);
    $("live-list").insertAdjacentHTML("beforeend", liveRow(e));
    if (e.action === "shop.procured" && p.store_id === storeId) {
      stopLive("Procurement finished — see the invoice on the dashboard");
    } else if (e.action === "shop.procure_failed" && p.store_id === storeId) {
      stopLive("This round was recorded as a failure — the next tick retries");
    }
  });
  source.addEventListener("error", () => { /* 재연결은 브라우저가 한다 */ });
}

// ── 시작 ────────────────────────────────────────────────────────────
loadWallet();
route();
// 다른 손님·에이전트의 활동이 메뉴판의 남은 인분에 반영되게 — 메뉴판을 보고 있을 때만
setInterval(async () => {
  if (location.pathname.includes("/orders/")) return;
  try { await loadBoard(); renderMenu(); renderCart(); } catch { /* 다음에 */ }
}, 30000);
