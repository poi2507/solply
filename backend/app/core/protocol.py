"""x402 (HTTP 402 Payment Required) 프로토콜 구현.

Solply에서의 매핑:
  - 판매자(resource server) = 본사. "정산 확정"이 유료 리소스다.
  - 구매자(client)          = 가맹점 에이전트.
  - 402 응답의 accepts[]    = 협상 조건 목록 (즉시납 / 유예 / 분할)

핵심 아이디어: x402 스펙의 `accepts` 는 배열이라 하나의 리소스에 복수 결제 조건을
제시할 수 있다. 우리는 여기에 협상 옵션을 담아 **표준 안에서 협상을 표현**한다.

참고: https://docs.x402.org/introduction (v2 헤더 규약)
"""

import base64
import json
from datetime import UTC, datetime, timedelta
from typing import Any

X402_VERSION = 2

# CAIP-2 네트워크 식별자
NETWORKS = {
    "localnet": "solana:localnet",
    "devnet": "solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1",
    "mainnet-beta": "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp",
}
USDC_DECIMALS = 6


def to_atomic(amount_usdc: float) -> str:
    """USDC 금액을 atomic units 문자열로 (스펙 요구사항)."""
    return str(round(amount_usdc * 10**USDC_DECIMALS))


def from_atomic(amount: str) -> float:
    return int(amount) / 10**USDC_DECIMALS


def encode_header(payload: dict[str, Any]) -> str:
    """헤더 값은 base64로 인코딩된 JSON."""
    return base64.b64encode(json.dumps(payload, ensure_ascii=False).encode()).decode()


def decode_header(value: str) -> dict[str, Any]:
    return json.loads(base64.b64decode(value).decode())


def build_payment_requirements(
    invoice: dict, hq_address: str, network: str, store_profile: dict | None = None
) -> dict:
    """402 응답 본문 = PaymentRequirements.

    accepts[]에 협상 옵션을 담는다. 가맹점 에이전트는 이 중 하나를 선택하거나,
    검수 불일치를 근거로 조정을 역제안한다.
    """
    amount = invoice["amount_usdc"]
    caip2 = NETWORKS.get(network, NETWORKS["localnet"])
    now = datetime.now(UTC)
    policy = (store_profile or {}).get("policy", {})
    defer_max_pct = policy.get("defer_max_pct", 20)
    installment_max = policy.get("installment_max", 2)

    accepts = [
        {
            "scheme": "exact",
            "network": caip2,
            "amount": to_atomic(amount),
            "asset": "USDC",
            "payTo": hq_address,
            "maxTimeoutSeconds": 60,
            "extra": {
                "term": "immediate",
                "label": "즉시 납부",
                "memo": invoice["id"],
            },
        }
    ]

    # 분할 합의의 회차 청구서에는 유예·재분할을 다시 제시하지 않는다 —
    # 이미 협상이 끝난 조건이라, 재협상 여지를 남기면 합의가 무한 후퇴한다.
    if invoice.get("installment"):
        accepts[0]["extra"]["label"] = f"분할 {invoice['installment']}회차 납부"
        return _wrap_requirements(invoice, accepts)

    # 유예: 청구액이 정책 한도(신용 기반) 안일 때만 제시
    accepts.append(
        {
            "scheme": "exact",
            "network": caip2,
            "amount": to_atomic(amount),
            "asset": "USDC",
            "payTo": hq_address,
            "maxTimeoutSeconds": 60,
            "extra": {
                "term": "deferred",
                "label": "납부 유예 (본사 심사 필요)",
                "memo": invoice["id"],
                "notBefore": (now + timedelta(days=1)).isoformat(),
                "requiresApproval": True,
                "policyHint": f"외상 한도의 {defer_max_pct}% 이내 & 납부기한 내면 자동 수락",
            },
        }
    )

    # 분할 — 회차는 본사 정책(installment_max)이 정한다.
    # 여기에 2를 박아두면 정책이 3일 때 "2회 분할·절반 금액"을 제시하고 실제로는
    # 3등분 청구서가 생겨, 지점이 어느 청구서와도 맞지 않는 금액을 보낸다 (USDC 유실).
    parts = max(1, int(installment_max))
    per = round(amount / parts, 2)
    accepts.append(
        {
            "scheme": "exact",
            "network": caip2,
            "amount": to_atomic(per),
            "asset": "USDC",
            "payTo": hq_address,
            "maxTimeoutSeconds": 60,
            "extra": {
                "term": "installment",
                "label": f"{parts}회 분할 (회당 {per} USDC)",
                "memo": invoice["id"],
                "installments": parts,
                "requiresApproval": True,
                "policyHint": f"본사 정책상 최대 {installment_max}회까지 허용",
            },
        }
    )

    return _wrap_requirements(invoice, accepts)


def _wrap_requirements(invoice: dict, accepts: list[dict]) -> dict:
    return {
        "x402Version": X402_VERSION,
        "accepts": accepts,
        "resource": {
            "url": f"/x402/invoices/{invoice['id']}/settle",
            "description": f"식자재 대금 정산 — {invoice['store_id']} / {invoice['delivery_id']}",
            "mimeType": "application/json",
        },
        # 표준 외 확장: 우리가 청구 근거를 함께 실어 보낸다 (검수 대조용)
        "extensions": {
            "solply.invoice": {
                "id": invoice["id"],
                "storeId": invoice["store_id"],
                "deliveryId": invoice["delivery_id"],
                "items": invoice["items"],
                "amountUsdc": invoice["amount_usdc"],
            }
        },
    }


def build_trade_requirements(trade: dict, seller_address: str, network: str) -> dict:
    """지점 간 직거래의 402 — 이번엔 판매 지점이 resource server다.

    본사-가맹점 정산과 같은 규약을 그대로 쓴다. x402가 세로(본사↔지점)와
    가로(지점↔지점) 정산을 한 프로토콜로 관통한다는 게 포인트다.
    """
    caip2 = NETWORKS.get(network, NETWORKS["localnet"])
    return {
        "x402Version": X402_VERSION,
        "accepts": [
            {
                "scheme": "exact",
                "network": caip2,
                "amount": to_atomic(trade["price_usdc"]),
                "asset": "USDC",
                "payTo": seller_address,
                "maxTimeoutSeconds": 60,
                "extra": {
                    "term": "immediate",
                    "label": f"직거래 대금 즉시 납부 ({trade['name']} ×{trade['qty']})",
                    "memo": trade["id"],
                },
            }
        ],
        "resource": {
            "url": f"/x402/trades/{trade['id']}/settle",
            "description": f"지점 간 재고 직거래 — {trade['buyer_id']} → {trade['seller_id']}",
            "mimeType": "application/json",
        },
        "extensions": {
            "solply.trade": {
                "id": trade["id"],
                "sku": trade["sku"],
                "qty": trade["qty"],
                "buyerId": trade["buyer_id"],
                "sellerId": trade["seller_id"],
                "amountUsdc": trade["price_usdc"],
            }
        },
    }


def build_settlement_response(invoice_id: str, signature: str, verified: bool, explorer: str) -> dict:
    """정산 완료 응답 = SettlementResponse (PAYMENT-RESPONSE 헤더에 실린다)."""
    return {
        "x402Version": X402_VERSION,
        "verified": verified,
        "settled": verified,
        "transaction": signature,
        "invoiceId": invoice_id,
        "explorer": explorer,
    }
