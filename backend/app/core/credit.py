"""납부 이력 기반 신용점수.

전에는 88/81/92가 fixtures에 박힌 상수였다. 이제 점수는 이력에서 계산된다 —
"납부 이력이 곧 신용"이라는 프로덕트 논거를 데모가 직접 증명한다.

  점수 = 기본 50 + 정시납 ×2 − 연체 ×3 − 분쟁 ×2   (0~100로 클램프)

이력은 두 겹이다:
  1) 시드 이력  fixtures의 payment_history — 데모 시작 전의 과거 (집계값)
  2) 라이브 이력 이번 세션에서 온체인 정산(settled)된 청구서 — 정시납으로 가산

그래서 데모 중 결제가 완료되면 대시보드의 점수가 실제로 오른다.
devnet 전환 후에는 시드 이력을 지갑 트랜잭션 조회로 대체할 수 있다.
"""

from app.core import fixtures
from app.db import store as db

BASE = 50
ON_TIME_POINTS = 2
LATE_PENALTY = 3
DISPUTE_PENALTY = 2


def evaluate(store_id: str) -> dict:
    """이력에서 신용점수를 계산한다. 근거(정시납·연체·분쟁 건수)를 함께 돌려준다."""
    seeded = fixtures.load().get("payment_history", {}).get(store_id, {})
    # 건수만 필요하다 — 정산 이력이 수천 건 쌓여도 문서를 다 읽지 않는다
    live_settled = db.count_docs("invoices", store_id=store_id, status="settled")

    on_time = int(seeded.get("on_time", 0)) + live_settled
    late = int(seeded.get("late", 0))
    disputed = int(seeded.get("disputed", 0))

    score = BASE + ON_TIME_POINTS * on_time - LATE_PENALTY * late - DISPUTE_PENALTY * disputed
    return {
        "credit_score": max(0, min(100, score)),
        "on_time": on_time,
        "late": late,
        "disputed": disputed,
        "live_settled": live_settled,
        "note": seeded.get("note", ""),
    }
