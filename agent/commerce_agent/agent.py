"""Agentic Commerce 루트 에이전트.

Gemini가 두뇌, Solana가 결제 레이어. 결제 실행은 payments/ 서비스(TypeScript)의
HTTP API를 도구로 호출한다. 자율 결제는 AGENT_SPEND_LIMIT_USDC 한도 내에서만 허용.
"""

import os

import httpx
from dotenv import load_dotenv
from google.adk.agents import Agent

load_dotenv()

PAYMENTS_API = os.getenv("PAYMENTS_API_URL", "http://localhost:3000")
SPEND_LIMIT = float(os.getenv("AGENT_SPEND_LIMIT_USDC", "10"))


def get_wallet_balance() -> dict:
    """에이전트 지갑의 SOL / USDC 잔액을 조회한다."""
    resp = httpx.get(f"{PAYMENTS_API}/balance", timeout=10)
    resp.raise_for_status()
    return resp.json()


def send_payment(recipient: str, amount_usdc: float, memo: str) -> dict:
    """Solana devnet에서 USDC 결제를 실행한다.

    Args:
        recipient: 수취인 지갑 주소 (base58)
        amount_usdc: 결제 금액 (USDC)
        memo: 결제 사유 (온체인 메모로 기록)
    """
    if amount_usdc > SPEND_LIMIT:
        return {
            "status": "rejected",
            "reason": f"결제 한도 초과: {amount_usdc} USDC > 한도 {SPEND_LIMIT} USDC. 사람 승인이 필요합니다.",
        }
    resp = httpx.post(
        f"{PAYMENTS_API}/pay",
        json={"recipient": recipient, "amount": amount_usdc, "memo": memo},
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()


root_agent = Agent(
    name="commerce_agent",
    model="gemini-2.5-flash",
    description="한도 내에서 스스로 판단하고 Solana로 결제까지 실행하는 커머스 에이전트",
    instruction=(
        "너는 사용자를 대신해 구매·결제를 수행하는 자율 커머스 에이전트다. "
        f"건당 {SPEND_LIMIT} USDC 한도 내에서는 승인 없이 결제를 실행하고, "
        "한도를 넘으면 반드시 사용자에게 확인을 요청해라. "
        "결제 전에는 잔액을 확인하고, 결제 후에는 트랜잭션 서명(signature)과 "
        "explorer 링크를 사용자에게 보고해라."
    ),
    tools=[get_wallet_balance, send_payment],
)
