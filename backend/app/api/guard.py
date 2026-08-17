"""쓰기 보호 — 관리 토큰과 횟수 제한.

읽기는 전부 공개다(심사위원이 구경하는 대시보드가 제품이다). 상태를 바꾸는
문에만 자물쇠를 건다. 운영자 토큰 하나로 충분한 이유: 쓰는 주체가 우리뿐이다
— 운영자 브라우저·Cloud Scheduler·데모 잡·A2A 자기 호출. 손님 구매는 참여
동선이라 토큰 대신 횟수 제한으로 지킨다.

토큰이 비어 있으면(로컬 개발·테스트) 잠그지 않는다 — 운영에서만 env로 켠다.
"""

import secrets
import time
from collections import defaultdict, deque

from fastapi import Header, HTTPException, Request

from app import config


def require_admin(
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> None:
    if not config.ADMIN_TOKEN:
        return
    if not (x_admin_token and secrets.compare_digest(x_admin_token, config.ADMIN_TOKEN)):
        raise HTTPException(401, "관리 토큰이 필요합니다 (X-Admin-Token 헤더)")


# 횟수 제한 — 인스턴스 메모리 창(60초). 완벽한 분산 제한이 아니라 남용 감속이
# 목적이다: 스크립트가 지갑·재고를 비우는 속도를 사람 손 속도로 끌어내린다.
_BUCKETS: dict[str, deque] = defaultdict(deque)
WINDOW_S = 60.0


def rate_limit(request: Request, scope: str, per_ip: int = 4, total: int = 40) -> None:
    now = time.monotonic()
    fwd = request.headers.get("x-forwarded-for", "")
    ip = (fwd.split(",")[0].strip() or (request.client.host if request.client else "?"))
    for key, cap in ((f"{scope}:{ip}", per_ip), (scope, total)):
        bucket = _BUCKETS[key]
        while bucket and now - bucket[0] > WINDOW_S:
            bucket.popleft()
        if len(bucket) >= cap:
            raise HTTPException(429, "요청이 너무 잦습니다 — 잠시 후 다시 시도해주세요")
        bucket.append(now)
