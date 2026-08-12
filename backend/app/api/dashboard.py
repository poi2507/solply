"""대시보드 데이터 API."""

import asyncio
import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from app import config
from app.agents import utils as agent_utils
from app.core import credit, fixtures, kst
from app.core import events as events_mod
from app.core import policy as policy_mod
from app.core import stats as stats_mod
from app.core import status as status_mod
from app.db import store
from app.solana import payments

router = APIRouter(prefix="/api", tags=["dashboard"])


@router.get("/health")
def health() -> dict:
    # store를 빼먹으면 화면이 `?? "postgres"`로 떨어져 로컬 실행에도 postgres라고 우긴다
    return {"ok": True, "network": config.NETWORK, "llm": config.LLM_PROVIDER,
            "store": config.STORE_BACKEND}


@router.get("/overview")
def overview(day: str | None = None) -> dict:
    """대시보드 첫 화면 — 기본은 오늘(KST) 하루, `day`로 과거를 본다.

    목록은 하루치만 읽는다 (기록이 몇 달 쌓여도 화면이 무거워지지 않는다).
    다만 **미수금은 날짜로 자르지 않는다** — 어제 안 낸 돈이 오늘 화면에서
    사라지면 안 된다. 누적 건수도 날짜와 무관하게 센다.
    """
    day = kst.parse(day)
    invoices = store.list_docs("invoices", day=day)
    negotiations = store.list_docs("negotiations", day=day)
    profiles = fixtures.load()["stores"]

    settled = [i for i in invoices if i["status"] == status_mod.InvoiceStatus.SETTLED]
    # 미수금 = 아직 받을 돈. 어느 상태가 받을 돈인지는 core/status.py 한 곳에서만 정한다.
    # 상태별로 따로 물어본다 — 전체 청구서를 읽지 않고도 미결 건만 모인다.
    open_invoices = [
        inv
        for status in status_mod.RECEIVABLE
        for inv in store.list_docs("invoices", status=status)
    ]

    stores = []
    for sid, profile in profiles.items():
        mine = [i for i in invoices if i["store_id"] == sid]
        my_open = [i for i in open_invoices if i["store_id"] == sid]
        rating = credit.evaluate(sid)  # 점수는 상수가 아니라 납부 이력에서 계산된다
        stores.append(
            {
                "id": sid,
                "name": profile["name"],
                "creditScore": rating["credit_score"],
                "creditBasis": {
                    "onTime": rating["on_time"],
                    "late": rating["late"],
                    "disputed": rating["disputed"],
                    "liveSettled": rating["live_settled"],
                },
                "creditLimit": profile["credit_limit_usdc"],
                # 시드값이 아니라 점주가 프론트에서 설정한 실효 정책을 보여준다 —
                # 상한을 낮췄는데 화면이 옛 값이면 승인 대기 사유와 모순된다
                "autoPayLimit": policy_mod.get(sid).auto_pay_limit_usdc,
                "inventory": [
                    {"sku": sku, "name": entry.get("name", sku),
                     "qty": entry["qty"], "safety": entry["safety"]}
                    for sku, entry in agent_utils.effective_inventory(sid).items()
                ],
                "invoiceCount": len(mine),
                # 미수금은 전체 기간, 정산액은 보고 있는 하루
                "outstandingUsdc": round(sum(i["amount_usdc"] for i in my_open), 2),
                "settledUsdc": round(
                    sum(i["amount_usdc"] for i in mine
                        if i["status"] == status_mod.InvoiceStatus.SETTLED), 2
                ),
            }
        )

    trades = store.list_docs("p2p_trades", day=day)
    moves = store.list_docs("inventory_moves", day=day)

    # 자금 흐름 다이어그램의 재료 — 물대·P2P는 위 문서들에 이미 있고,
    # 카드정산은 계수기 문서 하나로 읽는다 (폴링마다 이벤트를 훑으면 서비스가 질식한다 — 8/12 실측)
    flow_doc = stats_mod.card_flows(day)
    data_today = store.list_docs("data_orders", day=day, state="fulfilled")
    return {
        "day": day,
        "today": kst.today(),
        "firstDay": store.first_day(),
        "inventoryMoves": sorted(moves, key=lambda m: m.get("updated_at", ""), reverse=True)[:40],
        # 본사 창고 원장 — 본사 화면은 지점 재고가 아니라 자기 창고를 본다
        "hqInventory": [
            {"sku": sku, "name": entry.get("name", sku),
             "qty": entry["qty"], "safety": entry["safety"]}
            for sku, entry in agent_utils.effective_inventory("hq").items()
        ],
        "network": config.NETWORK,
        "statusLabels": status_mod.LABELS,
        "tradeStatusLabels": status_mod.TRADE_LABELS,
        "actionLabels": events_mod.ACTION_LABELS,
        "moveLabels": events_mod.MOVE_LABELS,
        "totals": {
            # 보고 있는 하루
            "invoices": len(invoices),
            "settledCount": len(settled),
            "settledUsdc": round(sum(i["amount_usdc"] for i in settled), 2),
            "negotiations": len(negotiations),
            "humanActions": store.count_events(actor="human", day=day),
            # 날짜와 무관 — 받을 돈과 누적 실적
            "outstandingCount": len(open_invoices),
            "outstandingUsdc": round(sum(i["amount_usdc"] for i in open_invoices), 2),
            "allInvoices": store.count_docs("invoices"),
            "allTrades": store.count_docs("p2p_trades"),
        },
        "stores": stores,
        # 자금 흐름(보고 있는 하루) — 다이어그램이 이 숫자로 화살표를 그린다
        "flows": {
            "card": flow_doc.get("card", {}),
            "royaltyUsdc": flow_doc.get("royalty_usdc", 0.0),
            "guestUsdc": flow_doc.get("guest_usdc", 0.0),
            "guest": flow_doc.get("guest", {}),
            "dataUsdc": round(sum(float(o.get("price_usdc") or 0) for o in data_today), 2),
            "dataCount": len(data_today),
        },
        # 본사 수익 계기판 — 구독료 밖 두 매출원(로열티·데이터 판매)의 실측 누적
        "hqRevenue": stats_mod.snapshot(),
        # 데이터 상점 — 상품 가격과 최근 판매 (외부 구매 + 에이전트 자급 구매)
        "dataStore": {
            "priceUsdc": policy_mod.get("hq").data_price_usdc,
            "recentSales": sorted(
                store.list_docs("data_orders", state="fulfilled"),
                key=lambda o: o.get("updated_at", ""), reverse=True,
            )[:5],
        },
        # 승인·예약 패널은 날짜로 자르지 않는다 — 어제 멈춘 결제가
        # 오늘 화면에서 사라지면 돈이 묶인 채로 아무 표시도 남지 않는다
        "openInvoices": sorted(open_invoices, key=lambda i: i.get("updated_at", ""), reverse=True),
        "invoices": sorted(invoices, key=lambda i: i.get("updated_at", ""), reverse=True),
        "negotiations": sorted(negotiations, key=lambda n: n.get("updated_at", ""), reverse=True),
        "trades": sorted(trades, key=lambda t: t.get("updated_at", ""), reverse=True),
    }


@router.get("/report")
def report() -> dict:
    """정산 리포트 — 통계는 core/report, 문장은 Gemini(또는 mock 규칙)가 쓴다."""
    from app.core import policy as policy_mod
    from app.core import report as report_mod
    from app.llm import judge

    stats = report_mod.collect()
    text = judge.weekly_report(stats, policy_mod.get("hq").as_prompt_values())
    return {"stats": stats, "report": text}


@router.get("/invoices/{invoice_id}/timeline")
def timeline(invoice_id: str) -> dict:
    """청구서 한 건의 전 과정 — 발행부터 정산까지 한 흐름으로.

    표를 종류별로 흩어놓으면 "이 청구서가 어떻게 협상되고 정산됐나"가 보이지 않는다.
    화면에서 행을 펼칠 때 쓴다.
    """
    invoice = store.get("invoices", invoice_id)
    if not invoice:
        raise HTTPException(404, f"청구서 없음: {invoice_id}")

    # 분할된 경우 자식 청구서까지 한 이야기로 묶는다
    family = {invoice_id}
    children = store.list_docs("invoices", parent_id=invoice_id)
    family.update(c["id"] for c in children)
    if invoice.get("parent_id"):
        family.add(invoice["parent_id"])

    steps = store.events_for(tuple(family))
    negotiations = [
        n for n in store.list_docs("negotiations") if n.get("invoice_id") in family
    ]

    return {
        "invoice": invoice,
        "children": sorted(children, key=lambda c: c["id"]),
        "negotiations": sorted(negotiations, key=lambda n: n.get("updated_at", "")),
        "steps": steps,
    }


@router.get("/events")
def events(limit: int = 100, day: str | None = None) -> dict:
    """실행 증빙 로그 — 심사 기준 4번의 근거.

    기본은 오늘(KST) 하루. 요청한 건수만 읽어서 기록이 수만 건 쌓여도 가볍다.
    `total`은 그 하루의 건수, `allTime`은 지금까지 쌓인 전체 건수다.
    """
    day = kst.parse(day)
    return {
        "day": day,
        "events": store.recent_events(limit, day=day),
        "total": store.count_events(day=day),
        "allTime": store.count_events(),
    }


@router.get("/wallets")
def wallets() -> dict:
    out = []
    for name in config.WALLETS:
        try:
            bal = payments.balance(name)
        except Exception as exc:  # noqa: BLE001 — 결제 서비스가 꺼져도 대시보드는 살아있게
            out.append({"wallet": name, "error": str(exc)})
            continue
        if name != "hq":
            # 본사가 아직 지급하지 못한 카드 매출 — 지점 입장의 "받을 돈".
            # 이게 안 보이면 잔액 편중을 화면만으로 진단할 수 없다.
            till = store.get("till", name) or {}
            bal["pending_settlement_usdc"] = round(till.get("accrued_usdc", 0.0), 2)
        out.append(bal)
    return {"wallets": out}


@router.get("/stream")
async def stream(request: Request) -> StreamingResponse:
    """SSE — 새 이벤트가 생기면 즉시 밀어준다. 대시보드가 살아 움직이는 이유."""

    async def gen():
        # 개수만 세서 변화를 감지하고, 늘었을 때만 새 이벤트를 가져온다.
        # 매 틱마다 전체를 읽으면 열려 있는 대시보드가 DB를 계속 갈아 다른 요청까지 느려진다.
        cursor = store.count_events()
        yield f"event: ready\ndata: {json.dumps({'cursor': cursor})}\n\n"
        while True:
            if await request.is_disconnected():
                break
            total = store.count_events()
            if total > cursor:
                for event in store.events_after(cursor):
                    yield f"event: activity\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
                cursor = total
                yield "event: refresh\ndata: {}\n\n"
            await asyncio.sleep(1.2)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
