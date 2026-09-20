// 손님 페이지 — 구매가 라이브 경제의 수요이자 트리거가 된다.

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

function stockBar(qty, safety) {
  const denom = Math.max(qty, safety * 2, 1);
  const fill = Math.max(2, Math.min(100, (qty / denom) * 100));
  const tick = safety > 0 ? Math.min(100, (safety / denom) * 100) : null;
  return `<div class="stockbar ${qty < safety ? "low" : ""}"><i style="width:${fill}%"></i>${tick != null ? `<b style="left:${tick}%"></b>` : ""}</div>`;
}

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

async function loadWallet() {
  try {
    const w = await (await fetch("/api/shop/wallet")).json();
    $("gw-usdc").innerHTML = w.usdc == null
      ? '<small>조회 지연 — 잠시 후 갱신</small>'
      : `${w.usdc} <small>USDC</small>`;
    $("gw-addr").textContent = w.address ? `${w.address.slice(0, 6)}…${w.address.slice(-6)}` : "";
  } catch { /* 지갑 조회가 늦어도 진열대는 산다 */ }
}

// ── 실시간 기록 — 방금 누른 버튼이 일으킨 에이전트 활동을 이 자리에서 본다 ──
// 대시보드가 쓰는 SSE(/api/stream)를 그대로 구독하고, 이 지점(또는 그 지점의 청구서)에
// 관한 사건만 남긴다. 조달이 끝났다는 신호(shop.procured)가 오거나 2분 반이 지나면 닫는다.
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
  if (p.tx) bits.push(`<a href="https://explorer.solana.com/tx/${esc(p.tx)}?cluster=devnet" target="_blank" rel="noopener">tx ↗</a>`);
  return `<li><time>${esc(t)}</time><span class="sl-who">${esc(e.actor)}</span><span class="sl-what">${esc(e.action)}</span><span class="sl-detail">${bits.join(" · ")}</span></li>`;
}

function startLive(storeId, storeName, mode) {
  stopLive();
  const panel = $("live");
  panel.hidden = false;
  panel.classList.add("running");
  $("live-title").textContent = mode === "started"
    ? `${storeName} 에이전트가 지금 움직입니다`
    : `${storeName} — 도는 틱이 곧 조달을 처리합니다`;
  $("live-sub").textContent = "실행 기록이 도착하는 대로 여기 쌓입니다";
  $("live-list").innerHTML = "";
  panel.scrollIntoView({ behavior: "smooth", block: "nearest" });

  const source = new EventSource("/api/stream");
  live = { source, store: storeId, invoices: new Set(), timer: null };
  live.timer = setTimeout(() => stopLive("기록은 대시보드 실행 로그에서 계속 볼 수 있습니다"), 150000);

  source.addEventListener("activity", (ev) => {
    if (!live) return;
    let e;
    try { e = JSON.parse(ev.data); } catch { return; }
    const p = e.payload ?? {};
    // 이 지점의 에이전트(store-a-agent), 이 지점을 가리키는 사건, 또는 앞서 본 청구서의 후속 사건
    const mine = (typeof e.actor === "string" && e.actor.startsWith(storeId))
      || p.store_id === storeId
      || (p.invoice_id && live.invoices.has(p.invoice_id));
    if (!mine) return;
    if (p.invoice_id) live.invoices.add(p.invoice_id);
    $("live-list").insertAdjacentHTML("beforeend", liveRow(e));
    if (e.action === "shop.procured" && p.store_id === storeId) {
      stopLive("조달이 끝났습니다 — 청구서와 정산 내역은 대시보드에서 확인하세요");
      render();
    } else if (e.action === "shop.procure_failed" && p.store_id === storeId) {
      stopLive("이번 조달은 실패로 기록됐습니다 — 다음 틱이 다시 시도합니다");
    }
  });
  source.addEventListener("error", () => { /* 재연결은 브라우저가 한다 */ });
}

async function render() {
  const res = await fetch("/api/shop");
  const { stores } = await res.json();
  $("stores").innerHTML = stores.map((s) => `
    <section class="shop-store">
      <h2>${esc(s.name)}</h2>
      <div class="sub">${esc(s.id)} · 재고가 안전선(눈금) 아래로 내려가면 에이전트가 그 자리에서 조달을 시작합니다</div>
      <div class="goods">
        ${s.items.map((it) => `
          <div class="good">
            <div class="top"><span class="name">${esc(it.name)}</span><span class="price">${it.price_usdc} USDC</span></div>
            <div class="stockline">${stockBar(it.qty, it.safety)}<span class="qtytxt">${it.qty}개 남음</span></div>
            <button data-store="${esc(s.id)}" data-name="${esc(s.name)}" data-sku="${esc(it.sku)}" ${it.qty <= 0 ? "disabled" : ""}>
              ${it.qty <= 0 ? "품절 — 에이전트가 채우는 중" : "1개 구매"}
            </button>
          </div>`).join("")}
      </div>
    </section>`).join("");

  document.querySelectorAll("button[data-sku]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      btn.disabled = true;
      try {
        const res = await fetch("/api/shop/purchase", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ store_id: btn.dataset.store, sku: btn.dataset.sku, qty: 1 }),
        });
        const data = await res.json();
        if (!res.ok) { toast(esc(data.detail ?? "구매 실패"), true); return; }
        const receipt = data.tx
          ? ` · <a href="https://explorer.solana.com/tx/${esc(data.tx)}?cluster=${esc(data.network ?? "devnet")}"
               target="_blank" rel="noopener" style="color:inherit; font-weight:650">
               ${esc(String(data.paid_usdc))} USDC 온체인 영수증 ↗</a>`
          : "";
        toast(`<b>구매 완료</b> — ${esc(data.next)}${receipt}`, data.low_stock);
        if (data.trigger === "started" || data.trigger === "tick_running") {
          startLive(btn.dataset.store, btn.dataset.name, data.trigger);
        }
      } catch {
        toast("연결에 실패했습니다.", true);
      } finally {
        render();
        loadWallet();  // 결제가 나갔으니 잔액을 다시 읽는다
      }
    });
  });
}

render();
loadWallet();
setInterval(render, 30000);  // 다른 손님·에이전트의 활동이 진열대에 반영되게
