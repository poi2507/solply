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


def is_receivable(status: str) -> bool:
    """이 청구서가 아직 받을 돈인가. 모르는 상태는 받을 돈으로 본다 —
    빠뜨려서 미수금이 실제보다 작아 보이는 쪽이 더 위험하다."""
    return status not in NOT_RECEIVABLE
