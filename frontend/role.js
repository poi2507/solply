// 역할 — 어느 입장으로 접속했는지. 본사·가맹점·시스템 관리자가 서로 다른 화면을 본다.
//
// 실제 서비스에서 본사 담당자와 가맹점 사장님이 같은 화면을 볼 이유가 없다.
// 여기서는 인증 대신 역할 선택으로 그 구분을 표현한다 (데모 범위).

const KEY = "solply.role";

export const ROLES = {
  hq: {
    kind: "hq",
    label: "본사 정산팀",
    caption: "전 지점 청구·심사·정산",
    desc: "청구서를 발행하고 가맹점의 협상 제안을 심사합니다. 모든 지점의 미수금과 신용을 봅니다.",
  },
  admin: {
    kind: "admin",
    label: "시스템 관리자",
    caption: "실행 증빙 · 지갑 · 네트워크",
    desc: "에이전트의 모든 판단 로그와 온체인 지갑 상태를 감사합니다. 거래에는 개입하지 않습니다.",
  },
};

/** 저장된 역할 (없으면 null) */
export function current() {
  const id = localStorage.getItem(KEY);
  if (!id) return null;
  if (ROLES[id]) return { id, ...ROLES[id] };
  return { id, kind: "store", label: id, caption: "내 청구서·잔액·정책", desc: "" };
}

export function set(id) {
  localStorage.setItem(KEY, id);
}

export function clear() {
  localStorage.removeItem(KEY);
}

/** data-role 속성으로 패널을 보이거나 숨긴다. 여러 역할은 공백으로 나열한다. */
export function applyVisibility(kind) {
  document.querySelectorAll("[data-role]").forEach((el) => {
    const allowed = el.dataset.role.split(/\s+/);
    el.hidden = !allowed.includes(kind);
  });
  // 가맹점 화면에서는 '가맹점' 열이 의미가 없다 (전부 자기 것)
  document.querySelectorAll(".col-store").forEach((el) => {
    el.style.display = kind === "hq" || kind === "admin" ? "" : "none";
  });
}

/** 역할에 맞게 데이터를 걸러낸다 — 가맹점은 자기 것만 본다. */
export function scope(role, overview) {
  if (role.kind !== "store") return overview;

  const mine = overview.invoices.filter((i) => i.store_id === role.id);
  const myIds = new Set(mine.map((i) => i.id));
  // 직거래 협상(가격 흥정·본사 중개)은 invoice_id 자리에 거래 ID(P2P-…)가 들어온다 —
  // 청구서 ID로만 거르면 지점 화면에서 자기 흥정이 안 보인다 (8/19 팀장 발견)
  const myTrades = new Set(
    (overview.trades ?? [])
      .filter((t) => t.buyer_id === role.id || t.seller_id === role.id)
      .map((t) => t.id),
  );
  return {
    ...overview,
    invoices: mine,
    stores: overview.stores.filter((s) => s.id === role.id),
    negotiations: overview.negotiations.filter(
      (n) => myIds.has(n.invoice_id) || myTrades.has(n.invoice_id),
    ),
    trades: (overview.trades ?? []).filter(
      (t) => t.buyer_id === role.id || t.seller_id === role.id,
    ),
    inventoryMoves: (overview.inventoryMoves ?? []).filter((m) => m.store_id === role.id),
    openInvoices: (overview.openInvoices ?? []).filter((i) => i.store_id === role.id),
  };
}

/** 가맹점 화면의 지표 — 전체 합계가 아니라 내 몫으로 바꾼다. */
export function metricsFor(role, scoped, wallets) {
  const settled = scoped.invoices.filter((i) => i.status === "settled");
  const open = scoped.invoices.filter((i) => !["settled", "refused", "split"].includes(i.status));
  const sum = (list) => list.reduce((a, i) => a + Number(i.amount_usdc ?? 0), 0);

  if (role.kind === "store") {
    const me = scoped.stores[0] ?? {};
    // 납부할 금액은 그날치가 아니라 전체 미결 — 어제 밀린 돈이 사라지면 안 된다
    const owed = Number(me.outstandingUsdc ?? sum(open));
    // 조회 실패 응답에는 usdc가 없다 — 그대로 쓰면 0.00을 "결제 가능액"으로 우긴다
    const found = (wallets ?? []).find((w) => w.wallet === role.id);
    const wallet = found && !found.error ? found : null;
    const walletFoot = found?.error ? "결제 서비스 연결 안 됨" : wallet ? "결제 가능액" : "조회 중…";
    const basis = me.creditBasis
      ? `정시납 ${me.creditBasis.onTime} · 연체 ${me.creditBasis.late}`
      : "납부 이력 기준";
    return [
      { label: "납부 완료", value: sum(settled), unit: "USDC", foot: `이 날 ${settled.length}건`, accent: true },
      { label: "납부할 금액", value: owed, unit: "USDC", foot: "미결 전체", warn: owed > 0 },
      { label: "내 신용점수", value: me.creditScore ?? 0, unit: "점", foot: basis, plain: true },
      { label: "지갑 잔액", value: wallet ? wallet.usdc : "—", unit: wallet ? "USDC" : "",
        foot: walletFoot, plain: !wallet, warn: !!found?.error },
    ];
  }

  const t = scoped.totals;
  if (role.kind === "admin") {
    return [
      { label: "온체인 정산", value: t.settledUsdc, unit: "USDC", foot: `이 날 ${t.settledCount}건`, accent: true },
      { label: "에이전트 협상", value: t.negotiations, unit: "건", foot: "이 날 자동 합의", plain: true },
      { label: "사람 개입", value: t.humanActions, unit: "회", foot: "이 날 사람이 누른 횟수", plain: true },
      { label: "누적 청구서", value: t.allInvoices ?? t.invoices, unit: "건", foot: "전체 기간 발행", plain: true },
    ];
  }

  const rev = scoped.hqRevenue ?? {};
  const extra = (rev.royalty_usdc ?? 0) + (rev.data_sales_usdc ?? 0);
  return [
    { label: "정산 완료", value: t.settledUsdc, unit: "USDC", foot: `이 날 ${t.settledCount}건`, accent: true },
    { label: "미수금", value: t.outstandingUsdc, unit: "USDC", foot: `미결 전체 ${t.outstandingCount ?? 0}건`, warn: (t.outstandingUsdc ?? 0) > 0 },
    { label: "부가 수익", value: extra, unit: "USDC",
      foot: `로열티 ${rev.royalty_count ?? 0}건 · 데이터 ${rev.data_sales_count ?? 0}건 누적` },
    { label: "에이전트 협상", value: t.negotiations, unit: "건", foot: "이 날 자동 합의", plain: true },
  ];
}
