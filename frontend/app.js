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
let viewDay = null;          // 보고 있는 날짜 (null = 오늘). 정산은 날짜 단위 업무다
let dayMeta = { today: null, firstDay: null };

// 날짜 계산은 시간대를 타지 않게 UTC로만 한다 — 로컬로 파싱하고 UTC로 출력하면
// KST 브라우저에서 하루가 밀린다 (오늘에서 뒤로 가면 어제를 건너뛴다)
const shiftDay = (day, n) => {
  const d = new Date(`${day}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
};
const dayParam = () => (viewDay ? `day=${viewDay}` : "");
const timelines = new Map();  // id → 응답 캐시

// 행위 라벨은 API(`overview.actionLabels`)가 내려준다 — 백엔드가 단일 출처다.
// 새 행위를 추가하고 라벨을 빼먹으면 백엔드 테스트가 잡는다.
let ACTION_LABEL = {};

// 상태 라벨은 API(`overview.statusLabels`)가 내려준다 — 백엔드와 사본이 갈라지지 않게.
// 아래는 첫 그림이 오기 전/응답이 없을 때만 쓰는 대비값이다.
// 직거래 상태 라벨도 API가 내려준다 (`overview.tradeStatusLabels`)
let TRADE_STATUS_LABEL = {
  proposed: "제안됨", accepted: "수락", approved: "본사 승인",
  confirmed: "확정", rejected: "거절",
};
let STATUS_LABEL = {
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

// ── 쪽 넘기기 ─────────────────────────────────────────────────────
// 하루치라도 청구서·직거래는 수십~수백 건이 된다. 한 화면에 30건씩 보여주고 넘긴다.
const PAGE_SIZE = 15;
const page = { invoices: 0, trades: 0, negs: 0 };

function paginate(key, items, size = PAGE_SIZE) {
  const pages = Math.max(1, Math.ceil(items.length / size));
  if (page[key] > pages - 1) page[key] = pages - 1;  // 목록이 줄면 마지막 쪽으로 당긴다
  const from = page[key] * size;
  return { rows: items.slice(from, from + size), from, pages, total: items.length };
}

/** 쪽 표시 + 이동 버튼. 한 쪽에 다 들어가면 건수만 적는다. */
function pagerHtml(key, cut, tail = "") {
  const suffix = tail ? ` · ${tail}` : "";
  if (cut.pages <= 1) return `${cut.total}건${suffix}`;
  const to = cut.from + cut.rows.length;
  return `${cut.total}건 중 ${cut.from + 1}–${to}${suffix}
    <span class="pager">
      <button class="daybtn" data-page="${key}:-1" ${page[key] === 0 ? "disabled" : ""}
              aria-label="이전 쪽">‹</button>
      <b>${page[key] + 1}/${cut.pages}</b>
      <button class="daybtn" data-page="${key}:1" ${page[key] >= cut.pages - 1 ? "disabled" : ""}
              aria-label="다음 쪽">›</button>
    </span>`;
}

function bindPager(scope) {
  scope.querySelectorAll("button[data-page]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const [key, step] = btn.dataset.page.split(":");
      page[key] = Math.max(0, page[key] + Number(step));
      refresh();
    });
  });
}

// ── 청구서 표 ─────────────────────────────────────────────────────
/** 분할 가족(부모+자식)을 한 덩어리로 묶는다 — 쪽이 넘어가도 같은 이야기가 쪼개지지 않게. */
function invoiceFamilies(invoices) {
  const byParent = new Map();
  for (const inv of invoices) {
    if (!inv.parent_id) continue;
    if (!byParent.has(inv.parent_id)) byParent.set(inv.parent_id, []);
    byParent.get(inv.parent_id).push(inv);
  }
  const families = [];
  for (const inv of invoices) {
    if (inv.parent_id && invoices.some((x) => x.id === inv.parent_id)) continue;
    const kids = (byParent.get(inv.id) ?? []).sort((a, b) => a.id.localeCompare(b.id));
    families.push([{ inv, child: false }, ...kids.map((kid) => ({ inv: kid, child: true }))]);
  }
  return families;
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
  const head = $("invoice-count");
  if (!invoices.length) {
    head.textContent = "이 날은 청구서가 없습니다";
    el.innerHTML = '<tr><td colspan="5" class="empty">이 날짜에는 청구서가 없습니다. 날짜를 옮기거나 데모를 실행해 보세요.</td></tr>';
    return;
  }
  const cut = paginate("invoices", invoiceFamilies(invoices));
  head.innerHTML = pagerHtml("invoices", cut, "행을 누르면 협상 과정이 펼쳐집니다");
  bindPager(head);

  // 첫 그림에는 강조를 넣지 않는다 — 전부 새것이라 전부 깜빡이면 아무것도 강조되지 않는다
  const firstPaint = seenInvoices.size === 0;
  el.innerHTML = cut.rows.flat()
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
function renderNegotiations(negs, invoices = []) {
  const el = $("negotiations");
  const head = $("negotiations-count");
  if (!negs.length) {
    if (head) head.textContent = "에이전트가 제안하고 심사한 결과";
    el.innerHTML = '<div class="empty">협상 기록이 없습니다</div>';
    return;
  }
  // 유예 계열은 청구서별 "대화 스레드"로 — 다회 왕복이 말풍선으로 보인다.
  const DEFER = new Set(["deferral", "counter_response", "counter_settle"]);
  const threads = new Map();
  const others = [];
  for (const n of negs) {
    if (DEFER.has(n.type) && n.invoice_id) {
      if (!threads.has(n.invoice_id)) threads.set(n.invoice_id, []);
      threads.get(n.invoice_id).push(n);
    } else others.push(n);
  }
  const bubble = (side, title, body, tone) => `
    <div class="msg ${side}">
      <span class="who3">${side === "store" ? "지점" : "본사"}</span>
      <div class="bubble ${tone}"><b>${esc(title)}</b>${body ? `<span>${esc(body)}</span>` : ""}</div>
    </div>`;
  const threadHtml = (inv, rows) => {
    rows.sort((a, b) => (a.updated_at ?? "").localeCompare(b.updated_at ?? ""));
    const invDoc = invoices.find((i) => i.id === inv);
    const stTone = !invDoc ? ""
      : ["scheduled", "split", "settled"].includes(invDoc.status) ? "stat-good"
      : ["pending_approval", "refused"].includes(invDoc.status) ? "stat-risk" : "";
    const chip = invDoc
      ? `<span class="chip ${stTone}">${esc(STATUS_LABEL[invDoc.status] ?? invDoc.status)}</span>` : "";
    const msgs = [];
    for (const n of rows) {
      if (n.type === "deferral") {
        msgs.push(bubble("store", n.proposal ?? "납부 유예 요청", "", "ask"));
        const [title, tone] =
          n.decision === "accept" ? ["유예 수락 — 예약 전환", "good"]
          : n.decision === "counter" ? ["분할 역제안 — 지점 응답 대기", "warn"]
          : ["유예 거절", "risk"];
        msgs.push(bubble("hq", title, n.reasoning ?? "", tone));
      } else if (n.type === "counter_response") {
        const [title, tone] =
          n.decision === "accept" ? ["역제안 수락", "good"]
          : n.decision === "counter"
            ? [`수정안 — 지금 ${fmt(n.terms?.first_usdc ?? 0)} USDC 선납`, "warn"]
          : ["결렬 — 분할도 감당 불가", "risk"];
        msgs.push(bubble("store", title, n.reasoning ?? "", tone));
      } else {
        const [title, tone] =
          n.decision === "accept" ? ["수정안 수용 — 분할 청구서 집행", "good"]
          : n.proposal === "협상 결렬" ? ["결렬 — 사람 결정 대기", "risk"]
          : ["수정안 거절 — 사람 결정 대기", "risk"];
        msgs.push(bubble("hq", title, n.reasoning ?? "", tone));
      }
    }
    return `<div class="thread">
      <div class="thread-head">${esc(inv)} · A2A 협상 (message/send ${rows.length + 1}통) ${chip}</div>
      ${msgs.join("")}
    </div>`;
  };
  const rowHtml = (n) => `
    <div class="row">
      <span class="kind">${KIND_LABEL[n.type] ?? esc(n.type)}</span>
      <div class="body">
        <div class="head">${esc(n.proposal ?? "")}</div>
        <div class="why"><b>본사 판단:</b> ${esc(n.reasoning ?? "")}</div>
      </div>
      <span class="verdict ${esc(n.decision)}">${VERDICT_LABEL[n.decision] ?? esc(n.decision)}</span>
    </div>`;

  // 스레드는 부피가 크다 — 한 쪽에 6덩이씩만
  const units = [
    ...[...threads.entries()].map(([inv, rows]) => ({ thread: [inv, rows] })),
    ...others.map((n) => ({ row: n })),
  ];
  const cut = paginate("negs", units, 6);
  if (head) {
    head.innerHTML = pagerHtml("negs", cut);
    bindPager(head);
  }
  el.innerHTML = cut.rows
    .map((u) => (u.thread ? threadHtml(u.thread[0], u.thread[1]) : rowHtml(u.row)))
    .join("");
}

function renderDataStore(ov) {
  const el = $("datastore");
  if (!el) return;
  const rev = ov.hqRevenue ?? {};
  const ds = ov.dataStore ?? {};
  const sales = ds.recentSales ?? [];
  el.innerHTML = `
    <div class="ds-stats">
      <div><b>${fmt(rev.data_sales_usdc ?? 0)}</b><span>데이터 매출 · ${rev.data_sales_count ?? 0}건</span></div>
      <div><b>${fmt(rev.royalty_usdc ?? 0)}</b><span>로열티 수익 · ${rev.royalty_count ?? 0}건</span></div>
      <div><b>${fmt(ds.priceUsdc ?? 0)}</b><span>지수 1건 가격 (USDC)</span></div>
    </div>
    <div class="ds-note">상품 2종 — <b>체결가 지수</b>·<b>수요 지수</b>. 온체인 정산이 확인된 체결만
      비식별 집계하며, 에이전트도 같은 상점에서 판단 재료를 사 간다 (자급 순환).</div>
    ${sales.length ? sales.map((o) => `
      <div class="row">
        <span class="kind">판매</span>
        <div class="body">
          <div class="head">${esc(o.product)} · ${esc(o.sku)} · ${fmt(o.price_usdc)} USDC</div>
          <div class="why">주문 ${esc(o.id)}${o.tx_sig ? ` · <a class="txlink" href="${explorerUrl(o.tx_sig, currentNetwork)}" target="_blank" rel="noopener">${short(o.tx_sig, 8, 6)}</a>` : ""}</div>
        </div>
        <span class="verdict accept">이행</span>
      </div>`).join("") : '<div class="empty">아직 판매 기록이 없습니다</div>'}`;
}

// ── 오늘의 자금 흐름 — 곡선 엣지·알약 라벨·흐르는 점선 (공용 헬퍼) ──
function round2(n) { return Math.round(n * 100) / 100; }
function flowEdge(x1, y1, x2, y2, cls) {
  const dx = Math.abs(x2 - x1) * 0.5;
  const c1 = x1 + (x2 > x1 ? dx : -dx);
  const c2 = x2 - (x2 > x1 ? dx : -dx);
  const d = `M ${x1} ${y1} C ${c1} ${y1}, ${c2} ${y2}, ${x2} ${y2}`;
  return `<path d="${d}" class="fl-path ${cls}" marker-end="url(#fl-${cls})"/>`
    + (cls === "dim" ? "" : `<path d="${d}" class="fl-anim ${cls}"/>`);
}
function flowPill(cx, cy, cls, text) {
  const w = [...text].reduce(
    (a, ch) => a + (/[가-힣]/.test(ch) ? 11 : /[0-9.()]/.test(ch) ? 6.6 : 6), 0) + 18;
  return `<g><rect x="${cx - w / 2}" y="${cy - 11}" width="${w}" height="22" rx="11"
    class="fl-pill ${cls}"/><text x="${cx}" y="${cy + 4}" class="fl-ptext ${cls}">${text}</text></g>`;
}
const FLOW_DEFS = `<defs>
  <marker id="fl-in" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 Z" class="fl-head in"/></marker>
  <marker id="fl-out" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 Z" class="fl-head out"/></marker>
  <marker id="fl-dim" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 Z" class="fl-head dim"/></marker>
  <marker id="fl-p2p" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 Z" class="fl-head p2p"/></marker>
  <marker id="fl-p2pr" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto-start-reverse"><path d="M0,0 L8,4 L0,8 Z" class="fl-head p2p"/></marker>
</defs>`;

// 지점 화면 — 내 가게가 한가운데. 돈이 나를 중심으로 돈다.
function storeFlowSvg(ov) {
  const flows = ov.flows ?? {};
  const mine = (ov.stores ?? []).find((s) => s.id === me.id) ?? {};
  const sell = Number(mine.settledUsdc ?? 0);
  const back = Number((flows.card ?? {})[me.id] ?? 0);
  const guest = Number((flows.guest ?? {})[me.id] ?? 0);
  const quotes = Number((flows.quotes ?? {})[me.id] ?? 0);
  const trades = (ov.trades ?? []).filter((t) => t.status === "confirmed");
  const gc = guest ? "in" : "dim", bc = back ? "in" : "dim";
  const sc = sell ? "out" : "dim", qc = quotes ? "out" : "dim";

  // 이웃 지점별 매입·판매 — 업장끼리 사고판 것이 짝별로 보인다
  const neighbors = (ov.stores ?? []).filter((s) => s.id !== me.id).slice(0, 2);
  const nbox = neighbors.map((n, k) => {
    const bought = trades.filter((t) => t.buyer_id === me.id && t.seller_id === n.id)
      .reduce((a, t) => a + Number(t.price_usdc ?? 0), 0);
    const soldTo = trades.filter((t) => t.seller_id === me.id && t.buyer_id === n.id)
      .reduce((a, t) => a + Number(t.price_usdc ?? 0), 0);
    const y = k === 0 ? 74 : 246;
    const meY = k === 0 ? 150 : 230;
    // 연결선은 화살촉 없이 — 방향은 매입·판매 라벨이 말한다. 알약은 선 위로 띄운다.
    const d = `M 572 ${meY} C 645 ${meY}, 645 ${y}, 718 ${y}`;
    return `
      <rect x="720" y="${y - 32}" width="156" height="64" rx="12" class="fl-box"/>
      <text x="798" y="${y - 6}" text-anchor="middle" class="fl-name">${esc(n.name ?? n.id)}</text>
      <text x="798" y="${y + 15}" text-anchor="middle" class="fl-cap">${esc(n.id)}</text>
      <path d="${d}" class="fl-line p2p"/>
      ${flowPill(645, (meY + y) / 2 - 20, "p2p", `매입 ${fmt(bought)} · 판매 ${fmt(soldTo)}`)}`;
  }).join("");

  return `
  <svg viewBox="0 0 900 320" role="img" aria-label="오늘 내 지점을 중심으로 오간 온체인 자금 흐름">
    ${FLOW_DEFS}
    <rect x="70" y="16" width="160" height="64" rx="12" class="fl-box"/>
    <text x="150" y="42" text-anchor="middle" class="fl-name">손님 (guest)</text>
    <text x="150" y="63" text-anchor="middle" class="fl-cap">/shop에서 내 가게 구매</text>
    <rect x="60" y="130" width="180" height="120" rx="12" class="fl-box"/>
    <text x="150" y="158" text-anchor="middle" class="fl-name">본사 정산팀</text>
    <text x="150" y="177" text-anchor="middle" class="fl-cap">hq</text>
    <line x1="80" y1="196" x2="220" y2="196" class="fl-sep"/>
    <text x="150" y="216" text-anchor="middle" class="fl-cap">매출은 금고 적립 후</text>
    <text x="150" y="234" text-anchor="middle" class="fl-cap">로열티 공제하고 지급</text>
    ${flowEdge(150, 80, 150, 128, gc)}
    ${flowPill(150, 104, gc, `손님 매출 ${fmt(guest)}`)}
    <rect x="390" y="130" width="180" height="120" rx="14" class="fl-box fl-hq"/>
    <text x="480" y="172" text-anchor="middle" class="fl-name">${esc(mine.name ?? me.id)}</text>
    <text x="480" y="193" text-anchor="middle" class="fl-cap">${esc(me.id)} — 내 지점</text>
    <text x="480" y="222" text-anchor="middle" class="fl-cap">신용점수 ${mine.creditScore ?? "—"}</text>
    ${flowEdge(240, 165, 388, 165, bc)}
    ${flowPill(314, 152, bc, `카드정산 ${fmt(back)}`)}
    ${flowEdge(390, 210, 242, 210, sc)}
    ${flowPill(316, 224, sc, `물대 ${fmt(sell)}`)}
    <rect x="390" y="16" width="180" height="64" rx="12" class="fl-box"/>
    <text x="480" y="42" text-anchor="middle" class="fl-name">데이터 상점</text>
    <text x="480" y="63" text-anchor="middle" class="fl-cap">시세·수요 지수 — x402 구매</text>
    ${flowEdge(480, 128, 480, 82, qc)}
    ${flowPill(412, 105, qc, `시세 구입 ${fmt(quotes)}`)}
    ${nbox}
    <text x="24" y="308" class="fl-cap">청록 점선은 이웃 지점과의 P2P 직거래 — 초록 유입 · 파랑 유출 (내 지갑 기준)</text>
    <text x="876" y="308" text-anchor="end" class="fl-cap">모든 흐름은 ${esc(ov.network ?? "devnet")} 온체인 USDC 이체</text>
  </svg>`;
}

function renderFlows(ov) {
  const el = $("flowmap");
  if (!el || el.hidden) return;
  if (me?.kind === "store") {
    el.innerHTML = storeFlowSvg(ov);
    return;
  }
  const flows = ov.flows ?? {};
  const card = flows.card ?? {};
  const stores = ov.stores ?? [];
  const p2p = (ov.trades ?? []).filter((t) => t.status === "confirmed");
  const p2pSum = p2p.reduce((a, t) => a + Number(t.price_usdc ?? 0), 0);

  const cy = [70, 180, 290];
  const inPort = [120, 180, 240];
  const outPort = [136, 196, 256];
  const storeBits = stores.slice(0, 3).map((s, i) => {
    const y = cy[i];
    const sell = Number(s.settledUsdc ?? 0);
    const back = Number(card[s.id] ?? 0);
    const sc = sell ? "in" : "dim", bc = back ? "out" : "dim";
    const inMidY = (y - 13 + inPort[i]) / 2, outMidY = (y + 13 + outPort[i]) / 2;
    return `
      <rect x="24" y="${y - 32}" width="160" height="64" rx="12" class="fl-box"/>
      <text x="104" y="${y - 6}" text-anchor="middle" class="fl-name">${esc(s.name ?? s.id)}</text>
      <text x="104" y="${y + 15}" text-anchor="middle" class="fl-cap">${esc(s.id)}</text>
      ${flowEdge(184, y - 13, 398, inPort[i], sc)}
      ${flowEdge(400, outPort[i], 186, y + 13, bc)}
      ${flowPill(292, inMidY - 3, sc, `물대 ${fmt(sell)}`)}
      ${flowPill(292, outMidY + 3, bc, `카드정산 ${fmt(back)}`)}`;
  }).join("");

  const pairSum = (a, b) => p2p
    .filter((t) => (t.buyer_id === a && t.seller_id === b) || (t.buyer_id === b && t.seller_id === a))
    .reduce((s2, t) => s2 + Number(t.price_usdc ?? 0), 0);
  const p2pSeg = (y1, y2, label) => `<line x1="104" y1="${y1}" x2="104" y2="${y2}"
    class="fl-line p2p" marker-start="url(#fl-p2pr)" marker-end="url(#fl-p2p)"/>
    ${label ? flowPill(104, (y1 + y2) / 2, "p2p", label) : ""}`;

  const royalty = Number(flows.royaltyUsdc ?? 0);
  const dataUsdc = Number(flows.dataUsdc ?? 0);
  const guestUsdc = Number(flows.guestUsdc ?? 0);
  const quoteSum = Object.values(flows.quotes ?? {}).reduce((a, v) => a + Number(v ?? 0), 0);
  const external = Math.max(0, round2(dataUsdc - quoteSum));
  const dc = dataUsdc ? "in" : "dim";
  const gc = guestUsdc ? "in" : "dim";
  el.innerHTML = `
  <svg viewBox="0 0 900 360" role="img" aria-label="오늘 본사와 지점 사이를 오간 온체인 자금 흐름">
    ${FLOW_DEFS}
    ${storeBits}
    ${p2p.length && stores.length >= 3
      ? p2pSeg(cy[0] + 40, cy[1] - 40, `${fmt(pairSum(stores[0].id, stores[1].id))}`)
        + p2pSeg(cy[1] + 40, cy[2] - 40, `${fmt(pairSum(stores[1].id, stores[2].id))}`)
      : ""}
    <rect x="400" y="90" width="180" height="180" rx="14" class="fl-box fl-hq"/>
    <text x="490" y="118" text-anchor="middle" class="fl-name">본사 정산팀</text>
    <text x="490" y="137" text-anchor="middle" class="fl-cap">hq</text>
    <text x="490" y="182" text-anchor="middle" class="fl-total">${fmt(ov.totals?.settledUsdc ?? 0)}</text>
    <text x="490" y="202" text-anchor="middle" class="fl-cap">오늘 정산 완료 (USDC)</text>
    <line x1="420" y1="219" x2="560" y2="219" class="fl-sep"/>
    <text x="490" y="240" text-anchor="middle" class="fl-gain ${royalty ? "" : "mute"}">로열티 원천징수 +${fmt(royalty)}</text>
    <text x="490" y="259" text-anchor="middle" class="fl-gain ${dataUsdc ? "" : "mute"}">데이터 판매 +${fmt(dataUsdc)}</text>
    <rect x="716" y="38" width="160" height="64" rx="12" class="fl-box"/>
    <text x="796" y="64" text-anchor="middle" class="fl-name">데이터 상점 구매자</text>
    <text x="796" y="85" text-anchor="middle" class="fl-cap">자급 ${fmt(quoteSum)} · 외부 ${fmt(external)}</text>
    <path d="M 582 100 C 640 100, 660 52, 714 52" class="fl-line p2p" marker-end="url(#fl-p2p)"/>
    ${flowPill(648, 60, "p2p", `지수 인도 ${flows.dataCount ?? 0}건`)}
    ${flowEdge(716, 86, 582, 132, dc)}
    ${flowPill(650, 116, dc, `지수 판매 ${fmt(dataUsdc)}`)}
    <rect x="716" y="240" width="160" height="64" rx="12" class="fl-box"/>
    <text x="796" y="266" text-anchor="middle" class="fl-name">손님 (guest)</text>
    <text x="796" y="287" text-anchor="middle" class="fl-cap">/shop 방문 구매</text>
    ${flowEdge(716, 272, 582, 240, gc)}
    ${flowPill(650, 268, gc, `손님 매출 ${fmt(guestUsdc)}`)}
    <text x="24" y="352" class="fl-cap">점선은 지점 ⇄ 지점 직거래(P2P) — 오늘 ${p2p.length}건 · ${fmt(p2pSum)} USDC</text>
    <text x="876" y="352" text-anchor="end" class="fl-cap">모든 흐름은 ${esc(ov.network ?? "devnet")} 온체인 USDC 이체</text>
  </svg>`;
}

function renderTrades(trades) {
  const el = $("trades");
  if (!el) return;
  const head = $("trade-count");
  if (!trades || !trades.length) {
    if (head) head.textContent = "이 날은 지점 간 직거래가 없습니다";
    el.innerHTML = '<div class="empty">이 날짜에는 지점 간 직거래가 없습니다</div>';
    return;
  }
  const cut = paginate("trades", trades);
  if (head) {
    head.innerHTML = pagerHtml("trades", cut, "재고 부족분을 옆 지점에서 조달 — 시세 지수 근거 · x402 결제");
    bindPager(head);
  }
  const STATUS = TRADE_STATUS_LABEL;
  // 고정 설명은 패널 머리로 올리고, 행에는 변하는 정보만 남긴다 — 30행이 같은 문장을 반복하면 소음이다
  el.innerHTML = cut.rows.map((t) => {
    const sig = t.release_tx ?? t.refund_tx ?? t.tx_sig;  // 종결 tx가 있으면 그것부터
    const tx = sig
      ? ` <a class="txlink" href="${explorerUrl(sig, currentNetwork)}" target="_blank" rel="noopener" title="온체인 트랜잭션">${short(sig, 6, 4)}↗</a>`
      : "";
    const tone = t.status === "confirmed" ? "accept"
      : ["rejected", "refunded"].includes(t.status) ? "reject" : "counter";
    const m = /시세:\s*(\S+)\s+([\d.]+)\s*USD(?:.*?대비\s*([+\-−]?[\d.]+%))?/.exec(t.basis ?? "");
    const basis = m ? `시세 ${m[1]} ${m[2]}${m[3] ? ` · ${m[3]}` : ""}` : "";
    return `
    <div class="row slim">
      <span class="kind">P2P</span>
      <div class="body">
        <div class="head">${esc(t.buyer_id)} ← ${esc(t.seller_id)} · ${esc(t.name ?? t.sku)} ×${t.qty} ·
          <b>${fmt(t.price_usdc)}</b> USDC${basis ? ` <span class="basis">${esc(basis)}</span>` : ""}${tx}</div>
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
  const pending = (invoices || []).filter((inv) =>
    inv.status === "pending_approval" ||
    (inv.status === "refused" && !inv.human_reviewed));
  panel.style.display = pending.length ? "" : "none";
  el.innerHTML = pending.map((inv) => inv.status === "pending_approval" ? `
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
    </div>` : `
    <div class="row">
      <span class="kind">거부 검토</span>
      <div class="body">
        <div class="head">${esc(inv.id)} · ${esc(inv.store_id)} · ${fmt(inv.amount_usdc)} USDC</div>
        <div class="why">발주 기록에 없어 에이전트가 결제를 거부했습니다 — 재발행하거나 거부를 확정할 사람의 몫입니다</div>
      </div>
      <span class="actions">
        <button class="btn btn-approve" data-id="${esc(inv.id)}" data-decision="approve">재발행</button>
        <button class="btn btn-reject" data-id="${esc(inv.id)}" data-decision="reject">거부 확정</button>
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
  else if (p.trade_id) meta = p.trade_id;
  if (p.tx) meta += ` · ${short(p.tx, 10, 6)}`;
  // 같은 뜻을 두 이름으로 보내는 곳이 있다 (amount / amount_usdc / price_usdc)
  const amt = p.amount ?? p.amount_usdc ?? p.price_usdc;
  if (amt != null) meta += ` · ${fmt(amt)} USDC`;
  if (p.new_amount != null) meta += ` → ${fmt(p.new_amount)} USDC`;
  if (p.price_usd != null) meta += ` · ${p.symbol ?? p.sku} ${p.price_usd} ${p.source === "solply-index" ? "USDC" : "USD"}`;
  if (p.receipt_ref) meta += ` · 영수증 ${short(p.receipt_ref, 8, 6)}`;
  if (evt.action === "delivery.verified") meta += p.match ? " · 일치" : ` · 불일치 ${p.discrepancies?.length ?? 0}건`;
  if (p.sku && p.qty != null) meta += ` · ${esc(p.sku)} ${p.qty > 0 ? "+" : ""}${p.qty}`;
  if (p.reason) meta += ` · ${p.reason}`;
  return `<li class="${isNew ? "new" : ""}">
    <span class="t">${clock(evt.ts)}</span>
    <span class="what">
      <span class="who">${esc(evt.actor.replace("-agent", ""))}</span><span class="act ${toneOf(evt)}">${esc(label)}</span>
      ${meta ? `<span class="meta">${esc(meta)}</span>` : ""}
      ${p.tx || p.explorer ? `<a class="txlink" target="_blank" rel="noopener" href="${p.explorer ?? explorerUrl(p.tx, currentNetwork)}">체인↗</a>` : ""}
    </span>
  </li>`;
}

function renderWallets(wallets) {
  $("wallets").innerHTML = wallets.map((w) => w.error
    ? `<div class="wallet"><div class="line"><span class="who2">${esc(w.wallet)}</span></div><div class="err">결제 서비스 연결 안 됨</div></div>`
    : `<div class="wallet">
         <div class="line"><span class="who2">${esc(w.wallet)}</span><span class="usdc">${fmt(w.usdc)} <small>USDC</small></span></div>
         <div class="line"><span class="addr">${short(w.address, 10, 6)}</span><span class="sol">${Number(w.sol).toFixed(3)} SOL</span></div>
         ${w.pending_settlement_usdc > 0 ? `<div class="line"><span class="addr">카드정산 대기</span><span class="sol">+${fmt(w.pending_settlement_usdc)} USDC</span></div>` : ""}
         ${w.wallet !== "hq" ? `<div class="line"><span class="addr">⚡ Gasless</span><span class="sol">수수료 본사 대납</span></div>` : ""}
       </div>`).join("");
}

// ── 무대 트리거 — 발표 중 "지금 실시간으로" ─────────────────────────
async function stageCall(btn, url, runningText) {
  const out = $("stage-result");
  btn.disabled = true;
  const original = btn.textContent;
  btn.textContent = runningText;
  try {
    const res = await fetch(url, { method: "POST" });
    const body = await res.json().catch(() => ({}));
    out.textContent = res.ok
      ? `완료 — ${body.invoice_id ? `${body.invoice_id} → ${body.outcome}` : "틱 실행됨"} (협상 기록에 표시)`
      : `실패 — ${body.detail ?? res.status}`;
  } catch (err) {
    out.textContent = `오류 — ${err}`;
  } finally {
    btn.disabled = false;
    btn.textContent = original;
    refresh();
  }
}
$("stage-negotiate")?.addEventListener("click", (e) =>
  stageCall(e.target, "/api/demo/negotiate", "협상 진행 중…"));
$("stage-tick")?.addEventListener("click", (e) =>
  stageCall(e.target, "/api/ticks/run", "틱 실행 중…"));

// ── 역할별 패널 순서 — 각 역할의 이야기 순서대로 배치한다 ──────────
const MAIN_ORDER = {
  hq: ["p-stores", "p-negotiations", "approvals-panel", "schedules-panel",
       "p-datastore", "p-invoices", "p-inventory", "p-trades", "p-feedwide", "p-mystore"],
  store: ["p-mystore", "approvals-panel", "schedules-panel", "p-invoices",
          "p-negotiations", "p-inventory", "p-trades", "p-stores", "p-datastore", "p-feedwide"],
  admin: ["p-feedwide", "p-datastore", "p-invoices", "p-inventory",
          "p-stores", "p-mystore", "approvals-panel", "schedules-panel", "p-negotiations", "p-trades"],
};
const SIDE_ORDER = {
  hq: ["s-stage", "s-report", "s-feedside", "s-policy", "s-system", "s-wallets"],
  store: ["s-wallets", "s-policy", "s-feedside", "s-report", "s-stage", "s-system"],
  admin: ["s-stage", "s-system", "s-wallets", "s-policy", "s-report", "s-feedside"],
};
function orderPanels(kind) {
  const move = (ids, parent) => {
    if (!parent) return;
    for (const id of ids) {
      const el = $(id);
      if (el) parent.appendChild(el);
    }
  };
  move(MAIN_ORDER[kind] ?? [], document.querySelector(".col-main"));
  move(SIDE_ORDER[kind] ?? [], document.querySelector(".col-side"));
}

// ── 자금 흐름 접기/펼치기 — 기본은 접힘, 선택은 기억한다 ──────────
function applyFlowOpen() {
  const open = localStorage.getItem("solply.flowOpen") === "1";
  const map = $("flowmap");
  if (map) {
    map.hidden = !open;
    map.closest(".flow-panel")?.classList.toggle("closed", !open);
  }
  const btn = $("flow-toggle");
  if (btn) btn.textContent = open ? "접기" : "펼치기";
}
$("flow-toggle")?.addEventListener("click", () => {
  const open = localStorage.getItem("solply.flowOpen") === "1";
  localStorage.setItem("solply.flowOpen", open ? "0" : "1");
  applyFlowOpen();
  refresh();
});
applyFlowOpen();

// ── 리포트 · 어시스턴트 ───────────────────────────────────────────
function openModal(title, body) {
  $("modal-title").textContent = title;
  $("modal-body").textContent = body;
  $("modal-backdrop").hidden = false;
}
function closeModal() {
  $("modal-backdrop").hidden = true;
}
$("modal-close")?.addEventListener("click", closeModal);
$("modal-backdrop")?.addEventListener("click", (e) => {
  if (e.target === e.currentTarget) closeModal();
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") closeModal();
});

const reportBtn = $("report-btn");
if (reportBtn) {
  reportBtn.addEventListener("click", async () => {
    reportBtn.disabled = true;
    reportBtn.textContent = "생성 중…";
    openModal("정산 리포트", "요약을 작성하고 있습니다…");
    try {
      const r = await getJSON("/api/report");
      $("modal-body").textContent = r.report || "아직 요약할 정산 내역이 없습니다.";
    } catch {
      $("modal-body").textContent = "리포트 생성에 실패했습니다. 잠시 뒤 다시 시도해 주세요.";
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
  $("chat-chips")?.addEventListener("click", (e) => {
    const question = e.target.dataset?.q;
    if (!question) return;
    input.value = question;
    chatForm.requestSubmit();
  });
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
// 이동 사유 라벨도 API(`overview.moveLabels`)가 내려준다
let MOVE_LABEL = {};
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

  const multi = new Set(rows.map((r) => r.store)).size > 1;
  let lastStore = null;
  table.innerHTML = rows.length
    ? rows.map((r) => `${multi && r.store !== lastStore
        ? `<tr class="stock-group"><td colspan="5">${esc((lastStore = r.store))}</td></tr>` : ""}<tr>
        <td class="col-store">${multi ? "" : esc(r.store)}</td>
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
  const cardLink = (id) =>
    `<a href="/a2a/${id}/.well-known/agent-card.json" target="_blank" rel="noopener">${id}</a>`;
  el.innerHTML = rows.map(([k, v]) => `<dt>${k}</dt><dd>${esc(v)}</dd>`).join("")
    + `<dt>A2A 명함</dt><dd class="cards">${["hq", "store-a", "store-b", "store-c"].map(cardLink).join(" · ")}</dd>`;
}


// ── 날짜 이동 ─────────────────────────────────────────────────────
// 오늘이 기본이고, 과거로 넘기면 그날의 청구·협상·직거래·로그만 보인다.
// (미수금은 날짜와 무관하게 계속 보인다 — 어제 안 낸 돈이 사라지면 안 되니까)
function renderDayNav(ov) {
  const day = ov.day;
  const isToday = day === ov.today;
  const label = $("day-label");
  if (label) {
    label.textContent = isToday ? `오늘 ${day.slice(5)}` : day;
    label.classList.toggle("past", !isToday);
  }
  const prev = $("day-prev");
  const next = $("day-next");
  if (prev) prev.disabled = !!(ov.firstDay && day <= ov.firstDay);
  if (next) next.disabled = isToday;
  const todayBtn = $("day-today");
  if (todayBtn) todayBtn.hidden = isToday;
}

function goDay(target) {
  viewDay = target && target !== dayMeta.today ? target : null;
  seenInvoices.clear();   // 날짜가 바뀌면 "새 항목" 강조를 초기화한다
  expanded.clear();
  page.invoices = 0;      // 다른 날의 첫 쪽부터
  page.trades = 0;
  refresh();
}

$("day-prev")?.addEventListener("click", () => goDay(shiftDay(viewDay ?? dayMeta.today, -1)));
$("day-next")?.addEventListener("click", () => goDay(shiftDay(viewDay ?? dayMeta.today, 1)));
$("day-today")?.addEventListener("click", () => goDay(null));

async function refresh() {
  if (!me) return;
  try {
    const [ov, ev, health] = await Promise.all([
      getJSON(`/api/overview${viewDay ? `?${dayParam()}` : ""}`),
      getJSON(`/api/events?limit=60${viewDay ? `&${dayParam()}` : ""}`),
      getJSON("/api/health").catch(() => null),
    ]);
    const view = role.scope(me, ov);
    lastView = view;
    currentNetwork = ov.network;

    $("network").textContent = ov.network;
    dayMeta = { today: ov.today, firstDay: ov.firstDay };
    if (ov.statusLabels) STATUS_LABEL = ov.statusLabels;
    if (ov.tradeStatusLabels) TRADE_STATUS_LABEL = ov.tradeStatusLabels;
    if (ov.actionLabels) ACTION_LABEL = ov.actionLabels;
    if (ov.moveLabels) MOVE_LABEL = ov.moveLabels;
    renderDayNav(ov);
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
    renderNegotiations(view.negotiations, [...(view.invoices ?? []), ...(view.openInvoices ?? [])]);
    renderTrades(view.trades);
    renderDataStore(ov);
    renderFlows(ov);
    // 날짜로 자르지 않은 목록을 쓴다 — 어제 멈춘 결제가 오늘 사라지면 안 된다
    const openList = view.openInvoices ?? ov.openInvoices ?? view.invoices;
    renderSchedules(openList);
    renderApprovals(openList);
    renderSysInfo(ov, health);

    // 펼쳐둔 행은 최신 과정으로 다시 채운다
    for (const id of expanded) loadTimeline(id, ov.network);

    const dayNote = ev.day === ov.today ? "오늘" : ev.day;
    for (const id of ["event-total", "event-total-side"]) {
      const el = $(id);
      if (el) el.textContent = `${dayNote} ${ev.total}건 · 누적 ${ev.allTime ?? ev.total}건`;
    }
    const feedHtml = ev.events.slice(0, 30).map((e) => eventRow(e, false)).join("")
      || '<li class="empty" style="display:block">아직 활동이 없습니다</li>';
    for (const id of ["feed", "feed-side"]) {
      const el = $(id);
      if (el) el.innerHTML = feedHtml;
    }
  } catch (err) {
    console.error(err);
  }

  // 지갑 조회는 온체인 왕복이라 느리다 — 화면을 붙잡지 않고 도착하는 대로 채운다
  const wbox = $("wallets");
  if (wbox && !wbox.childElementCount) {
    wbox.innerHTML = '<div class="empty">온체인 잔액 조회 중…</div>';
  }
  getJSON("/api/wallets").then((w) => {
    lastWallets = w.wallets;
    const shown = me.kind === "store" ? w.wallets.filter((x) => x.wallet === me.id) : w.wallets;
    renderWallets(shown);
    if (lastView) renderMetrics(role.metricsFor(me, lastView, lastWallets));
  }).catch(() => {
    if (wbox && wbox.querySelector(".empty")) {
      wbox.innerHTML = '<div class="empty">잔액 조회가 늦어지고 있습니다 — 잠시 후 자동 갱신됩니다</div>';
    }
  });
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
    // 과거 날짜를 보고 있으면 지금 일어나는 일을 그 날 로그에 끼워넣지 않는다
    if (viewDay) return;
    for (const id of ["feed", "feed-side"]) {
      const feed = $(id);
      if (!feed || feed.hidden) continue;
      feed.querySelector(".empty")?.remove();
      feed.insertAdjacentHTML("afterbegin", eventRow(evt, true));
      while (feed.children.length > 40) feed.lastElementChild.remove();
    }
    beacon.className = "beacon hot";
    beacon.innerHTML = "<i></i>에이전트 작동 중";
    clearTimeout(hotTimer);
    hotTimer = setTimeout(() => {
      beacon.className = "beacon on";
      beacon.innerHTML = "<i></i>실시간 연결됨";
    }, 3000);
  });

  src.addEventListener("refresh", () => { if (!viewDay) refresh(); });
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
    btn.addEventListener("click", () => passkeyEnter(btn.dataset.id)),
  );
}

// ── 패스키 본인확인 — 문이지 벽이 아니다: 실패·미지원이면 언제든 데모 모드로 ──
const b64u = {
  enc: (buf) => btoa(String.fromCharCode(...new Uint8Array(buf)))
    .replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, ""),
  dec: (s) => Uint8Array.from(
    atob(s.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - (s.length % 4)) % 4)),
    (ch) => ch.charCodeAt(0),
  ),
};

function credentialJSON(cred) {
  const r = cred.response;
  const out = {
    id: cred.id, rawId: b64u.enc(cred.rawId), type: cred.type,
    clientExtensionResults: cred.getClientExtensionResults(),
    authenticatorAttachment: cred.authenticatorAttachment ?? null,
    response: { clientDataJSON: b64u.enc(r.clientDataJSON) },
  };
  if (r.attestationObject) {
    out.response.attestationObject = b64u.enc(r.attestationObject);
    if (r.getTransports) out.response.transports = r.getTransports();
  }
  if (r.authenticatorData) {
    out.response.authenticatorData = b64u.enc(r.authenticatorData);
    out.response.signature = b64u.enc(r.signature);
    out.response.userHandle = r.userHandle ? b64u.enc(r.userHandle) : null;
  }
  return out;
}

async function postJSON(url, body) {
  const res = await fetch(url, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail ?? `HTTP ${res.status}`);
  return data;
}

function gateAuthPanel(id, message) {
  const panel = $("gate-auth");
  if (!panel) return;
  panel.hidden = false;
  $("ga-role").textContent = ROLE_TITLE(id);
  if (message) $("ga-msg").innerHTML = `<b>${esc(ROLE_TITLE(id))}</b> — ${esc(message)}`;
  $("ga-register").onclick = () => passkeyRegister(id);
  $("ga-skip").onclick = () => enterAs(id);
}

const ROLE_TITLE = (id) => role.ROLES?.[id]?.label ?? id;

function enterAs(id) {
  role.set(id);
  $("gate-auth")?.setAttribute("hidden", "");
  start();
}

async function passkeyEnter(id) {
  if (!window.PublicKeyCredential) return enterAs(id);  // 미지원 브라우저 — 막지 않는다
  try {
    const res = await postJSON("/api/auth/passkey/login/options", { role: id });
    if (!res.registered) return gateAuthPanel(id, "이 역할에는 아직 패스키가 없습니다.");
    const options = res.options;
    options.challenge = b64u.dec(options.challenge);
    options.allowCredentials = (options.allowCredentials ?? []).map((c) => ({ ...c, id: b64u.dec(c.id) }));
    const cred = await navigator.credentials.get({ publicKey: options });
    await postJSON("/api/auth/passkey/login/verify", { role: id, credential: credentialJSON(cred) });
    enterAs(id);
  } catch (err) {
    gateAuthPanel(id, `본인확인이 완료되지 않았습니다 (${err.message ?? err}). 다시 등록하거나 데모 모드로 입장하세요.`);
  }
}

async function passkeyRegister(id) {
  try {
    const options = await postJSON("/api/auth/passkey/register/options", { role: id });
    options.challenge = b64u.dec(options.challenge);
    options.user.id = b64u.dec(options.user.id);
    options.excludeCredentials = (options.excludeCredentials ?? []).map((c) => ({ ...c, id: b64u.dec(c.id) }));
    const cred = await navigator.credentials.create({ publicKey: options });
    await postJSON("/api/auth/passkey/register/verify", { role: id, credential: credentialJSON(cred) });
    enterAs(id);
  } catch (err) {
    gateAuthPanel(id, `등록이 완료되지 않았습니다 (${err.message ?? err}). 데모 모드로 입장할 수 있습니다.`);
  }
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
  orderPanels(me.kind);

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
