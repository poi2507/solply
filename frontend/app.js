// Solply 대시보드 — SSE로 에이전트 활동을 실시간 반영한다.
//
// 화면의 중심은 청구서 표다. 행을 누르면 그 청구서 한 건이 발행부터 정산까지
// 어떻게 협상됐는지 펼쳐진다 (/api/invoices/{id}/timeline).
// 목록을 종류별로 흩어놓으면 "무슨 일이 있었나"가 사라지기 때문이다.

import { mount as mountPolicy } from "./policy.js";
import * as role from "./role.js";

const $ = (id) => document.getElementById(id);
const seenInvoices = new Set();
const expanded = new Set();   // 펼쳐둔 청구서 — 새로고침에도 유지한다
const timelines = new Map();  // id → 응답 캐시

const ACTION_LABEL = {
  "invoice.created": "청구서 발행",
  "invoice.adjusted": "청구 금액 정정",
  "invoice.split": "분할 청구서 생성",
  "delivery.verified": "검수 대조",
  "proposal.adjustment": "차감 제안",
  "proposal.deferral": "유예 제안",
  "proposal.installment": "분할 제안",
  "proposal.reviewed": "본사 심사",
  "payment.executed": "결제 실행",
  "payment.verified": "수금 검증",
  "payment.mismatch": "검증 불일치",
  "payment.refused": "결제 거부",
  "payment.blocked_over_limit": "한도 초과 차단",
  "payment.needs_approval": "사람 승인 요청",
  "market.quote_purchased": "시세 데이터 구매 (pay.sh)",
  "x402.payment_required": "x402 결제 요구 (402)",
  "x402.terms_received": "x402 조건 수신",
  "x402.settled": "x402 정산 완료",
  "x402.verification_failed": "x402 검증 실패",
};

const STATUS_LABEL = {
  issued: "발행", paid: "결제됨", settled: "정산완료",
  disputed: "협의중", scheduled: "예약", refused: "거부",
  pending_approval: "승인 대기", split: "분할됨",
};

const KIND_LABEL = { adjustment: "차감", deferral: "유예", installment: "분할" };
const VERDICT_LABEL = { accept: "수락", reject: "거절", counter: "역제안" };

const fmt = (n) => Number(n ?? 0).toLocaleString("ko-KR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const short = (s, head = 6, tail = 4) => (!s ? "" : s.length <= head + tail + 1 ? s : `${s.slice(0, head)}…${s.slice(-tail)}`);
// 로케일 문자열은 브라우저마다 "22:51:39" / "22시 51분 39초"로 갈려 자릿수를 잘라 쓸 수 없다
const pad = (n) => String(n).padStart(2, "0");
const clock = (iso) => {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "--:--:--" : `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
};
const hhmm = (iso) => clock(iso).slice(0, 5);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

async function getJSON(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${url} → ${res.status}`);
  return res.json();
}

function explorerUrl(sig, network) {
  const cluster = network === "localnet" ? "custom" : (network ?? "devnet");
  return `https://explorer.solana.com/tx/${sig}?cluster=${cluster}`;
}

// ── 가맹점 ────────────────────────────────────────────────────────
function renderStores(stores, targetId = "stores") {
  const el = $(targetId);
  if (!el) return;
  if (!stores.length) { el.innerHTML = '<div class="empty">가맹점 정보가 없습니다</div>'; return; }
  el.innerHTML = stores.map((s) => `
    <article class="store">
      <div class="top"><span class="name">${esc(s.name)}</span><span class="score ${s.creditScore >= 85 ? "hi" : "mid"}">${s.creditScore}</span></div>
      <div class="id">${esc(s.id)}</div>
      <div class="gauge"><i style="width:${Math.min(100, s.creditScore)}%"></i></div>
      ${s.creditBasis ? `<div class="basis">정시납 ${s.creditBasis.onTime}${s.creditBasis.liveSettled ? ` <em>+${s.creditBasis.liveSettled} 온체인</em>` : ""} · 연체 ${s.creditBasis.late} · 분쟁 ${s.creditBasis.disputed}</div>` : ""}
      ${(s.inventory || []).length ? `<div class="stock">${s.inventory.map((it) => `<span class="chip ${it.qty < it.safety ? "low" : ""}">${esc(it.name)} ${it.qty}<i> / 안전 ${it.safety}</i></span>`).join("")}</div>` : ""}
      <dl>
        <dt>미수금</dt><dd>${fmt(s.outstandingUsdc)}</dd>
        <dt>정산 완료</dt><dd>${fmt(s.settledUsdc)}</dd>
        <dt>자동결제 한도</dt><dd>${fmt(s.autoPayLimit)}</dd>
      </dl>
    </article>`).join("");
}

// ── 청구서 표 ─────────────────────────────────────────────────────
/** 분할 자식은 부모 바로 아래로 붙인다 — 같은 이야기가 표에서 흩어지지 않게. */
function orderInvoices(invoices) {
  const byParent = new Map();
  for (const inv of invoices) {
    if (!inv.parent_id) continue;
    if (!byParent.has(inv.parent_id)) byParent.set(inv.parent_id, []);
    byParent.get(inv.parent_id).push(inv);
  }
  const out = [];
  for (const inv of invoices) {
    if (inv.parent_id && invoices.some((x) => x.id === inv.parent_id)) continue;
    out.push({ inv, child: false });
    for (const kid of (byParent.get(inv.id) ?? []).sort((a, b) => a.id.localeCompare(b.id))) {
      out.push({ inv: kid, child: true });
    }
  }
  return out;
}

function amountCell(inv) {
  const now = fmt(inv.amount_usdc);
  const before = inv.original_amount_usdc;
  if (before == null || Number(before) === Number(inv.amount_usdc)) return now;
  return `<span class="dash">${fmt(before)} →</span> <b class="amt-chg">${now}</b>`;
}

function invoiceRow({ inv, child }, network, firstPaint) {
  const key = inv.id + inv.status + inv.amount_usdc;
  const isNew = !firstPaint && !seenInvoices.has(key);
  seenInvoices.add(key);
  const open = expanded.has(inv.id);
  const tx = inv.tx_sig
    ? `<a class="txlink" href="${inv.explorer || explorerUrl(inv.tx_sig, network)}" target="_blank" rel="noopener" onclick="event.stopPropagation()">${short(inv.tx_sig, 8, 6)}</a>`
    : '<span class="dash">—</span>';
  const label = STATUS_LABEL[inv.status] ?? inv.status;
  const round = inv.installment ? ` <span class="dash">${inv.installment}회차</span>` : "";

  return `<tr class="pick ${open ? "open" : ""} ${isNew ? "flash" : ""}" data-inv="${esc(inv.id)}">
      <td>
        <span class="caret">${open ? "▾" : "▸"}</span>
        ${child ? '<span class="child-mark">└</span>' : ""}
        <span class="inv-id">${esc(inv.id)}</span>${round}
      </td>
      <td class="col-store">${esc(inv.store_id)}</td>
      <td class="r">${amountCell(inv)}</td>
      <td><span class="state ${inv.status}">${label}</span></td>
      <td>${tx}</td>
    </tr>
    ${open ? `<tr class="detail" data-detail="${esc(inv.id)}"><td colspan="5">${detailBody(inv.id)}</td></tr>` : ""}`;
}

function renderInvoices(invoices, network) {
  const el = $("invoices");
  $("invoice-count").textContent = `${invoices.length}건 · 행을 누르면 협상 과정이 펼쳐집니다`;
  if (!invoices.length) {
    el.innerHTML = '<tr><td colspan="5" class="empty">아직 청구서가 없습니다. 데모를 실행하면 여기에 나타납니다.</td></tr>';
    return;
  }
  // 첫 그림에는 강조를 넣지 않는다 — 전부 새것이라 전부 깜빡이면 아무것도 강조되지 않는다
  const firstPaint = seenInvoices.size === 0;
  el.innerHTML = orderInvoices(invoices)
    .map((entry) => invoiceRow(entry, network, firstPaint)).join("");
  el.querySelectorAll("tr[data-inv]").forEach((tr) => {
    tr.addEventListener("click", () => toggle(tr.dataset.inv));
  });
}

// ── 펼친 행: 청구서 한 건의 전 과정 ────────────────────────────────
function toneOf(evt) {
  const a = evt.action;
  if (a === "delivery.verified") return evt.payload?.match ? "good" : "warn";
  if (/refused|failed|mismatch|blocked/.test(a)) return "risk";
  if (/settled|executed|verified/.test(a)) return "good";
  if (a.startsWith("proposal.") || a === "invoice.split" || a === "invoice.adjusted"
      || a === "payment.needs_approval") return "warn";
  return "info";
}

/** 분할된 가족 안에서 이 단계가 어느 청구서 것인지 — "원본" 또는 "P2". */
function familyLabel(payloadId, invoice) {
  if (!payloadId || payloadId === invoice.id) return null;
  if (payloadId === invoice.parent_id) return "원본";
  const base = invoice.parent_id ?? invoice.id;
  return payloadId.startsWith(`${base}-`) ? payloadId.slice(base.length + 1) : payloadId;
}

function stepExtra(evt, invoice, network) {
  const p = evt.payload ?? {};
  const bits = [];
  const where = familyLabel(p.invoice_id, invoice);
  if (where) bits.push(where);
  if (p.amount != null) bits.push(`${fmt(p.amount)} USDC`);
  if (p.new_amount != null) bits.push(`→ ${fmt(p.new_amount)} USDC`);
  if (p.parts) bits.push(`${p.parts}회 분할`);
  if (evt.action === "delivery.verified") {
    bits.push(p.match ? "일치" : `불일치 ${p.discrepancies?.length ?? 0}건`);
  }
  if (p.tx) {
    bits.push(`<a class="txlink" href="${explorerUrl(p.tx, network)}" target="_blank" rel="noopener">${short(p.tx, 8, 6)}</a>`);
  }
  return bits.length ? `<span class="tl-extra">${bits.join(" · ")}</span>` : "";
}

function detailBody(id) {
  const data = timelines.get(id);
  if (!data) return '<div class="empty">불러오는 중…</div>';
  if (data.error) return `<div class="empty">과정을 불러오지 못했습니다: ${esc(data.error)}</div>`;

  const { invoice, steps, negotiations, network } = data;
  const items = (invoice.items ?? []).map((it) =>
    `<span>${esc(it.name ?? it.sku)} ${it.qty}<i> × ${fmt(it.unit_price_usdc)}</i></span>`).join("");

  // 심사 사유는 이벤트 다음 줄에 붙여, 판단과 근거가 붙어 읽히게 한다
  const negByTime = [...negotiations];
  const flow = steps.map((evt) => {
    const label = ACTION_LABEL[evt.action] ?? evt.action;
    let why = "";
    if (evt.action === "proposal.reviewed") {
      const neg = negByTime.shift();
      if (neg) {
        why = `<div class="tl-why ${esc(neg.decision)}">
          <b>${KIND_LABEL[neg.type] ?? neg.type} ${VERDICT_LABEL[neg.decision] ?? neg.decision}</b> —
          ${esc(neg.proposal)}<br>${esc(neg.reasoning)}</div>`;
      }
    }
    return `<div class="tl-step ${toneOf(evt)}">
        <span class="tl-time">${hhmm(evt.ts)}</span>
        <span class="tl-actor">${esc(evt.actor.replace("-agent", ""))}</span>
        <span class="tl-body"><span class="tl-what">${esc(label)}</span>${stepExtra(evt, invoice, network)}${why}</span>
      </div>`;
  }).join("");

  return `
    <div class="detail-head">
      납품 ${esc(invoice.delivery_id ?? "—")} · ${esc(invoice.store_id)}
      ${invoice.adjusted ? " · 금액 정정됨" : ""}${invoice.installment ? ` · 분할 ${esc(invoice.installment)}회차` : ""}
    </div>
    ${items ? `<div class="detail-items">${items}</div>` : ""}
    <div class="timeline">${flow || '<div class="empty">기록된 단계가 없습니다</div>'}</div>`;
}

function paintDetail(id) {
  const cell = document.querySelector(`tr[data-detail="${id}"] td`);
  if (cell) cell.innerHTML = detailBody(id);
}

async function loadTimeline(id, network) {
  try {
    const data = await getJSON(`/api/invoices/${encodeURIComponent(id)}/timeline`);
    timelines.set(id, { ...data, network });
  } catch (err) {
    timelines.set(id, { error: err.message });
  }
  paintDetail(id);
}

let currentNetwork = "devnet";

function toggle(id) {
  const tr = document.querySelector(`tr[data-inv="${id}"]`);
  if (expanded.has(id)) {
    expanded.delete(id);
    tr?.classList.remove("open");
    tr?.querySelector(".caret")?.replaceChildren("▸");
    document.querySelector(`tr[data-detail="${id}"]`)?.remove();
    return;
  }
  expanded.add(id);
  tr?.classList.add("open");
  tr?.querySelector(".caret")?.replaceChildren("▾");
  const detail = document.createElement("tr");
  detail.className = "detail";
  detail.dataset.detail = id;
  detail.innerHTML = `<td colspan="5">${detailBody(id)}</td>`;
  tr?.after(detail);
  loadTimeline(id, currentNetwork);
}

// ── 목록형 ────────────────────────────────────────────────────────
function renderNegotiations(negs) {
  const el = $("negotiations");
  if (!negs.length) {
    el.innerHTML = '<div class="empty">협상 기록이 없습니다</div>';
    return;
  }
  el.innerHTML = negs.map((n) => `
    <div class="row">
      <span class="kind">${KIND_LABEL[n.type] ?? esc(n.type)}</span>
      <div class="body">
        <div class="head">${esc(n.proposal ?? "")}</div>
        <div class="why"><b>본사 판단:</b> ${esc(n.reasoning ?? "")}</div>
      </div>
      <span class="verdict ${esc(n.decision)}">${VERDICT_LABEL[n.decision] ?? esc(n.decision)}</span>
    </div>`).join("");
}

function renderTrades(trades) {
  const el = $("trades");
  if (!el) return;
  if (!trades || !trades.length) {
    el.innerHTML = '<div class="empty">아직 지점 간 직거래가 없습니다</div>';
    return;
  }
  const STATUS = { proposed: "제안됨", accepted: "수락", approved: "본사 승인", paid: "결제됨", confirmed: "확정", rejected: "거절" };
  el.innerHTML = trades.map((t) => {
    const tx = t.tx_sig
      ? ` · <a class="txlink" href="${explorerUrl(t.tx_sig, currentNetwork)}" target="_blank" rel="noopener">${short(t.tx_sig, 8, 6)}</a>`
      : "";
    const tone = t.status === "confirmed" ? "accept" : t.status === "rejected" ? "reject" : "counter";
    return `
    <div class="row">
      <span class="kind">P2P</span>
      <div class="body">
        <div class="head">${esc(t.buyer_id)} ← ${esc(t.seller_id)} · ${esc(t.name ?? t.sku)} ×${t.qty} · ${fmt(t.price_usdc)} USDC</div>
        <div class="why">재고 부족분을 본사 청구 대신 옆 지점에서 조달했습니다${tx}</div>
      </div>
      <span class="verdict ${tone}">${STATUS[t.status] ?? esc(t.status)}</span>
    </div>`;
  }).join("");
}

function renderSchedules(invoices) {
  const panel = $("schedules-panel");
  const el = $("schedules");
  if (!panel || !el) return;
  const scheduled = (invoices || []).filter((inv) => inv.status === "scheduled");
  panel.style.display = scheduled.length ? "" : "none";
  el.innerHTML = scheduled.map((inv) => `
    <div class="row">
      <span class="kind">예약</span>
      <div class="body">
        <div class="head">${esc(inv.id)} · ${esc(inv.store_id)} · ${fmt(inv.amount_usdc)} USDC${inv.installment ? ` · 분할 ${esc(inv.installment)}회차` : ""}</div>
        <div class="why">예약일이 오면 에이전트가 x402 왕복으로 결제합니다</div>
      </div>
      <span class="actions"><button class="btn btn-approve" data-run="${esc(inv.id)}">지금 실행</button></span>
    </div>`).join("");
  el.querySelectorAll("button[data-run]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      btn.disabled = true;
      btn.textContent = "실행 중…";
      try {
        await fetch(`/api/schedules/${btn.dataset.run}/run`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ simulate_inflow: true }),  // 데모: 예약일의 입금까지 시간을 당긴다
        });
      } finally {
        refresh();
      }
    });
  });
}

function renderApprovals(invoices) {
  const panel = $("approvals-panel");
  const el = $("approvals");
  if (!panel || !el) return;
  const pending = (invoices || []).filter((inv) => inv.status === "pending_approval");
  panel.style.display = pending.length ? "" : "none";
  el.innerHTML = pending.map((inv) => `
    <div class="row">
      <span class="kind">승인</span>
      <div class="body">
        <div class="head">${esc(inv.id)} · ${esc(inv.store_id)} · ${fmt(inv.amount_usdc)} USDC</div>
        <div class="why">자동결제 상한을 넘어 에이전트가 결제를 보류했습니다 — 사람이 결정할 지점입니다</div>
      </div>
      <span class="actions">
        <button class="btn btn-approve" data-id="${esc(inv.id)}" data-decision="approve">승인</button>
        <button class="btn btn-reject" data-id="${esc(inv.id)}" data-decision="reject">반려</button>
      </span>
    </div>`).join("");
  el.querySelectorAll("button[data-id]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      btn.disabled = true;
      try {
        await fetch(`/api/approvals/${btn.dataset.id}/decide`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ decision: btn.dataset.decision }),
        });
      } finally {
        refresh();
      }
    });
  });
}

// ── 실행 로그 · 지갑 ──────────────────────────────────────────────
function eventRow(evt, isNew) {
  const label = ACTION_LABEL[evt.action] ?? evt.action;
  const p = evt.payload ?? {};
  let meta = "";
  if (p.invoice_id) meta = p.invoice_id;
  if (p.tx) meta += ` · ${short(p.tx, 10, 6)}`;
  if (p.amount != null) meta += ` · ${fmt(p.amount)} USDC`;
  if (p.new_amount != null) meta += ` → ${fmt(p.new_amount)} USDC`;
  if (evt.action === "delivery.verified") meta += p.match ? " · 일치" : ` · 불일치 ${p.discrepancies?.length ?? 0}건`;
  return `<li class="${isNew ? "new" : ""}">
    <span class="t">${clock(evt.ts)}</span>
    <span class="what">
      <span class="who">${esc(evt.actor.replace("-agent", ""))}</span><span class="act ${toneOf(evt)}">${esc(label)}</span>
      ${meta ? `<span class="meta">${esc(meta)}</span>` : ""}
    </span>
  </li>`;
}

function renderWallets(wallets) {
  $("wallets").innerHTML = wallets.map((w) => w.error
    ? `<div class="wallet"><div class="line"><span class="who2">${esc(w.wallet)}</span></div><div class="err">결제 서비스 연결 안 됨</div></div>`
    : `<div class="wallet">
         <div class="line"><span class="who2">${esc(w.wallet)}</span><span class="usdc">${fmt(w.usdc)} <small>USDC</small></span></div>
         <div class="line"><span class="addr">${short(w.address, 10, 6)}</span><span class="sol">${Number(w.sol).toFixed(3)} SOL</span></div>
       </div>`).join("");
}

// ── 리포트 · 어시스턴트 ───────────────────────────────────────────
const reportBtn = $("report-btn");
if (reportBtn) {
  reportBtn.addEventListener("click", async () => {
    reportBtn.disabled = true;
    reportBtn.textContent = "생성 중…";
    try {
      const r = await getJSON("/api/report");
      $("report-text").textContent = r.report || "아직 요약할 정산 내역이 없습니다.";
    } catch {
      $("report-text").textContent = "리포트 생성에 실패했습니다.";
    } finally {
      reportBtn.disabled = false;
      reportBtn.textContent = "생성";
    }
  });
}

/** 말풍선용 경량 마크다운 — 굵게·코드·목록·헤딩만. 전부 이스케이프한 뒤에 입힌다. */
function mdLite(text) {
  let h = esc(text);
  h = h.replace(/`([^`\n]+)`/g, "<code>$1</code>");
  h = h.replace(/\*\*([^*\n]+)\*\*/g, "<b>$1</b>");
  h = h.replace(/^#{1,4}\s*(.+)$/gm, "<b>$1</b>");     // 헤딩은 굵은 줄로
  h = h.replace(/^(\s*)[-*]\s+/gm, "$1· ");            // 불릿
  h = h.replace(/^-{3,}\s*$/gm, "");                   // 구분선 제거
  return h.replace(/\n{3,}/g, "\n\n");
}

const chatForm = $("chat-form");
if (chatForm) {
  const log = $("chat-log");
  const input = $("chat-input");
  const append = (text, who) => {
    const li = document.createElement("li");
    li.className = `msg ${who}`;
    if (who === "bot") li.innerHTML = mdLite(text);
    else li.textContent = text;
    log.appendChild(li);
    log.scrollTop = log.scrollHeight;
    return li;
  };
  chatForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const message = input.value.trim();
    if (!message) return;
    input.value = "";
    input.disabled = true;
    append(message, "user");
    const waiting = append("…", "bot");
    try {
      const res = await fetch("/api/assistant/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message }),
      });
      const data = await res.json();
      if (res.ok) waiting.innerHTML = mdLite(data.reply);
      else waiting.textContent = data.detail ?? "응답 실패";
    } catch {
      waiting.textContent = "연결에 실패했습니다.";
    } finally {
      input.disabled = false;
      input.focus();
      refresh();  // 승인·예약 실행이 있었으면 화면에 바로 반영
    }
  });
}

// ── 지표 · 시스템 ─────────────────────────────────────────────────
let me = null;          // 현재 역할
let lastWallets = [];   // 지표에서 재사용
let lastView = null;    // 지갑이 늦게 도착하면 지표만 다시 그린다

// ── 재고 원장 ────────────────────────────────────────────────────────
const MOVE_LABEL = { received: "입고", shipped: "출고", sold: "판매", p2p_in: "직거래 입고", p2p_out: "직거래 출고" };
const storeLabel = (id) => (id === "hq" ? "본사 창고" : id);

function stockBar(qty, safety) {
  // 막대의 눈금: 안전재고의 2배(최소 보유량과 여유가 함께 보이는 배율)와 현재고 중 큰 쪽
  const denom = Math.max(qty, safety * 2, 1);
  const fill = Math.max(2, Math.min(100, (qty / denom) * 100));
  const tick = safety > 0 ? Math.min(100, (safety / denom) * 100) : null;
  return `<div class="stockbar ${qty < safety ? "low" : ""}">
    <i style="width:${fill}%"></i>${tick != null ? `<b style="left:${tick}%" title="안전재고 ${safety}"></b>` : ""}
  </div>`;
}

function renderInventory(rows, moves) {
  const table = $("stock-table");
  if (!table) return;

  table.innerHTML = rows.length
    ? rows.map((r) => `<tr>
        <td class="col-store">${esc(r.store)}</td>
        <td>${esc(r.name)}</td>
        <td class="r stock-qty"><b>${r.qty}</b><i> / 안전 ${r.safety}</i></td>
        <td class="stockbar-cell">${stockBar(r.qty, r.safety)}</td>
        <td><span class="state ${r.qty < r.safety ? "disputed" : "settled"}">${r.qty < r.safety ? "안전재고 미달" : "정상"}</span></td>
      </tr>`).join("")
    : '<tr><td colspan="5" class="empty">재고 데이터가 없습니다</td></tr>';

  const list = $("stock-moves");
  if (!list) return;
  const shown = (moves ?? []).slice(0, 8);
  const count = $("mv-count");
  if (count) count.textContent = moves?.length ? `${moves.length}건 기록됨` : "";
  list.innerHTML = shown.map((m) => `
    <div class="move">
      <span class="mv-t">${clock(m.updated_at)}</span>
      <span class="mv-chip ${esc(m.reason)}">${MOVE_LABEL[m.reason] ?? m.reason}</span>
      <span class="mv-what"><b>${esc(m.name)}</b> · ${esc(storeLabel(m.store_id))} <span class="mono-ref">${esc(m.ref)}</span></span>
      <span class="mv-qty ${m.qty > 0 ? "in" : "out"}">${m.qty > 0 ? "+" : ""}${m.qty}</span>
    </div>`).join("") || '<div class="empty">아직 재고 이동이 없습니다</div>';
}

function renderMetrics(cards) {
  $("metrics").innerHTML = cards.map((c) => `
    <div class="metric ${c.accent ? "accent" : ""} ${c.warn ? "warn" : ""}">
      <span class="label">${c.label}</span>
      <strong class="value"><span>${c.plain ? c.value : fmt(c.value)}</span><em>${c.unit}</em></strong>
      <span class="foot">${typeof c.foot === "object" ? "" : c.foot}</span>
    </div>`).join("");
}

function renderSysInfo(ov, health) {
  const el = $("sysinfo");
  if (!el) return;
  const rows = [
    ["네트워크", ov.network],
    ["LLM", health?.llm ?? "—"],
    ["저장소", health?.store ?? "postgres"],
    ["청구서", `${ov.totals.invoices}건`],
    ["협상", `${ov.totals.negotiations}건`],
    ["사람 개입", `${ov.totals.humanActions}회`],
  ];
  el.innerHTML = rows.map(([k, v]) => `<dt>${k}</dt><dd>${esc(v)}</dd>`).join("");
}

async function refresh() {
  if (!me) return;
  try {
    const [ov, ev, health] = await Promise.all([
      getJSON("/api/overview"),
      getJSON("/api/events?limit=60"),
      getJSON("/api/health").catch(() => null),
    ]);
    const view = role.scope(me, ov);
    lastView = view;
    currentNetwork = ov.network;

    $("network").textContent = ov.network;
    renderMetrics(role.metricsFor(me, view, lastWallets));

    if (me.kind === "store") {
      renderStores(view.stores, "my-store");
      $("invoices-title").textContent = "내 청구서";
      $("negotiations-title").textContent = "내 협상 기록";
      $("policy-title").textContent = "내 거래 정책";
      const w = $("wallets-title");
      if (w) w.textContent = "내 지갑";
    } else {
      renderStores(ov.stores, "stores");
    }

    renderInvoices(view.invoices, ov.network);

    // 재고 원장은 화면 권한대로 — 지점은 자기 것, 본사는 자기 창고, 관리자는 전부.
    // (P2P 심사 때 시스템이 지점 잉여를 검증하는 것과 화면 노출은 별개다)
    const asRows = (s) => (s.inventory ?? []).map((i) => ({ store: s.id, ...i }));
    const hqRows = (ov.hqInventory ?? []).map((i) => ({ store: "본사 창고", ...i }));
    const stockRows =
      me.kind === "store" ? (view.stores ?? []).flatMap(asRows)
      : me.kind === "hq" ? hqRows
      : [...hqRows, ...(ov.stores ?? []).flatMap(asRows)];
    const stockMoves =
      me.kind === "store" ? view.inventoryMoves
      : me.kind === "hq" ? (ov.inventoryMoves ?? []).filter((m) => m.store_id === "hq")
      : ov.inventoryMoves;
    renderInventory(stockRows, stockMoves);
    renderNegotiations(view.negotiations);
    renderTrades(view.trades);
    renderSchedules(view.invoices);
    renderApprovals(view.invoices);
    renderSysInfo(ov, health);

    // 펼쳐둔 행은 최신 과정으로 다시 채운다
    for (const id of expanded) loadTimeline(id, ov.network);

    const feedHtml = ev.events.map((e) => eventRow(e, false)).join("")
      || '<li class="empty" style="display:block">아직 활동이 없습니다</li>';
    for (const id of ["feed", "feed-side"]) {
      const el = $(id);
      if (el) el.innerHTML = feedHtml;
    }
    for (const id of ["event-total", "event-total-side"]) {
      const el = $(id);
      if (el) el.textContent = `${ev.total}건 기록됨`;
    }
  } catch (err) {
    console.error(err);
  }

  // 지갑 조회는 온체인 왕복이라 느리다 — 화면을 붙잡지 않고 도착하는 대로 채운다
  getJSON("/api/wallets").then((w) => {
    lastWallets = w.wallets;
    const shown = me.kind === "store" ? w.wallets.filter((x) => x.wallet === me.id) : w.wallets;
    renderWallets(shown);
    if (lastView) renderMetrics(role.metricsFor(me, lastView, lastWallets));
  }).catch(() => {});
}

function connect() {
  const beacon = $("beacon");
  const src = new EventSource("/api/stream");
  let hotTimer;

  src.addEventListener("ready", () => {
    beacon.className = "beacon on";
    beacon.innerHTML = "<i></i>실시간 연결됨";
  });

  src.addEventListener("activity", (e) => {
    const evt = JSON.parse(e.data);
    for (const id of ["feed", "feed-side"]) {
      const feed = $(id);
      if (!feed || feed.hidden) continue;
      feed.querySelector(".empty")?.remove();
      feed.insertAdjacentHTML("afterbegin", eventRow(evt, true));
      while (feed.children.length > 80) feed.lastElementChild.remove();
    }
    beacon.className = "beacon hot";
    beacon.innerHTML = "<i></i>에이전트 작동 중";
    clearTimeout(hotTimer);
    hotTimer = setTimeout(() => {
      beacon.className = "beacon on";
      beacon.innerHTML = "<i></i>실시간 연결됨";
    }, 3000);
  });

  src.addEventListener("refresh", () => refresh());
  src.onerror = () => {
    beacon.className = "beacon";
    beacon.innerHTML = "<i></i>재연결 중";
  };
}

// ── 어시스턴트 드로어 ─────────────────────────────────────────────
const fab = $("chat-fab");
const drawer = $("chat-drawer");
fab?.addEventListener("click", () => {
  drawer.hidden = false;
  fab.hidden = true;
  $("chat-input")?.focus();
});
$("chat-close")?.addEventListener("click", () => {
  drawer.hidden = true;
  fab.hidden = false;
});

// ── 로그인 게이트 ─────────────────────────────────────────────────
async function renderGate() {
  const { owners } = await getJSON("/api/policy/owners");
  const cards = [
    { id: "hq", ...role.ROLES.hq },
    ...owners.filter((o) => o.kind === "store").map((o) => ({
      id: o.id, kind: "store", label: o.name,
      caption: "내 청구서·잔액·정책",
      desc: "본사가 보낸 청구서를 검증하고, 여력이 될 때 결제합니다. 다른 지점의 내역은 보이지 않습니다.",
    })),
    { id: "admin", ...role.ROLES.admin },
  ];
  $("gate-list").innerHTML = cards.map((c) => `
    <button class="gate-btn ${c.kind}" data-id="${esc(c.id)}">
      <span class="gate-name">${esc(c.label)}</span>
      <span class="gate-caption">${esc(c.caption)}</span>
      <span class="gate-desc">${esc(c.desc)}</span>
    </button>`).join("");
  $("gate-list").querySelectorAll(".gate-btn").forEach((btn) =>
    btn.addEventListener("click", () => {
      role.set(btn.dataset.id);
      start();
    }),
  );
}

let streaming = false;

function start() {
  me = role.current();
  if (!me) {
    $("gate").hidden = false;
    $("app").hidden = true;
    if (fab) fab.hidden = true;
    renderGate().catch((e) => console.error(e));
    return;
  }

  $("gate").hidden = true;
  $("app").hidden = false;
  if (fab) fab.hidden = !drawer || !drawer.hidden;

  $("who-chip").textContent = me.label;
  $("who-chip").className = `who-chip ${me.kind}`;
  $("role-caption").textContent = me.caption;
  role.applyVisibility(me.kind);

  // 정책은 본사·가맹점만, 자기 것만 편집한다
  const policyHost = $("policy");
  if (policyHost && me.kind !== "admin") mountPolicy(policyHost, me.id);

  expanded.clear();
  timelines.clear();
  refresh();
  if (!streaming) { connect(); streaming = true; }
}

$("switch-role")?.addEventListener("click", () => {
  role.clear();
  start();
});

start();
setInterval(refresh, 15000);
