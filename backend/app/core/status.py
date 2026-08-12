"""청구서 상태 — 단일 출처.

여기가 필요한 이유: "받을 돈"의 정의가 코드 두 곳에 **서로 반대 방향으로** 손으로
적혀 있었다. 대시보드는 받을 상태를 나열하고, 어시스턴트는 받지 않을 상태를
나열했다. 둘은 서로의 여집합이어야 하는데 사본이 두 개라, 상태가 하나 늘면
한쪽만 고쳐도 아무 에러 없이 **미수금 숫자가 갈라진다.**

그래서 한쪽만 손으로 적고 나머지는 파생시킨다.
"""

from enum import StrEnum


class InvoiceStatus(StrEnum):
    ISSUED = "issued"                      # 발행됨, 아직 미결
    PAID = "paid"                          # 지불했으나 본사 대조 전
    SETTLED = "settled"                    # 온체인 대조까지 끝난 확정
    DISPUTED = "disputed"                  # 검수 불일치로 협의 중
    SCHEDULED = "scheduled"                # 유예 합의로 납부일이 잡힘
    REFUSED = "refused"                    # 발주 없는 청구 — 거부하고 사람에게
    PENDING_APPROVAL = "pending_approval"  # 정책 상한 초과 — 사람 승인 대기
    SPLIT = "split"                        # 분할됨 (자식 청구서가 대신 받는다)


# 받을 돈이 아닌 상태. 여기만 손으로 적는다.
#   settled — 이미 받았다
#   split   — 자식 청구서가 대신 받으므로 부모를 세면 이중 계산이 된다
#   refused — 분쟁 확인 대기지 수취 채권이 아니다
NOT_RECEIVABLE: tuple[InvoiceStatus, ...] = (
    InvoiceStatus.SETTLED,
    InvoiceStatus.SPLIT,
    InvoiceStatus.REFUSED,
)

# 받을 돈인 상태 — 위의 여집합으로 **파생**시킨다 (사본을 만들지 않는다)
RECEIVABLE: tuple[InvoiceStatus, ...] = tuple(
    s for s in InvoiceStatus if s not in NOT_RECEIVABLE
)

# 화면 표기 — 프론트가 자기 사본을 들지 않도록 API가 내려준다
LABELS: dict[str, str] = {
    InvoiceStatus.ISSUED: "발행",
    InvoiceStatus.PAID: "결제됨",
    InvoiceStatus.SETTLED: "정산완료",
    InvoiceStatus.DISPUTED: "협의중",
    InvoiceStatus.SCHEDULED: "예약",
    InvoiceStatus.REFUSED: "거부",
    InvoiceStatus.PENDING_APPROVAL: "승인 대기",
    InvoiceStatus.SPLIT: "분할됨",
}


# 이미 돈이 나간 상태 — 이중 결제 방지 가드가 본다.
# 여기에 상태를 빠뜨리면 재시도 한 번에 돈이 두 번 나간다.
ALREADY_PAID: tuple[InvoiceStatus, ...] = (
    InvoiceStatus.PAID,
    InvoiceStatus.SETTLED,
)


# 지점이 아직 손을 써야 하는 상태 — 지점 에이전트의 "내 미결 청구서" 도구가 본다.
#   paid  — 이미 돈을 보내고 본사 대조를 기다리는 중이라 행동할 게 없다
#   split — 자식 청구서가 대신 받으므로 부모까지 세면 이중 계산이 된다
ACTIONABLE: tuple[InvoiceStatus, ...] = tuple(
    s for s in RECEIVABLE if s is not InvoiceStatus.PAID
)


def is_receivable(status: str) -> bool:
    """이 청구서가 아직 받을 돈인가. 모르는 상태는 받을 돈으로 본다 —
    빠뜨려서 미수금이 실제보다 작아 보이는 쪽이 더 위험하다."""
    return status not in NOT_RECEIVABLE


class TradeStatus(StrEnum):
    """지점 간 직거래의 상태 — 아래 순서대로 진행한다.

    proposed → accepted → approved → confirmed
      (구매측 제안)  (판매측 수락)  (본사 승인)  (온체인 결제 후 확정)
    수락·승인 어느 단계에서든 거절되면 rejected로 끝난다.
    """

    PROPOSED = "proposed"    # 구매 지점이 제안
    ACCEPTED = "accepted"    # 판매 지점이 수락 (안전재고를 지키고도 팔 수 있음)
    REJECTED = "rejected"    # 판매측 또는 본사가 거절
    APPROVED = "approved"    # 본사 승인 — 결제의 전제
    ESCROWED = "escrowed"    # 구매 대금이 본사 에스크로에 예치됨 (인도 확인 대기)
    CONFIRMED = "confirmed"  # 인도 확인 후 에스크로가 판매측에 지급 — 거래 종결
    REFUNDED = "refunded"    # 인도 실패 — 에스크로가 구매측에 환불


TRADE_LABELS: dict[str, str] = {
    TradeStatus.PROPOSED: "제안됨",
    TradeStatus.ACCEPTED: "수락",
    TradeStatus.REJECTED: "거절",
    TradeStatus.APPROVED: "본사 승인",
    TradeStatus.ESCROWED: "에스크로 예치",
    TradeStatus.CONFIRMED: "확정",
    TradeStatus.REFUNDED: "환불됨",
}
