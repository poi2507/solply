"""Solply 데모 오케스트레이터.

가맹점 3곳의 시나리오를 순차 실행한다. 사람은 아무 버튼도 누르지 않는다.

  A지점 — 검수 일치 → 즉시 자율 결제
  B지점 — 검수 불일치 → 차감 협상 → 조정 결제
  C지점 — 잔액 부족 → 유예 협상 → 예약 → 예약 실행

사용법:
  터미널1: solana-test-validator --reset --clone MemoSq4... --url mainnet-beta
  터미널2: cd payments && npm run dev
  터미널3: cd agent && uv run python demo.py
"""

import asyncio
import importlib
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
from google.adk.runners import InMemoryRunner
from google.genai import types

load_dotenv()

C = {"hq": "\033[36m", "a": "\033[32m", "b": "\033[33m", "c": "\033[35m", "0": "\033[0m", "d": "\033[90m"}


def banner(text: str, color: str = "0") -> None:
    print(f"\n{C[color]}{'━' * 72}\n  {text}\n{'━' * 72}{C['0']}")


async def ask(agent, prompt: str, tag: str, color: str) -> str:
    """에이전트에게 지시하고, 도구 호출과 응답을 중계한다."""
    runner = InMemoryRunner(agent=agent, app_name="solply")
    session = await runner.session_service.create_session(app_name="solply", user_id="demo")
    msg = types.Content(role="user", parts=[types.Part(text=prompt)])
    final = ""
    async for event in runner.run_async(user_id="demo", session_id=session.id, new_message=msg):
        if not (event.content and event.content.parts):
            continue
        for part in event.content.parts:
            if part.function_call:
                args = {k: v for k, v in dict(part.function_call.args).items() if k != "items"}
                print(f"  {C[color]}[{tag}]{C['0']} {C['d']}🔧 {part.function_call.name}({json.dumps(args, ensure_ascii=False)}){C['0']}")
            elif part.text and part.text.strip():
                final = part.text.strip()
    if final:
        print(f"  {C[color]}[{tag}]{C['0']} {final}")
    return final


def store_agent_for(store_id: str):
    """지점별 에이전트 인스턴스를 만든다 (같은 코드, 정책·지갑만 다름)."""
    os.environ["STORE_ID"] = store_id
    import store_agent.agent as mod

    return importlib.reload(mod).root_agent


def open_invoice_for(store_id: str) -> dict | None:
    from solply import state

    docs = state.list_docs("invoices", store_id=store_id)
    pending = [d for d in docs if d["status"] not in ("settled", "refused")]
    return pending[-1] if pending else None


async def main() -> None:
    from hq_agent.agent import root_agent as hq
    from solply import state

    Path("data/state.json").unlink(missing_ok=True)

    banner("SOLPLY — 프랜차이즈 식자재 대금 자율 정산 데모", "hq")
    print("  본사 에이전트 1대 + 가맹점 에이전트 3대가 사람 개입 없이 정산을 완결합니다.\n")

    # ── 시나리오 A: 정상 플로우 ──────────────────────────────────
    banner("A지점 (강남) — 검수 일치, 즉시 자율 결제", "a")
    await ask(hq, "A지점 납품 DEL-001이 완료됐습니다. 청구서를 발행하세요.", "본사", "hq")
    inv_a = open_invoice_for("store-a")
    await ask(
        store_agent_for("store-a"),
        f"본사에서 청구서 {inv_a['id']}가 도착했습니다. 검수 대조부터 결제까지 처리하세요.",
        "A지점", "a",
    )
    inv_a = state.get("invoices", inv_a["id"])
    if inv_a.get("tx_sig"):
        await ask(hq, f"A지점이 청구서 {inv_a['id']}를 결제했다고 합니다. 트랜잭션 {inv_a['tx_sig']}를 검증하고 정산을 확정하세요.", "본사", "hq")

    # ── 시나리오 B: 차감 협상 ────────────────────────────────────
    banner("B지점 (홍대) — 검수 불일치 발견, 차감 협상", "b")
    await ask(hq, "B지점 납품 DEL-002가 완료됐습니다. 청구서를 발행하세요.", "본사", "hq")
    inv_b = open_invoice_for("store-b")
    agent_b = store_agent_for("store-b")
    await ask(
        agent_b,
        f"본사에서 청구서 {inv_b['id']}가 도착했습니다. 검수 대조부터 처리하세요.",
        "B지점", "b",
    )
    negotiation = [e for e in json.loads(Path("data/state.json").read_text())["events"] if e["action"] == "proposal.adjustment"]
    if negotiation:
        prop = negotiation[-1]["payload"]
        await ask(
            hq,
            f"B지점이 청구서 {inv_b['id']}에 대해 차감을 제안했습니다: {prop['reason']} (차감 {prop['deduction_usdc']} USDC). "
            "납품 데이터와 대조해 심사하고, 합당하면 금액을 조정해 재발행하세요.",
            "본사", "hq",
        )
        inv_b = state.get("invoices", inv_b["id"])
        await ask(agent_b, f"본사가 청구서 {inv_b['id']}를 {inv_b['amount_usdc']} USDC로 조정했습니다. 결제하세요.", "B지점", "b")
        inv_b = state.get("invoices", inv_b["id"])
        if inv_b.get("tx_sig"):
            await ask(hq, f"B지점이 결제했습니다. 트랜잭션 {inv_b['tx_sig']}를 검증하고 정산을 확정하세요.", "본사", "hq")

    # ── 시나리오 C: 유예 협상 ────────────────────────────────────
    banner("C지점 (부산) — 잔액 부족, 유예 협상", "c")
    await ask(hq, "C지점 납품 DEL-003이 완료됐습니다. 청구서를 발행하세요.", "본사", "hq")
    inv_c = open_invoice_for("store-c")
    await ask(
        store_agent_for("store-c"),
        f"본사에서 청구서 {inv_c['id']}가 도착했습니다. 검수 대조부터 처리하세요.",
        "C지점", "c",
    )
    deferrals = [e for e in json.loads(Path("data/state.json").read_text())["events"] if e["action"] == "proposal.deferral"]
    if deferrals:
        prop = deferrals[-1]["payload"]
        await ask(
            hq,
            f"C지점이 청구서 {inv_c['id']}에 대해 납부 유예를 제안했습니다: {prop['pay_when']}에 납부, 사유는 {prop['reason']}. "
            "C지점 신용점수와 정책을 확인해 심사하세요.",
            "본사", "hq",
        )

    # ── 정산 요약 ────────────────────────────────────────────────
    banner("정산 결과", "hq")
    data = json.loads(Path("data/state.json").read_text())
    for inv in data["invoices"].values():
        icon = {"settled": "✅", "scheduled": "🕐", "paid": "💸", "issued": "📄", "refused": "🚫"}.get(inv["status"], "•")
        line = f"  {icon} {inv['id']}  {inv['store_id']:9} {inv['amount_usdc']:>7.2f} USDC  {inv['status']}"
        if inv.get("tx_sig"):
            line += f"\n     {C['d']}tx {inv['tx_sig'][:44]}…{C['0']}"
        print(line)
    print(f"\n  실행 증빙 이벤트 {len(data['events'])}건 · 협상 {len(data['negotiations'])}건")
    print(f"  {C['d']}사람이 누른 버튼: 0회{C['0']}\n")


if __name__ == "__main__":
    asyncio.run(main())
