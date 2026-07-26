"""Solply 데모 오케스트레이터.

가맹점 3곳의 시나리오를 순차 실행한다. 사람은 아무 버튼도 누르지 않는다.

  A지점 — 검수 일치 → 즉시 자율 결제
  B지점 — 검수 불일치 → 차감 협상 → 조정 결제
  C지점 — 잔액 부족 → 유예 협상 → 예약

대시보드(http://localhost:8080)를 띄워놓고 실행하면 활동이 실시간으로 찍힌다.

  make demo        Gemini 판단 (실제 심사용, 느림)
  make demo-mock   규칙 기반 (리허설용, 빠름 — 온체인 결제는 동일하게 발생)
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app import config
from app.agents import hq as hq_mod
from app.agents import store as store_mod
from app.agents.runner import latest_event, run_agent
from app.db import store as db

C = {
    "hq": "\033[36m", "a": "\033[32m", "b": "\033[33m", "c": "\033[35m",
    "dim": "\033[90m", "bold": "\033[1m", "0": "\033[0m",
}


def banner(text: str, color: str = "0") -> None:
    print(f"\n{C[color]}{C['bold']}{'━' * 74}\n  {text}\n{'━' * 74}{C['0']}")


def reporter(tag: str, color: str):
    def on_tool(name: str, args: dict) -> None:
        shown = ", ".join(f"{k}={v}" for k, v in args.items() if k != "items")
        print(f"  {C[color]}[{tag}]{C['0']} {C['dim']}🔧 {name}({shown}){C['0']}")

    def on_text(text: str) -> None:
        for line in text.splitlines():
            if line.strip():
                print(f"  {C[color]}[{tag}]{C['0']} {line.strip()}")

    return on_tool, on_text


async def ask(agent, prompt: str, tag: str, color: str) -> str:
    on_tool, on_text = reporter(tag, color)
    return await run_agent(agent, prompt, on_tool=on_tool, on_text=on_text)


def newest_open_invoice(store_id: str) -> dict | None:
    docs = [d for d in db.list_docs("invoices", store_id=store_id) if d["status"] != "settled"]
    return sorted(docs, key=lambda d: d["updated_at"])[-1] if docs else None


async def scenario_a(hq) -> None:
    banner("A지점 (강남) — 검수 일치, 즉시 자율 결제", "a")
    await ask(hq, "A지점 납품 DEL-001이 완료됐습니다. 청구서를 발행하세요.", "본사", "hq")

    invoice = newest_open_invoice("store-a")
    if not invoice:
        return print("  청구서 생성 실패 — 건너뜁니다")

    await ask(
        store_mod.build("store-a"),
        f"본사에서 청구서 {invoice['id']}가 도착했습니다. 검수 대조부터 결제까지 처리하세요.",
        "A지점", "a",
    )

    invoice = db.get("invoices", invoice["id"])
    if invoice.get("tx_sig"):
        await ask(
            hq,
            f"A지점이 청구서 {invoice['id']}를 결제했습니다. "
            f"트랜잭션 {invoice['tx_sig']}를 검증하고 정산을 확정하세요.",
            "본사", "hq",
        )


async def scenario_b(hq) -> None:
    banner("B지점 (홍대) — 검수 불일치 발견, 차감 협상", "b")
    await ask(hq, "B지점 납품 DEL-002가 완료됐습니다. 청구서를 발행하세요.", "본사", "hq")

    invoice = newest_open_invoice("store-b")
    if not invoice:
        return print("  청구서 생성 실패 — 건너뜁니다")

    agent_b = store_mod.build("store-b")
    await ask(
        agent_b,
        f"본사에서 청구서 {invoice['id']}가 도착했습니다. 검수 대조부터 처리하세요.",
        "B지점", "b",
    )

    proposal = latest_event(db.list_events(), "proposal.adjustment")
    if not proposal:
        return print(f"  {C['dim']}차감 제안이 나오지 않았습니다{C['0']}")

    await ask(
        hq,
        f"B지점이 청구서 {invoice['id']}에 대해 차감을 제안했습니다. "
        f"사유: {proposal['reason']} / 차감 요청액: {proposal['deduction_usdc']} USDC. "
        "납품 데이터와 대조해 심사하고, 합당하면 금액을 조정해 재발행하세요.",
        "본사", "hq",
    )

    invoice = db.get("invoices", invoice["id"])
    await ask(
        agent_b,
        f"본사가 청구서 {invoice['id']}를 {invoice['amount_usdc']} USDC로 조정했습니다. 결제하세요.",
        "B지점", "b",
    )

    invoice = db.get("invoices", invoice["id"])
    if invoice.get("tx_sig"):
        await ask(
            hq,
            f"B지점이 청구서 {invoice['id']}를 결제했습니다. "
            f"트랜잭션 {invoice['tx_sig']}를 검증하고 정산을 확정하세요.",
            "본사", "hq",
        )


async def scenario_c(hq) -> None:
    banner("C지점 (부산) — 잔액 부족, 유예 협상", "c")
    await ask(hq, "C지점 납품 DEL-003이 완료됐습니다. 청구서를 발행하세요.", "본사", "hq")

    invoice = newest_open_invoice("store-c")
    if not invoice:
        return print("  청구서 생성 실패 — 건너뜁니다")

    await ask(
        store_mod.build("store-c"),
        f"본사에서 청구서 {invoice['id']}가 도착했습니다. 검수 대조부터 처리하세요.",
        "C지점", "c",
    )

    proposal = latest_event(db.list_events(), "proposal.deferral")
    if not proposal:
        return print(f"  {C['dim']}유예 제안이 나오지 않았습니다{C['0']}")

    await ask(
        hq,
        f"C지점이 청구서 {invoice['id']}에 대해 납부 유예를 제안했습니다. "
        f"납부 예정: {proposal['pay_when']} / 사유: {proposal['reason']}. "
        "C지점 신용점수와 정책을 확인해 심사하고 결정을 기록하세요.",
        "본사", "hq",
    )


def summary() -> None:
    banner("정산 결과", "hq")
    icons = {"settled": "✅", "scheduled": "🕐", "paid": "💸", "issued": "📄", "disputed": "⚖️", "refused": "🚫"}
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
        db.reset()

    banner("SOLPLY — 프랜차이즈 식자재 대금 자율 정산", "hq")
    mode = "규칙 기반(mock)" if config.LLM_PROVIDER == "mock" else f"Gemini ({config.HQ_MODEL})"
    print(f"  판단 주체: {mode} · 네트워크: {config.NETWORK}")
    print(f"  {C['dim']}대시보드를 띄워두면 활동이 실시간으로 표시됩니다 → http://localhost:8080{C['0']}")

    hq = hq_mod.build()
    scenarios = {"a": scenario_a, "b": scenario_b, "c": scenario_c}
    for key in [args.only] if args.only else ["a", "b", "c"]:
        try:
            await scenarios[key](hq)
        except Exception as exc:  # noqa: BLE001 — 하나가 죽어도 나머지는 계속
            print(f"  {C['dim']}시나리오 {key.upper()} 중단: {str(exc)[:160]}{C['0']}")

    summary()


if __name__ == "__main__":
    asyncio.run(main())
