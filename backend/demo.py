"""Solply 데모 오케스트레이터.

에이전트 그래프를 번갈아 호출해 협상을 성사시킨다. 사람은 아무 버튼도 누르지 않는다.

  A지점 — 검수 일치 → x402 왕복 즉시 자율 결제
  B지점 — 검수 불일치 → 차감 협상 → 조정 결제
  E(B⇄A) — 재고 소진 → 지점 간 직거래 협상 → 본사 승인 → B→A 온체인 결제
  D(A지점) — 발주 없는 품목 청구 → 결제 거부 → 사람 에스컬레이션
  C지점 — 잔액 부족 → 유예 협상 → 예약 → 예약일 도래 시 실제 실행

협상이 그래프 안의 루프가 아니라 **에이전트 사이의 왕복**인 이유: 실제 서비스에서
두 에이전트는 다른 프로세스(나중엔 다른 회사)에 있다. 여기서는 오케스트레이터가
그 왕복을 대신한다.

  make demo        Gemini 판단 (심사·영상용)
  make demo-mock   규칙 기반 (리허설용, 빠름 — 온체인 결제는 동일하게 발생)
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app import config
from app.agents.runner import latest_event, run_verbose
from app.core import policy as policy_mod
from app.db import store as db
from app.solana import payments

C = {
    "hq": "\033[36m", "a": "\033[32m", "b": "\033[33m", "c": "\033[35m",
    "dim": "\033[90m", "bold": "\033[1m", "0": "\033[0m",
}


def banner(text: str, color: str = "0") -> None:
    print(f"\n{C[color]}{C['bold']}{'━' * 74}\n  {text}\n{'━' * 74}{C['0']}")


def reporter(tag: str, color: str):
    def on_node(name: str, update: dict) -> None:
        detail = ""
        if "outcome" in update and update["outcome"] not in (None, "noop"):
            detail = f" → {update['outcome']}"
        print(f"  {C[color]}[{tag}]{C['0']} {C['dim']}▪ {name}{detail}{C['0']}")

    def on_message(text: str) -> None:
        for line in text.splitlines():
            if line.strip():
                print(f"  {C[color]}[{tag}]{C['0']} {line.strip()}")

    return on_node, on_message


async def act(agent: str, intent: str, tag: str, color: str, **kwargs) -> dict:
    on_node, on_message = reporter(tag, color)
    return await run_verbose(agent, intent, on_node=on_node, on_message=on_message, **kwargs)


def newest_open_invoice(store_id: str) -> dict | None:
    docs = [d for d in db.list_docs("invoices", store_id=store_id) if d["status"] != "settled"]
    return max(docs, key=lambda d: d["updated_at"]) if docs else None


def confirm_settlement(invoice_id: str) -> bool:
    """x402 왕복이 정산까지 끝냈는지 확인하고, 본사 쪽 확정 로그를 보여준다."""
    invoice = db.get("invoices", invoice_id)
    receipt = latest_event(db.list_events(), "x402.settled")
    if invoice and invoice["status"] == "settled" and receipt:
        print(f"  {C['hq']}[본사]{C['0']} x402 서명 검증 → 온체인 3중 대조 일치 — 정산 확정 "
              f"{C['dim']}(tx {receipt['tx'][:16]}…){C['0']}")
        return True
    return False


async def scenario_a() -> None:
    banner("A지점 (강남) — 검수 일치, x402 왕복으로 즉시 자율 결제", "a")
    simulate_card_settlement("store-a", 35.0)  # 주간 매출 입금 — 리허설을 반복해도 잔액이 유지된다
    issued = await act("hq", "invoice.issue", "본사", "hq", delivery_id="DEL-001")
    invoice_id = issued.get("invoice_id")
    if not invoice_id:
        return print("  청구서 발행 실패")

    paid = await act(
        "store", "invoice.handle", "A지점", "a", store_id="store-a", invoice_id=invoice_id
    )
    if paid.get("outcome") == "paid" and not confirm_settlement(invoice_id):
        # x402 영수증이 없으면 예전 경로(본사 사후 검증)로 확정한다
        await act(
            "hq", "payment.verify", "본사", "hq",
            invoice_id=invoice_id, payload={"tx_signature": paid["tx_signature"]},
        )


async def scenario_b() -> None:
    banner("B지점 (홍대) — 검수 불일치 발견, 차감 협상", "b")
    simulate_card_settlement("store-b", 35.0)
    issued = await act("hq", "invoice.issue", "본사", "hq", delivery_id="DEL-002")
    invoice_id = issued.get("invoice_id")
    if not invoice_id:
        return print("  청구서 발행 실패")

    await act("store", "invoice.handle", "B지점", "b", store_id="store-b", invoice_id=invoice_id)
    proposal = latest_event(db.list_events(), "proposal.adjustment")
    if not proposal:
        return print(f"  {C['dim']}차감 제안이 나오지 않았습니다{C['0']}")

    await act(
        "hq", "proposal.adjustment", "본사", "hq", invoice_id=invoice_id, payload=proposal
    )

    paid = await act(
        "store", "invoice.pay_adjusted", "B지점", "b",
        store_id="store-b", invoice_id=invoice_id,
    )
    if paid.get("outcome") == "paid" and not confirm_settlement(invoice_id):
        await act(
            "hq", "payment.verify", "본사", "hq",
            invoice_id=invoice_id, payload={"tx_signature": paid["tx_signature"]},
        )


def simulate_card_settlement(store_id: str, invoice_amount: float) -> None:
    """예약일의 카드정산금 입금 시뮬레이션 — 본사가 카드매출 정산을 대행하는 구조.

    '청구액 + 운영 하한'을 채우는 만큼만 넣는다. 데모를 반복해도 지점 잔액이
    불어나 '잔액 부족' 시나리오가 깨지지 않도록 자기 유지되는 금액이다.
    """
    balance = payments.balance(store_id)
    reserve = policy_mod.get(store_id).min_reserve_usdc
    needed = round(max(0.0, invoice_amount + reserve - balance["usdc"]), 2)
    if needed <= 0:
        return
    payments.pay("hq", balance["address"], needed, "CARD-SETTLEMENT")
    print(f"  {C['dim']}💳 카드정산금 {needed} USDC 입금 확인 (지점 지갑){C['0']}")


async def scenario_c() -> None:
    banner("C지점 (부산) — 잔액 부족, 유예 협상 → 예약 실행", "c")
    issued = await act("hq", "invoice.issue", "본사", "hq", delivery_id="DEL-003")
    invoice_id = issued.get("invoice_id")
    if not invoice_id:
        return print("  청구서 발행 실패")

    await act("store", "invoice.handle", "C지점", "c", store_id="store-c", invoice_id=invoice_id)
    proposal = latest_event(db.list_events(), "proposal.deferral")
    if not proposal:
        return print(f"  {C['dim']}유예 제안이 나오지 않았습니다{C['0']}")

    await act("hq", "proposal.deferral", "본사", "hq", invoice_id=invoice_id, payload=proposal)

    # ── 예약일 도래 — 시간을 당겨 합의된 예약 납부를 실제로 실행한다 ──
    invoice = db.get("invoices", invoice_id)
    if invoice["status"] != "scheduled":
        return
    print(f"\n  {C['dim']}⏩ 금요일로 시간을 당깁니다 — 예약 실행 (운영에선 Cloud Scheduler → POST /api/schedules/{{id}}/run){C['0']}")
    simulate_card_settlement("store-c", invoice["amount_usdc"])
    paid = await act(
        "store", "invoice.pay_scheduled", "C지점", "c",
        store_id="store-c", invoice_id=invoice_id,
    )
    if paid.get("outcome") == "paid":
        confirm_settlement(invoice_id)


async def scenario_d() -> None:
    banner("A지점 (강남) — 발주 없는 품목 청구, 결제 거부 → 사람 에스컬레이션", "a")
    issued = await act("hq", "invoice.issue", "본사", "hq", delivery_id="DEL-004")
    invoice_id = issued.get("invoice_id")
    if not invoice_id:
        return print("  청구서 발행 실패")

    await act("store", "invoice.handle", "A지점", "a", store_id="store-a", invoice_id=invoice_id)


async def scenario_f() -> None:
    banner("B지점 (홍대) — 전액 유예 불가 → 분할 역제안 → 합의 (멀티턴 협상)", "b")
    simulate_card_settlement("store-b", 25.0)  # 잔액을 '전액은 부족, 1회차는 가능' 구간으로
    issued = await act("hq", "invoice.issue", "본사", "hq", delivery_id="DEL-005")
    invoice_id = issued.get("invoice_id")
    if not invoice_id:
        return print("  청구서 발행 실패")

    await act("store", "invoice.handle", "B지점", "b", store_id="store-b", invoice_id=invoice_id)
    proposal = latest_event(db.list_events(), "proposal.deferral")
    if not proposal or proposal.get("invoice_id") != invoice_id:
        return print(f"  {C['dim']}유예 제안이 나오지 않았습니다{C['0']}")

    countered = await act(
        "hq", "proposal.deferral", "본사", "hq", invoice_id=invoice_id, payload=proposal
    )
    split = (countered.get("decision") or {}).get("split")
    if not split:
        return print(f"  {C['dim']}역제안(분할)이 나오지 않았습니다{C['0']}")

    # 가맹점이 역제안을 재평가 — 1회차는 지금, 2회차는 예약
    part1, part2 = split["children"][0]["id"], split["children"][1]["id"]
    paid = await act(
        "store", "invoice.pay_installment", "B지점", "b",
        store_id="store-b", invoice_id=part1,
    )
    if paid.get("outcome") == "paid":
        confirm_settlement(part1)
        print(f"  {C['dim']}🕐 2회차 {part2}는 예약 상태 — 예약 실행기(Cloud Scheduler 자리)가 처리한다{C['0']}")


async def scenario_e() -> None:
    banner("B지점 ⇄ A지점 — 가맹점 간 재고 직거래, 본사는 심판", "b")
    simulate_card_settlement("store-b", 10.0)

    # 1) 구매측(B): 재고 점검 → 조달 경로 비교 → 직거래 제안
    proposed = await act("store", "restock.check", "B지점", "b", store_id="store-b")
    trade_id = (proposed.get("trade") or {}).get("id")
    if not trade_id:
        return print(f"  {C['dim']}직거래 제안이 나오지 않았습니다{C['0']}")

    # 2) 판매측(A): 안전재고 확인 후 응답
    responded = await act("store", "p2p.respond", "A지점", "a", store_id="store-a", trade_id=trade_id)
    if (responded.get("trade") or {}).get("status") != "accepted":
        return print(f"  {C['dim']}판매 지점이 수락하지 않았습니다{C['0']}")

    # 3) 본사: 위생·신용·가격 심사 (자율성과 통제의 경계)
    await act("hq", "p2p.review", "본사", "hq", trade_id=trade_id)
    if (db.get("p2p_trades", trade_id) or {}).get("status") != "approved":
        return print(f"  {C['dim']}본사가 승인하지 않아 거래를 중단합니다{C['0']}")

    # 4) 구매측(B): 승인 확인 후 x402 왕복으로 B→A 온체인 결제
    paid = await act("store", "p2p.pay", "B지점", "b", store_id="store-b", trade_id=trade_id)
    if paid.get("outcome") != "paid":
        return

    # 5) 본사: 확정된 거래를 장부에 기록
    await act("hq", "p2p.record", "본사", "hq", trade_id=trade_id)


def summary() -> None:
    banner("정산 결과", "hq")
    icons = {"settled": "✅", "scheduled": "🕐", "paid": "💸", "issued": "📄", "disputed": "⚖️", "refused": "🚫", "pending_approval": "🙋", "split": "➗"}
    for inv in sorted(db.list_docs("invoices"), key=lambda d: d["updated_at"]):
        print(f"  {icons.get(inv['status'], '•')} {inv['id']}  {inv['store_id']:9} "
              f"{inv['amount_usdc']:>7.2f} USDC  {inv['status']}")
        if inv.get("tx_sig"):
            print(f"     {C['dim']}tx {inv['tx_sig'][:48]}…{C['0']}")

    trades = db.list_docs("p2p_trades")
    if trades:
        print()
        icons = {"confirmed": "🤝", "rejected": "🚫"}
        for t in sorted(trades, key=lambda d: d["updated_at"]):
            print(f"  {icons.get(t['status'], '•')} {t['id']}  {t['buyer_id']}→{t['seller_id']:8} "
                  f"{t['price_usdc']:>7.2f} USDC  직거래 {t['status']}")
            if t.get("tx_sig"):
                print(f"     {C['dim']}tx {t['tx_sig'][:48]}…{C['0']}")

    negotiations = db.list_docs("negotiations")
    print(f"\n  협상 {len(negotiations)}건 · 실행 증빙 이벤트 {len(db.list_events())}건")
    for neg in negotiations:
        print(f"    {C['dim']}· [{neg['type']}] {neg['decision']} — {neg['reasoning'][:64]}{C['0']}")
    human = sum(1 for e in db.list_events() if e["actor"] == "human")
    print(f"\n  {C['bold']}사람이 누른 버튼: {human}회{C['0']}")

    from app.core import report as report_mod
    from app.llm import judge
    text = judge.weekly_report(report_mod.collect(), policy_mod.get("hq").as_prompt_values())
    if text:
        print(f"\n  {C['bold']}📋 정산 리포트{C['0']}")
        for line in text.splitlines():
            print(f"  {line.strip()}")
    print(f"\n  {C['dim']}대시보드: http://localhost:8080{C['0']}\n")


async def main() -> None:
    parser = argparse.ArgumentParser(description="Solply 데모")
    parser.add_argument("--only", choices=["a", "b", "c", "d", "e", "f"], help="한 시나리오만 실행")
    parser.add_argument("--keep", action="store_true", help="기존 상태를 유지")
    args = parser.parse_args()

    if not args.keep:
        db.reset(keep=("policies",))  # 사용자가 설정한 거래 정책은 남긴다

    banner("SOLPLY — 프랜차이즈 식자재 대금 자율 정산", "hq")
    mode = "규칙 기반(mock)" if config.LLM_PROVIDER == "mock" else f"{config.LLM_PROVIDER} · {config.HQ_MODEL}"
    print(f"  판단 주체: {mode} · 네트워크: {config.NETWORK} · 저장소: {config.STORE_BACKEND}")
    print(f"  정산 경로: x402 (HTTP 402) — {config.SOLPLY_API_URL}")
    if config.STORE_BACKEND == "local":
        print("  ⚠ SOLPLY_STORE=local이면 API 서버와 상태가 분리돼 x402 왕복이 어긋난다 — postgres 권장")
    print(f"  {C['dim']}대시보드를 띄워두면 활동이 실시간으로 표시됩니다 → http://localhost:8080{C['0']}")

    scenarios = {
        "a": scenario_a, "b": scenario_b, "c": scenario_c,
        "d": scenario_d, "e": scenario_e, "f": scenario_f,
    }
    for key in [args.only] if args.only else ["a", "b", "e", "d", "c", "f"]:
        try:
            await scenarios[key]()
        except Exception as exc:  # noqa: BLE001 — 하나가 죽어도 나머지는 계속
            print(f"  {C['dim']}시나리오 {key.upper()} 중단: {str(exc)[:200]}{C['0']}")

    summary()


if __name__ == "__main__":
    asyncio.run(main())
