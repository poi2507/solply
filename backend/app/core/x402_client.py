"""x402 클라이언트 — 가맹점 에이전트가 본사 정산 엔드포인트와 왕복한다.

x402의 구매자(client) 쪽 절반. 판매자(resource server) 쪽은 `app/api/x402.py`.

  fetch_terms      GET  → 402 + accepts[] (결제 조건 = 협상 옵션)
  submit_payment   POST → 결제 서명을 PAYMENT-SIGNATURE 헤더로 제출, 정산 확정을 받는다

데모에서는 같은 FastAPI 앱을 HTTP로 다시 부른다 — 에이전트와 본사가 실제로는
다른 프로세스(나중엔 다른 회사)에 있다는 걸 왕복 자체로 보여주기 위해서다.
"""

import httpx

from app import config
from app.core import protocol

_BASE = config.SOLPLY_API_URL


def fetch_terms(invoice_id: str) -> dict:
    """정산을 요청하고 402 응답의 PaymentRequirements를 돌려받는다."""
    resp = httpx.get(f"{_BASE}/x402/invoices/{invoice_id}/settle", timeout=15)
    if resp.status_code == 402:
        return resp.json()
    resp.raise_for_status()
    return resp.json()  # 이미 정산된 경우 등 200 응답


def submit_payment(invoice_id: str, signature: str) -> dict:
    """결제 서명을 제출한다. 본사가 온체인 대조 후 정산을 확정하면 영수증이 온다."""
    return _submit(f"/x402/invoices/{invoice_id}/settle", signature)


def fetch_trade_terms(trade_id: str) -> dict:
    """직거래 대금 결제 조건을 판매 지점(resource server)에서 받아온다."""
    resp = httpx.get(f"{_BASE}/x402/trades/{trade_id}/settle", timeout=15)
    if resp.status_code == 402:
        return resp.json()
    resp.raise_for_status()
    return resp.json()


def submit_trade_payment(trade_id: str, signature: str) -> dict:
    """직거래 결제 서명을 제출한다. 판매 지점 검증이 끝나면 재고 인수가 확정된다."""
    return _submit(f"/x402/trades/{trade_id}/settle", signature)


def _submit(path: str, signature: str) -> dict:
    header = protocol.encode_header(
        {"x402Version": protocol.X402_VERSION, "payload": {"signature": signature}}
    )
    resp = httpx.post(f"{_BASE}{path}", headers={"PAYMENT-SIGNATURE": header}, timeout=60)
    body = resp.json()
    return {"status_code": resp.status_code, **body}
