// Solply 대시보드 — SSE로 에이전트 활동을 실시간 반영한다.

import { mount as mountPolicy } from "./policy.js";

const $ = (id) => document.getElementById(id);
const seenInvoices = new Set();

const ACTION_LABEL = {
  "invoice.created": "청구서 발행",
  "invoice.adjusted": "청구 금액 조정",
  "delivery.verified": "검수 대조",
  "proposal.adjustment": "차감 제안",
  "proposal.deferral": "유예 제안",
  "proposal.reviewed": "제안 심사",
  "payment.executed": "결제 실행",
  "payment.verified": "수금 검증",
  "payment.mismatch": "검증 불일치",
  "payment.refused": "결제 거부",
  "payment.blocked_over_limit": "한도 초과 차단",
  "payment.needs_approval": "사람 승인 요청",
  "x402.payment_required": "x402 결제 요구",
  "x402.settled": "x402 정산 완료",
  "x402.verification_failed": "x402 검증 실패",
};

const STATUS_LABEL = {
  issued: "발행", paid: "결제됨", settled: "정산완료",
  disputed: "협의중", scheduled: "예약", refused: "거부",
  pending_approval: "승인 대기",
};

const fmt = (n) => Number(n ?? 0).toLocaleString("ko-KR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const short = (s, head = 6, tail = 4) => (!s ? "" : s.length <= head + tail + 1 ? s : `${s.slice(0, head)}…${s.slice(-tail)}`);
const clock = (iso) => { try { return new Date(iso).toLocaleTimeString("ko-KR", { hour12: false }); } catch { return "--:--:--"; } };

async function getJSON(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${url} → ${res.status}`);
  return res.json();
}

function renderStores(stores) {
  const el = $("stores");
  if (!stores.length) { el.innerHTML = '<div class="empty">가맹점 정보가 없습니다</div>'; return; }
  el.innerHTML = stores.map((s) => `
    <article class="store">
      <div class="top"><span class="name">${s.name}</span><span class="score">${s.creditScore}</span></div>
      <div class="id">${s.id}</div>
      <div class="gauge"><i style="width:${Math.min(100, s.creditScore)}%"></i></div>
      ${s.creditBasis ? `<div class="basis">정시납 ${s.creditBasis.onTime}${s.creditBasis.liveSettled ? ` <em>(+${s.creditBasis.liveSettled} 온체인)</em>` : ""} · 연체 ${s.creditBasis.late} · 분쟁 ${s.creditBasis.disputed}</div>` : ""}
      ${(s.inventory || []).length ? `<div class="stock">${s.inventory.map((it) => `<span class="chip ${it.qty < it.safety ? "low" : ""}">${it.name} ${it.qty}<i>/안전 ${it.safety}</i></span>`).join("")}</div>` : ""}
      <dl>
        <dt>미수금</dt><dd>${fmt(s.outstandingUsdc)}</dd>
        <dt>정산 완료</dt><dd>${fmt(s.settledUsdc)}</dd>
        <dt>자동결제 한도</dt><dd>${fmt(s.autoPayLimit)}</dd>
      </dl>
    </article>`).join("");
}

function renderInvoices(invoices) {
  const el = $("invoices");
  $("invoice-count").textContent = `${invoices.length}건`;
  if (!invoices.length) {
    el.innerHTML = '<tr><td colspan="5" class="empty">아직 청구서가 없습니다. 데모를 실행하면 여기에 나타납니다.</td></tr>';
    return;
  }
  el.innerHTML = invoices.map((inv) => {
    const isNew = seenInvoices.size && !seenInvoices.has(inv.id + inv.status);
    seenInvoices.add(inv.id + inv.status);
    const tx = inv.tx_sig
      ? `<a class="txlink" href="${inv.explorer || `https://explorer.solana.com/tx/${inv.tx_sig}?cluster=devnet`}" target="_blank" rel="noopener">${short(inv.tx_sig, 8, 6)}</a>`
      : '<span class="dash">—</span>';
    return `<tr class="${isNew ? "flash" : ""}">
      <td><span class="inv-id">${inv.id}</span></td>
      <td>${inv.store_id}</td>
      <td class="r">${fmt(inv.amount_usdc)}</td>
      <td><span class="tag ${inv.status}">${STATUS_LABEL[inv.status] ?? inv.status}</span></td>
      <td>${tx}</td>
    </tr>`;
  }).join("");
}

function renderNegotiations(negs) {
  const el = $("negotiations");
  if (!negs.length) {
    el.innerHTML = '<div class="empty">협상 기록이 없습니다</div>';
    return;
  }
  const KIND = { adjustment: "차감", deferral: "유예", installment: "분할" };
  const VERDICT = { accept: "수락", reject: "거절", counter: "역제안" };
  el.innerHTML = negs.map((n) => `
    <div class="neg">
      <span class="kind ${n.type}">${KIND[n.type] ?? n.type}</span>
      <div class="body">
        <div class="prop">${n.proposal ?? ""}</div>
        <div class="why"><b>본사 판단:</b> ${n.reasoning ?? ""}</div>
      </div>
      <span class="verdict ${n.decision}">${VERDICT[n.decision] ?? n.decision}</span>
    </div>`).join("");
}

function eventRow(evt, isNew) {
  const who = evt.actor === "hq-agent" ? "hq" : "store";
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
      <span class="who ${who}">${evt.actor.replace("-agent", "")}</span><span class="act">${label}</span>
      ${meta ? `<span class="meta">${meta}</span>` : ""}
    </span>
  </li>`;
}

function renderWallets(wallets) {
  $("wallets").innerHTML = wallets.map((w) => w.error
    ? `<div class="wallet"><div class="row"><span class="who">${w.wallet}</span></div><div class="err">결제 서비스 연결 안 됨</div></div>`
    : `<div class="wallet">
         <div class="row"><span class="who">${w.wallet}</span><span class="usdc">${fmt(w.usdc)} <small>USDC</small></span></div>
         <div class="row"><span class="addr">${short(w.address, 10, 6)}</span><span class="sol">${Number(w.sol).toFixed(3)} SOL</span></div>
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
      ? ` · <a class="txlink" href="https://explorer.solana.com/tx/${t.tx_sig}?cluster=devnet" target="_blank" rel="noopener">${short(t.tx_sig, 8, 6)}</a>`
      : "";
    return `
    <div class="neg">
      <span class="kind p2p">P2P</span>
      <div class="body">
        <div class="prop">${t.buyer_id} → ${t.seller_id} · ${t.name ?? t.sku} ×${t.qty} · ${fmt(t.price_usdc)} USDC</div>
        <div class="why"><b>상태:</b> ${STATUS[t.status] ?? t.status}${tx}</div>
      </div>
      <span class="verdict ${t.status === "confirmed" ? "accept" : t.status === "rejected" ? "reject" : "counter"}">${STATUS[t.status] ?? t.status}</span>
    </div>`;
  }).join("");
}


const reportBtn = document.getElementById("report-btn");
if (reportBtn) {
  reportBtn.addEventListener("click", async () => {
    reportBtn.disabled = true;
    reportBtn.textContent = "생성 중…";
    try {
      const r = await getJSON("/api/report");
      document.getElementById("report-text").textContent = r.report || "아직 요약할 정산 내역이 없습니다.";
    } catch (err) {
      document.getElementById("report-text").textContent = "리포트 생성에 실패했습니다.";
    } finally {
      reportBtn.disabled = false;
      reportBtn.textContent = "생성";
    }
  });
}


function renderSchedules(invoices) {
  const panel = document.getElementById("schedules-panel");
  const el = $("schedules");
  if (!panel || !el) return;
  const scheduled = (invoices || []).filter((inv) => inv.status === "scheduled");
  panel.style.display = scheduled.length ? "" : "none";
  el.innerHTML = scheduled.map((inv) => `
    <div class="neg">
      <span class="kind deferral">예약</span>
      <div class="body">
        <div class="prop">${inv.id} · ${inv.store_id} · ${fmt(inv.amount_usdc)} USDC${inv.installment ? ` · 분할 ${inv.installment}회차` : ""}</div>
        <div class="why">예약일이 오면 에이전트가 x402 왕복으로 결제합니다</div>
      </div>
      <span class="approve-actions">
        <button class="btn-approve" data-run="${inv.id}">지금 실행</button>
      </span>
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
  const panel = document.getElementById("approvals-panel");
  const el = $("approvals");
  if (!panel || !el) return;
  const pending = (invoices || []).filter((inv) => inv.status === "pending_approval");
  panel.style.display = pending.length ? "" : "none";
  el.innerHTML = pending.map((inv) => `
    <div class="neg">
      <span class="kind adjustment">승인</span>
      <div class="body">
        <div class="prop">${inv.id} · ${inv.store_id} · ${fmt(inv.amount_usdc)} USDC</div>
        <div class="why">자동결제 상한 초과 — 에이전트가 결제를 보류했습니다</div>
      </div>
      <span class="approve-actions">
        <button class="btn-approve" data-id="${inv.id}" data-decision="approve">승인</button>
        <button class="btn-reject" data-id="${inv.id}" data-decision="reject">반려</button>
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


async function refresh() {
  try {
    const [ov, ev] = await Promise.all([getJSON("/api/overview"), getJSON("/api/events?limit=60")]);
    $("network").textContent = ov.network;
    $("m-settled").textContent = fmt(ov.totals.settledUsdc);
    $("m-settled-count").textContent = `${ov.totals.settledCount}건`;
    $("m-outstanding").textContent = fmt(ov.totals.outstandingUsdc);
    $("m-outstanding-count").textContent = `${ov.totals.outstandingCount ?? ov.totals.invoices - ov.totals.settledCount}건`;
    $("m-negotiations").textContent = ov.totals.negotiations;
    $("m-human").textContent = ov.totals.humanActions;
    renderStores(ov.stores);
    renderInvoices(ov.invoices);
    renderNegotiations(ov.negotiations);
    renderTrades(ov.trades);
    renderSchedules(ov.invoices);
    renderApprovals(ov.invoices);
    $("event-total").textContent = `${ev.total}건 기록됨`;
    $("feed").innerHTML = ev.events.map((e) => eventRow(e, false)).join("")
      || '<li class="empty" style="display:block">아직 활동이 없습니다</li>';
  } catch (err) {
    console.error(err);
  }
  getJSON("/api/wallets").then((w) => renderWallets(w.wallets)).catch(() => {});
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
    const feed = $("feed");
    const empty = feed.querySelector(".empty");
    if (empty) empty.remove();
    feed.insertAdjacentHTML("afterbegin", eventRow(evt, true));
    while (feed.children.length > 80) feed.lastElementChild.remove();

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

refresh();
connect();
mountPolicy(document.getElementById("policy"));
setInterval(refresh, 15000);
