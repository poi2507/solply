"""실행 증빙 로그의 행위 이름 — 단일 출처.

여기가 필요한 이유: 화면 라벨이 프론트에만 손으로 적혀 있었고, 경제 루프와
지점 간 직거래가 나중에 들어오면서 **라벨이 따라오지 않았다.** 그 결과 라이브
실행 로그의 69%가 `p2p.recorded`, `inventory.sold`처럼 영문 원문으로 보였다.
심사 기준 4의 증빙 화면인데 절반 넘게 읽히지 않았던 것이다.

이제 백엔드가 라벨을 내려주고(`/api/overview` → `actionLabels`), 테스트가
"코드가 기록하는 모든 행위에 라벨이 있는가"를 검사한다. 새 행위를 추가하고
라벨을 빼먹으면 테스트가 실패한다.
"""

ACTION_LABELS: dict[str, str] = {
    "auth.passkey_registered": "패스키 등록",
    "auth.passkey_reset": "패스키 초기화",
    "auth.passkey_login": "패스키 본인확인",
    "p2p.escrow_deposited": "에스크로 예치",
    "p2p.released": "에스크로 지급",
    "p2p.refunded": "에스크로 환불",
    "p2p.delivery_failed": "인도 실패",
    "shop.sale": "손님 구매 결제",
    "shop.pay_failed": "손님 결제 실패",
    # 청구서
    "invoice.created": "청구서 발행",
    "invoice.adjusted": "청구 금액 정정",
    "invoice.split": "분할 청구서 생성",
    "delivery.verified": "검수 대조",
    # 협상
    "proposal.adjustment": "차감 제안",
    "proposal.deferral": "유예 제안",
    "proposal.reviewed": "본사 심사",
    "proposal.counter_response": "역제안 응답 (지점)",
    "negotiation.failed": "협상 결렬 (사람에게)",
    # 결제
    "payment.executed": "결제 실행",
    "payment.verified": "수금 검증",
    "payment.mismatch": "검증 불일치",
    "payment.refused": "결제 거부",
    "payment.blocked_over_limit": "한도 초과 차단",
    "payment.needs_approval": "사람 승인 요청",
    "payment.failed": "결제 실패 (재시도 예정)",
    # x402 왕복
    "x402.payment_required": "x402 결제 요구 (402)",
    "x402.terms_received": "x402 조건 수신",
    "x402.settled": "x402 정산 완료",
    "x402.verification_failed": "x402 검증 실패",
    # 사람 개입
    "human.approved": "사람이 승인",
    "human.rejected": "사람이 반려",
    "policy.updated": "거래 정책 변경",
    # 지점 간 직거래
    "p2p.proposed": "직거래 제안",
    "p2p.responded": "직거래 응답",
    "p2p.reviewed": "본사 직거래 심사",
    "p2p.payment_required": "직거래 대금 요구",
    "p2p.paid": "직거래 대금 결제",
    "p2p.recorded": "직거래 장부 반영",
    "p2p.verification_failed": "직거래 검증 실패",
    "p2p.blocked_over_limit": "직거래 한도 초과 차단",
    "p2p.blocked_unapproved": "본사 미승인 직거래 차단",
    # 라이브 경제 루프
    # 데이터 판매 (본사가 x402 판매자가 된다)
    "data.quoted": "데이터 판매 견적 (402)",
    "data.sold": "데이터 판매 (x402 정산)",

    # 에이전트 간 표준 왕복 (A2A)
    "a2a.message": "A2A 메시지 (message/send)",

    "inventory.sold": "판매 (재고 차감)",
    "card.settled": "카드매출 정산 지급",
    "card.charged": "손님 카드매출 수납 (시뮬)",
    "card.settle_failed": "카드정산 지급 실패 (재시도 예정)",
    "warehouse.restocked": "본사 창고 재입고",
    "market.quote_purchased": "시세 데이터 구매 (pay.sh)",
    "tick.completed": "경제 루프 한 바퀴",
}


# 재고 원장의 이동 사유 — 같은 이유로 여기 둔다.
# 프론트에만 적혀 있었고 `restocked`(본사 창고 재입고)가 빠져 있어서
# 본사 화면에 영문 원문이 그대로 보였다.
MOVE_LABELS: dict[str, str] = {
    "received": "입고",
    "shipped": "출고",
    "sold": "판매",
    "p2p_in": "직거래 입고",
    "p2p_out": "직거래 출고",
    "restocked": "창고 재입고",
}


def label(action: str) -> str:
    """라벨이 없으면 원문을 돌려준다 — 화면이 비는 것보다 영문이라도 보이는 게 낫다."""
    return ACTION_LABELS.get(action, action)
