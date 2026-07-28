"""대시보드 데이터 API."""

import asyncio
import json

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app import config
from app.core import credit, fixtures
from app.db import store
from app.solana import payments

router = APIRouter(prefix="/api", tags=["dashboard"])


@router.get("/health")
def health() -> dict:
    return {"ok": True, "network": config.NETWORK, "llm": config.LLM_PROVIDER}


@router.get("/overview")
def overview() -> dict:
    """대시보드 첫 화면에 필요한 모든 것."""
    invoices = store.list_docs("invoices")
    negotiations = store.list_docs("negotiations")
    profiles = fixtures.load()["stores"]

    settled = [i for i in invoices if i["status"] == "settled"]
    # 미수금 = 아직 받을 돈. 분할 원본(split)은 자식이 대신하므로 빼고(이중 계산),
    # 거부(refused)는 분쟁 확인 대기지 수취 채권이 아니다.
    not_receivable = ("settled", "split", "refused")
    outstanding = [i for i in invoices if i["status"] not in not_receivable]

    stores = []
    for sid, profile in profiles.items():
        mine = [i for i in invoices if i["store_id"] == sid]
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
                "autoPayLimit": profile["policy"]["auto_pay_limit_usdc"],
                "invoiceCount": len(mine),
                "outstandingUsdc": round(
                    sum(i["amount_usdc"] for i in mine if i["status"] not in not_receivable), 2
                ),
                "settledUsdc": round(sum(i["amount_usdc"] for i in mine if i["status"] == "settled"), 2),
            }
        )

    trades = store.list_docs("p2p_trades")
    return {
        "network": config.NETWORK,
        "totals": {
            "invoices": len(invoices),
            "settledCount": len(settled),
            "settledUsdc": round(sum(i["amount_usdc"] for i in settled), 2),
            "outstandingCount": len(outstanding),
            "outstandingUsdc": round(sum(i["amount_usdc"] for i in outstanding), 2),
            "negotiations": len(negotiations),
            "humanActions": sum(1 for e in store.list_events() if e["actor"] == "human"),
        },
        "stores": stores,
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


@router.get("/events")
def events(limit: int = 100) -> dict:
    """실행 증빙 로그 — 심사 기준 4번의 근거."""
    all_events = store.list_events()
    return {"events": all_events[-limit:][::-1], "total": len(all_events)}


@router.get("/wallets")
def wallets() -> dict:
    out = []
    for name in config.WALLETS:
        try:
            out.append(payments.balance(name))
        except Exception as exc:  # noqa: BLE001 — 결제 서비스가 꺼져도 대시보드는 살아있게
            out.append({"wallet": name, "error": str(exc)})
    return {"wallets": out}


@router.get("/stream")
async def stream(request: Request) -> StreamingResponse:
    """SSE — 새 이벤트가 생기면 즉시 밀어준다. 대시보드가 살아 움직이는 이유."""

    async def gen():
        cursor = len(store.list_events())
        yield f"event: ready\ndata: {json.dumps({'cursor': cursor})}\n\n"
        while True:
            if await request.is_disconnected():
                break
            events_now = store.list_events()
            if len(events_now) > cursor:
                for event in events_now[cursor:]:
                    yield f"event: activity\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
                cursor = len(events_now)
                yield "event: refresh\ndata: {}\n\n"
            await asyncio.sleep(0.6)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
