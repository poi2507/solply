// 손님 페이지 — 구매가 라이브 경제의 수요가 된다.

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

async function render() {
  const res = await fetch("/api/shop");
  const { stores } = await res.json();
  $("stores").innerHTML = stores.map((s) => `
    <section class="shop-store">
      <h2>${esc(s.name)}</h2>
      <div class="sub">${esc(s.id)} · 재고가 안전선(눈금) 아래로 내려가면 에이전트가 조달을 시작합니다</div>
      <div class="goods">
        ${s.items.map((it) => `
          <div class="good">
            <div class="top"><span class="name">${esc(it.name)}</span><span class="price">${it.price_usdc} USDC</span></div>
            <div class="stockline">${stockBar(it.qty, it.safety)}<span class="qtytxt">${it.qty}개 남음</span></div>
            <button data-store="${esc(s.id)}" data-sku="${esc(it.sku)}" ${it.qty <= 0 ? "disabled" : ""}>
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
        toast(`<b>구매 완료</b> — ${esc(data.next)}`, data.low_stock);
      } catch {
        toast("연결에 실패했습니다.", true);
      } finally {
        render();
      }
    });
  });
}

render();
setInterval(render, 30000);  // 다른 손님·에이전트의 활동이 진열대에 반영되게
