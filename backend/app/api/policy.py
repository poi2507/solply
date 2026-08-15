"""거래 정책 API — 사용자가 프론트에서 에이전트의 판단 경계를 설정한다.

에이전트가 얼마까지 스스로 결제할지, 얼마를 남겨둘지, 어떤 조건에 유예를 내줄지는
개발자가 아니라 점주·정산담당자가 정한다. 저장된 값은 프롬프트의 POLICY 섹션으로 주입된다.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core import fixtures
from app.core import policy as policy_mod
from app.db import store

router = APIRouter(prefix="/api/policy", tags=["policy"])


class PolicyPatch(BaseModel):
    # 사정(persona)은 글이라 문자열도 받는다 — 한도는 여전히 숫자만
    values: dict[str, float | int | str]


@router.get("/owners")
def owners() -> dict:
    """설정 가능한 주체 목록 — 프론트 로그인 화면의 선택지."""
    stores = fixtures.load()["stores"]
    return {
        "owners": [
            {"id": "hq", "name": "본사 정산팀", "kind": "hq"},
            *[
                {"id": sid, "name": profile["name"], "kind": "store"}
                for sid, profile in stores.items()
            ],
        ]
    }


@router.get("/{owner_id}")
def get_policy(owner_id: str) -> dict:
    """현재 정책과 프론트가 렌더할 항목 정의를 함께 준다."""
    if owner_id not in ("hq", *fixtures.load()["stores"]):
        raise HTTPException(404, f"알 수 없는 주체: {owner_id}")
    return {"ownerId": owner_id, "fields": policy_mod.describe(owner_id)}


@router.put("/{owner_id}")
def update_policy(owner_id: str, patch: PolicyPatch) -> dict:
    """설정 저장. 다음 에이전트 실행부터 즉시 적용된다.

    규칙 변경도 결제와 같은 무게의 사건이다 — 무엇이 얼마에서 얼마로 바뀌었는지
    actor=human 이벤트로 남겨, 에이전트의 판단 경계가 언제 왜 움직였는지 추적된다.
    """
    if owner_id not in ("hq", *fixtures.load()["stores"]):
        raise HTTPException(404, f"알 수 없는 주체: {owner_id}")

    before = {f["key"]: f["value"] for f in policy_mod.describe(owner_id)}
    try:
        policy_mod.save(owner_id, dict(patch.values))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    changes = {
        key: {"from": before[key], "to": value}
        for key, value in patch.values.items()
        if key in before and before[key] != value
    }
    if changes:
        store.log_event("human", "policy.updated", {"owner_id": owner_id, "changes": changes})
    return {"ownerId": owner_id, "fields": policy_mod.describe(owner_id), "saved": True}
