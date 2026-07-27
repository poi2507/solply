"""Solply 데모 오케스트레이터.

에이전트 그래프를 번갈아 호출해 협상을 성사시킨다. 사람은 아무 버튼도 누르지 않는다.

  A지점 — 검수 일치 → 즉시 자율 결제
  B지점 — 검수 불일치 → 차감 협상 → 조정 결제
  C지점 — 잔액 부족 → 유예 협상 → 예약

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
from app.db import store as db

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
    return sorted(docs, key=lambda d: d["updated_at"])[-1] if docs else None


async def scenario_a() -> None:
    banner("A지점 (강남) — 검수 일치, 즉시 자율 결제", "a")
    issued = await act("hq", "invoice.issue", "본사", "hq", delivery_id="DEL-001")
    invoice_id = issued.get("invoice_id")
    if not invoice_id:
        return print("  청구서 발행 실패")

    paid = await act(
        "store", "invoice.handle", "A지점", "a", store_id="store-a", invoice_id=invoice_id
    )
    if paid.get("outcome") == "paid":
        await act(
            "hq", "payment.verify", "본사", "hq",
            invoice_id=invoice_id, payload={"tx_signature": paid["tx_signature"]},
        )


async def scenario_b() -> None:
    banner("B지점 (홍대) — 검수 불일치 발견, 차감 협상", "b")
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
    if paid.get("outcome") == "paid":
        await act(
            "hq", "payment.verify", "본사", "hq",
            invoice_id=invoice_id, payload={"tx_signature": paid["tx_signature"]},
        )


async def scenario_c() -> None:
    banner("C지점 (부산) — 잔액 부족, 유예 협상", "c")
    issued = await act("hq", "invoice.issue", "본사", "hq", delivery_id="DEL-003")
    invoice_id = issued.get("invoice_id")
    if not invoice_id:
        return print("  청구서 발행 실패")

    await act("store", "invoice.handle", "C지점", "c", store_id="store-c", invoice_id=invoice_id)
    proposal = latest_event(db.list_events(), "proposal.deferral")
    if not proposal:
        return print(f"  {C['dim']}유예 제안이 나오지 않았습니다{C['0']}")

    await act("hq", "proposal.deferral", "본사", "hq", invoice_id=invoice_id, payload=proposal)


def summary() -> None:
    banner("정산 결과", "hq")
    icons = {"settled": "✅", "scheduled": "🕐", "paid": "💸", "issued": "📄", "disputed": "⚖️", "refused": "🚫", "pending_approval": "🙋"}
    for inv in sorted(db.list_docs("invoices"), key=lambda d: d["updated_at"]):
        print(f"  {icons.get(inv['status'], '•')} {inv['id']}  {inv['store_id']:9} "
              f"{inv['amount_usdc']:>7.2f} USDC  {inv['status']}")
        if inv.get("tx_sig"):
            print(f"     {C['dim']}tx {inv['tx_sig'][:48]}…{C['0']}")

    negotiations = db.list_docs("negotiations")
    print(f"\n  협상 {len(negotiations)}건 · 실행 증빙 이벤트 {len(db.list_events())}건")
    for neg in negotiations:
        print(f"    {C['dim']}· [{neg['type']}] {neg['decision']} — {neg['reasoning'][:64]}{C['0']}")
    print(f"\n  {C['bold']}사람이 누른 버튼: 0회{C['0']}")
    print(f"  {C['dim']}대시보드: http://localhost:8080{C['0']}\n")


async def main() -> None:
    parser = argparse.ArgumentParser(description="Solply 데모")
    parser.add_argument("--only", choices=["a", "b", "c"], help="한 시나리오만 실행")
    parser.add_argument("--keep", action="store_true", help="기존 상태를 유지")
    args = parser.parse_args()

    if not args.keep:
        db.reset(keep=("policies",))  # 사용자가 설정한 거래 정책은 남긴다

    banner("SOLPLY — 프랜차이즈 식자재 대금 자율 정산", "hq")
    mode = "규칙 기반(mock)" if config.LLM_PROVIDER == "mock" else f"{config.LLM_PROVIDER} · {config.HQ_MODEL}"
    print(f"  판단 주체: {mode} · 네트워크: {config.NETWORK} · 저장소: {config.STORE_BACKEND}")
    print(f"  {C['dim']}대시보드를 띄워두면 활동이 실시간으로 표시됩니다 → http://localhost:8080{C['0']}")

    scenarios = {"a": scenario_a, "b": scenario_b, "c": scenario_c}
    for key in [args.only] if args.only else ["a", "b", "c"]:
        try:
            await scenarios[key]()
        except Exception as exc:  # noqa: BLE001 — 하나가 죽어도 나머지는 계속
            print(f"  {C['dim']}시나리오 {key.upper()} 중단: {str(exc)[:200]}{C['0']}")

    summary()


if __name__ == "__main__":
    asyncio.run(main())
