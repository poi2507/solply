"""납부 이력 기반 신용점수.

전에는 88/81/92가 fixtures에 박힌 상수였다. 이제 점수는 이력에서 계산된다 —
"납부 이력이 곧 신용"이라는 프로덕트 논거를 데모가 직접 증명한다.

  점수 = 기본 50 + 정시납 ×2 − 연체 ×3 − 분쟁 ×2   (0~100로 클램프)

이력은 두 겹이다:
  1) 시드 이력  fixtures의 payment_history — 데모 시작 전의 과거 (집계값)
  2) 라이브 이력 온체인 정산(settled)은 정시납으로 가산,
     24시간 넘게 미결로 남은 청구서는 연체로 감산

그래서 결제가 완료되면 점수가 오르고, 갚지 않고 버티면 내려간다.
devnet 전환 후에는 시드 이력을 지갑 트랜잭션 조회로 대체할 수 있다.
"""

from datetime import UTC, datetime, timedelta

from app.core import fixtures
from app.core.status import InvoiceStatus
from app.db import store as db

BASE = 50
ON_TIME_POINTS = 2

# 연체 = "납부 방법이 정해지지 않은 채" 이 시간을 넘긴 청구서.
# 예약(scheduled)은 납부일을 합의한 건이라 세지 않는다.
LATE_AFTER_HOURS = 48
# 사람 승인 대기(pending_approval)는 **지점의 연체가 아니다** — 심사가 늦어진 것이지
# 지점이 버틴 게 아니다. 이걸 연체로 세면 되먹임이 생긴다: 유예 거절 → 승인 큐 적체
# → 신용 하락 → 더 거절 (8/15 store-b 실측: 신용 73으로 유예 기준 85 미달, 큐 16건).
UNPLANNED: tuple[str, ...] = (
    InvoiceStatus.ISSUED, InvoiceStatus.DISPUTED,
)

# 정시납 가산의 상한. 누적으로만 쌓으면 몇백 건 뒤엔 원점수가 1400을 넘어
# 그 뒤의 연체가 점수에 전혀 보이지 않는다 — 미수 415 USDC·미결 144건인 지점이
# 만점이었다 (8/7 라이브). 상한을 두면 나쁜 이력이 실제로 점수를 움직인다.
ON_TIME_CAP = 25
LATE_PENALTY = 3
DISPUTE_PENALTY = 2


def score_from(on_time: int, late: int, disputed: int) -> int:
    """건수 → 점수. 정시납 가산에 상한이 있어 나쁜 이력이 항상 점수에 보인다."""
    raw = (BASE + ON_TIME_POINTS * min(on_time, ON_TIME_CAP)
           - LATE_PENALTY * late - DISPUTE_PENALTY * disputed)
    return max(0, min(100, raw))


def evaluate(store_id: str) -> dict:
    """이력에서 신용점수를 계산한다. 근거(정시납·연체·분쟁 건수)를 함께 돌려준다."""
    seeded = fixtures.load().get("payment_history", {}).get(store_id, {})
    # 건수만 필요하다 — 정산 이력이 수천 건 쌓여도 문서를 다 읽지 않는다
    live_settled = db.count_docs("invoices", store_id=store_id, status="settled")

    cutoff = (datetime.now(UTC) - timedelta(hours=LATE_AFTER_HOURS)).isoformat()
    live_late = db.count_stale("invoices", UNPLANNED, cutoff, store_id=store_id)

    on_time = int(seeded.get("on_time", 0)) + live_settled
    late = int(seeded.get("late", 0)) + live_late
    disputed = int(seeded.get("disputed", 0))

    return {
        "credit_score": score_from(on_time, late, disputed),
        "on_time": on_time,
        "late": late,
        "live_late": live_late,
        "disputed": disputed,
        "live_settled": live_settled,
        "note": seeded.get("note", ""),
    }
