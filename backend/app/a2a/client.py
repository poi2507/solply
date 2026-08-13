"""A2A 발신 — 상대 에이전트의 엔드포인트로 실제 HTTP 왕복.

runner.run(...)을 부르던 자리가 send(...)로 바뀐다. 경량판에서는 자기 자신을
부르지만(x402 self-call과 같은 수법), 호출부는 상대가 어디 있는지 모른다 —
완전판 승격은 config의 A2A_*_URL 교체가 전부인 이유다.

비동기 클라이언트를 쓴다: 동기 호출은 자기 자신을 기다리며 이벤트 루프를
잠그는 자기 호출 데드락이 된다.
"""

from typing import Any
from uuid import uuid4

import httpx

from app import config

# 테스트가 ASGITransport를 주입해 네트워크 없이 실제 왕복을 검증한다
_TRANSPORT: httpx.AsyncBaseTransport | None = None

# 그래프 한 판에는 온체인 결제(확정 대기 포함)가 들어갈 수 있다 — x402 pay(90s)보다 여유 있게
_TIMEOUT_S = 300


def _base(agent_id: str) -> str:
    return config.A2A_HQ_URL if agent_id == "hq" else config.A2A_STORE_URL


# 동적 디스커버리 — 보내기 전에 상대 명함을 읽고 스킬이 있는지 확인한다.
# 명함이 장식이 아니라 실제 계약이 되는 지점: 완전판에서 상대가 다른 회사여도
# 같은 명함으로 능력을 확인하고 나서야 메시지를 보낸다. 프로세스당 1회 캐시.
_CARD_CACHE: dict[str, set[str]] = {}


async def discover_skills(agent_id: str) -> set[str]:
    """상대 명함(.well-known/agent-card.json)에서 스킬 목록을 읽는다."""
    if agent_id in _CARD_CACHE:
        return _CARD_CACHE[agent_id]
    async with httpx.AsyncClient(transport=_TRANSPORT, timeout=30) as client:
        resp = await client.get(f"{_base(agent_id)}/a2a/{agent_id}/.well-known/agent-card.json")
    resp.raise_for_status()
    skills = {s["id"] for s in resp.json().get("skills", [])}
    _CARD_CACHE[agent_id] = skills
    return skills


async def send(agent_id: str, intent: str, **kwargs: Any) -> dict:
    """message/send 한 통 — 상대 명함에서 스킬을 확인한 뒤에만 보낸다."""
    skills = await discover_skills(agent_id)
    if intent not in skills:
        raise RuntimeError(
            f"명함에 없는 스킬이라 보내지 않음: {agent_id} ← {intent} (명함 스킬 {len(skills)}개)"
        )
    request = {
        "jsonrpc": "2.0",
        "id": f"a2a-{uuid4().hex[:12]}",
        "method": "message/send",
        "params": {
            "message": {
                "kind": "message",
                "role": "user",
                "parts": [{"kind": "data", "data": {"intent": intent, **kwargs}}],
            }
        },
    }
    async with httpx.AsyncClient(transport=_TRANSPORT, timeout=_TIMEOUT_S) as client:
        resp = await client.post(f"{_base(agent_id)}/a2a/{agent_id}", json=request)
    resp.raise_for_status()
    body = resp.json()
    if "error" in body:
        raise RuntimeError(f"A2A 오류 ({agent_id}/{intent}): {body['error'].get('message')}")
    return next(
        p["data"] for p in body["result"]["parts"] if p.get("kind") == "data"
    )
