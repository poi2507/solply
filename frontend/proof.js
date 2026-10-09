// 공개 증빙 — /api/traction 하나로 그린다. 관리자 패널과 같은 원장, 같은 숫자.
// 숫자를 믿으라고 하지 않는다: 결제마다 explorer 링크, 주문마다 추적 페이지 링크.

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const short = (s, a = 6, b = 4) => (s && s.length > a + b + 1 ? `${s.slice(0, a)}…${s.slice(-b)}` : s ?? "");

function explorer(sig, network) {
  const cluster = network === "localnet" ? "custom" : (network || "devnet");
  return `https://explorer.solana.com/tx/${sig}?cluster=${cluster}`;
}
const txLink = (sig, network) => (sig ? `<a href="${explorer(sig, network)}" target="_blank" rel="noopener">${esc(short(sig, 8, 6))}</a>` : "—");

const KIND = {
  supply_route: "Store: restock from a neighbour or HQ?",
  p2p_trade: "HQ: approve a store-to-store trade?",
  order: "HQ: fill this restock order as asked?",
  brokerage: "HQ: broker a stock transfer?",
  order_adjust: "Store: accept HQ's trimmed order?",
  adjustment: "HQ: approve a deduction?",
  deferral: "HQ: allow a payment deferral?",
  counter_response: "Store: accept HQ's installment offer?",
  p2p_respond: "Store: sell at the offered price?",
  p2p_price: "Store: accept the seller's counter price?",
  p2p_consider: "Store: take the brokered trade?",
};
const WHO = { jev: "Jev · System One", llm: "Gemini · System Two", rules: "Rules" };

const when = (iso) => new Date(iso).toLocaleString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", timeZone: "Asia/Seoul" }) + " KST";
const tile = (n, label, foot) => `<div class="pf-tile"><b>${n}</b><span>${esc(label)}</span>${foot ? `<i>${esc(foot)}</i>` : ""}</div>`;

function usage(t) {
  const T = t.totals;
  const max = Math.max(1, ...t.daily.map((d) => d.orders + d.purchases));
  const bars = t.daily.map((d) => {
    const n = d.orders + d.purchases;
    return `<div class="${n ? "" : "zero"}" style="height:${(n / max) * 100}%" title="${esc(d.day)}: ${n} order${n === 1 ? "" : "s"}"></div>`;
  }).join("");
  return `
  <section class="pf-sec">
    <h2>Real usage since ${esc(new Date(`${t.since}T00:00:00+09:00`).toLocaleDateString("en-US", { month: "short", day: "numeric" }))}</h2>
    <p class="sub">${t.simDemand
      ? "Simulated background demand is on and counted separately — it is not included below."
      : "Simulated demand is switched off. Every order below came from a person on the storefront; an hourly job only settles what those orders set in motion."}</p>
    <div class="pf-tiles">
      ${tile(T.orders + T.purchases, "customer orders", `${T.real_servings} servings drawn from real store stock`)}
      ${tile(T.paid_usdc.toFixed(2), "USDC paid on-chain", `${T.own_wallet_orders} paid from visitors' own wallets`)}
      ${tile(`${T.procured}/${T.triggered}`, "agent restocks finished", `${T.failed} failed`)}
      ${tile(T.visitors, "unique visitors", "counted from Sep 23")}
    </div>
    <div class="pf-bars" role="img" aria-label="Customer orders per day">${bars}</div>
    <div class="pf-axis"><span>${esc(t.daily[0]?.day.slice(5) ?? "")}</span><span>orders per day</span><span>${esc(t.daily.at(-1)?.day.slice(5) ?? "")}</span></div>
  </section>`;
}

function ledger(t) {
  if (!t.ledger.length) return `<section class="pf-sec"><h2>Order ledger</h2><div class="empty">No customer orders yet — <a href="/shop">be the first</a>.</div></section>`;
  const rows = t.ledger.map((o) => `
    <tr>
      <td class="n">${esc(when(o.ts))}</td>
      <td><a href="/shop/orders/${encodeURIComponent(o.order_id)}" target="_blank" rel="noopener">${esc(o.order_id)}</a></td>
      <td>${esc((o.items || []).join(", "))}<br><span style="color:var(--ink-3)">${esc(o.store_id)}</span></td>
      <td class="n">${o.amount_usdc != null ? Number(o.amount_usdc).toFixed(2) : "—"}</td>
      <td><span class="chip ${o.payer === "own_wallet" ? "own" : ""}">${o.payer === "own_wallet" ? "own wallet" : "demo wallet"}</span><br>${txLink(o.tx, t.network)}</td>
      <td>${o.invoice
        ? `${esc(o.invoice.id)} · ${esc(o.invoice.status)}<br>${txLink(o.invoice.tx, t.network)}`
        : `<span style="color:var(--ink-3)">${o.trigger ? "restock started — no HQ invoice linked" : "stock still above safety line"}</span>`}</td>
    </tr>`).join("");
  return `
  <section class="pf-sec">
    <h2>Order ledger</h2>
    <p class="sub">Customer payment → the store's agent restocks → HQ invoice paid on-chain. Both transactions open on Solana Explorer.</p>
    <div class="pf-scroll"><table class="pf">
      <thead><tr><th>When</th><th>Order</th><th>Items · store</th><th>USDC</th><th>Customer payment</th><th>Restock the order caused</th></tr></thead>
      <tbody>${rows}</tbody>
    </table></div>
  </section>`;
}

// 본사가 지점에 옮긴 운영자금 — 매출이 아니다. 위 합계에 넣지 않고 따로, 이유와 tx를 단다.
function capital(t) {
  if (!t.capital?.length) return "";
  const rows = t.capital.map((c) => `
    <tr><td class="n">${esc(when(c.ts))}</td><td>HQ → ${esc(c.store_id)}</td>
      <td class="n">${Number(c.amount_usdc).toFixed(2)}</td><td>${esc(c.reason)}</td><td>${txLink(c.tx, t.network)}</td></tr>`).join("");
  return `
  <section class="pf-sec">
    <h2>Working capital moved by HQ — not sales</h2>
    <p class="sub">Transfers a person made from HQ to a store so it could keep restocking. They are listed here and left out of every total above.</p>
    <div class="pf-scroll"><table class="pf">
      <thead><tr><th>When</th><th>Transfer</th><th>USDC</th><th>Why</th><th>Transaction</th></tr></thead>
      <tbody>${rows}</tbody>
    </table></div>
  </section>`;
}

function probs(p, choice) {
  if (!p) return "";
  const parts = Object.entries(p).sort((a, b) => b[1] - a[1]);
  return `<div class="probs" title="${esc(parts.map(([k, v]) => `${k} ${Math.round(v * 100)}%`).join(" · "))}">${
    parts.map(([k, v]) => `<span class="${k === choice ? "top" : ""}" style="width:${v * 100}%"></span>`).join("")}</div>`;
}

function decisions(t) {
  const D = t.decisions;
  if (!D || !D.total) return "";
  const items = D.recent.map((d) => {
    const escalated = d.decider !== "jev" && d.confidence != null;
    const badge = escalated
      ? `<span class="chip llm esc">Jev ${Math.round(d.confidence * 100)}% → Gemini</span>`
      : `<span class="chip ${d.decider}">${esc(WHO[d.decider] || d.decider)}${d.decider === "jev" ? ` ${Math.round(d.confidence * 100)}%` : ""}</span>`;
    return `<li>
      <div class="meta">${badge}${probs(d.probabilities, d.decider === "jev" ? d.decision : null)}<span>${esc(when(d.at))}</span></div>
      <div class="why"><b>${esc(KIND[d.kind] || d.kind)}</b> → <b>${esc(d.decision)}</b><br>${esc(d.reasoning)}</div>
    </li>`;
  }).join("");
  return `
  <section class="pf-sec">
    <h2>Who made the agents' decisions</h2>
    <p class="sub">Each judgment is first put to Jev, a System One model that scores the options and returns probabilities.
      If its confidence clears the policy bar (set per store and HQ, default 70%), Jev decides and Gemini only writes the explanation;
      otherwise Gemini reasons it through from scratch. Amounts and limits are always enforced by code.</p>
    <div class="pf-split">
      ${tile(D.total, "agent decisions logged")}
      ${tile(D.jev, "decided by Jev", D.jevAsked ? `asked ${D.jevAsked}× · median confidence ${Math.round(D.confidenceMedian * 100)}%` : "")}
      ${tile(D.escalated, "sent on to Gemini", "Jev was not confident enough")}
      ${tile(D.jevAnswerMsMedian != null ? `${D.jevAnswerMsMedian} ms` : "—", "Jev answer, median",
        D.llmDecisionMsMedian != null ? `Gemini-only decision: ${(D.llmDecisionMsMedian / 1000).toFixed(1)} s` : "")}
    </div>
    <ul class="pf-dec">${items}</ul>
  </section>`;
}

async function load() {
  let t;
  try {
    const r = await fetch("/api/traction");
    if (!r.ok) throw new Error(r.status);
    t = await r.json();
  } catch {
    $("proof").innerHTML = '<div class="empty">Could not load the ledger. Try again in a moment.</div>';
    return;
  }
  $("proof").innerHTML = usage(t) + ledger(t) + capital(t) + decisions(t) +
    `<p class="pf-notes">${t.notes.map(esc).join(" ")} Numbers refresh every 30 seconds.</p>`;
}

load();
setInterval(load, 60_000);
