"""A2A 수신 — message/send(JSON-RPC)를 그래프 실행으로 번역한다.

그래프 코드는 한 줄도 바뀌지 않는다. 이 라우터는 x402의 protocol.py처럼
'번역기'다: 표준 메시지의 skill(intent)과 데이터를 runner.run에 넘기고,
최종 상태의 공개 가능한 부분을 표준 응답으로 되돌려준다.

수신 자체가 실행 증빙이다 — 모든 메시지가 a2a.message 이벤트로 남는다.
"""

from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from app.a2a import card
from app.agents import runner, utils

router = APIRouter(prefix="/a2a", tags=["a2a"])

# 그래프 최종 상태에서 상대에게 돌려주는 키 — 내부 필드는 경계를 넘지 않는다
REPLY_KEYS = (
    "outcome", "messages", "reasoning", "tx_signature",
    "invoice_id", "trade_id", "invoice", "trade", "proposal",
    # decision — 협상 오케스트레이터가 역제안 조건(counter_terms)을 여기서 읽는다.
    # 빠지면 라운드 1의 counter가 결렬로 오판된다 (8/13 라이브 실측).
    "decision",
)


def _error(request_id: Any, code: int, message: str) -> JSONResponse:
    return JSONResponse(
        {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}
    )


@router.get("/{agent_id}/.well-known/agent-card.json")
def agent_card(agent_id: str) -> dict:
    """에이전트 명함 — 이 주소가 열린다는 것 자체가 '표준으로 말한다'는 증명."""
    if agent_id not in card.known_agents():
        raise HTTPException(404, f"알 수 없는 에이전트: {agent_id}")
    return card.build(agent_id)


@router.post("/{agent_id}")
async def message_send(agent_id: str, body: dict) -> JSONResponse:
    """JSON-RPC message/send 한 통 = 그래프 한 판."""
    agents = card.known_agents()
    if agent_id not in agents:
        raise HTTPException(404, f"알 수 없는 에이전트: {agent_id}")
    request_id = body.get("id")
    if body.get("jsonrpc") != "2.0":
        return _error(request_id, -32600, "jsonrpc 2.0 요청이 아닙니다")
    if body.get("method") != "message/send":
        return _error(request_id, -32601, f"지원하지 않는 메서드: {body.get('method')}")

    try:
        parts = body["params"]["message"]["parts"]
        data = next(p["data"] for p in parts if p.get("kind") == "data")
        intent = data["intent"]
    except (KeyError, StopIteration):
        return _error(request_id, -32602, "message.parts에 intent를 담은 data part가 필요합니다")

    skills = card.HQ_SKILLS if agents[agent_id] == "hq" else card.STORE_SKILLS
    if intent not in skills:
        return _error(request_id, -32602, f"명함에 없는 스킬: {intent}")

    kwargs = {k: v for k, v in data.items() if k != "intent"}
    if agents[agent_id] == "store":
        kwargs["store_id"] = agent_id  # 명함의 주인이 곧 실행 주체 — 메시지로 남을 흉내 못 낸다

    try:
        final = await runner.run(agents[agent_id], intent, **kwargs)
    except Exception as exc:  # noqa: BLE001 — 그래프 실패는 불투명한 500이 아니라 표준 오류로
        utils.log(
            f"{agent_id}-agent", "a2a.message",
            {"method": "message/send", "skill": intent, "outcome": "error",
             "reason": str(exc)[:160], "request_id": request_id},
        )
        return _error(request_id, -32000, f"{type(exc).__name__}: {str(exc)[:200]}")
    reply = {k: final[k] for k in REPLY_KEYS if k in final}

    utils.log(
        f"{agent_id}-agent", "a2a.message",
        {"method": "message/send", "skill": intent, "outcome": reply.get("outcome"),
         "request_id": request_id},
    )
    return JSONResponse({
        "jsonrpc": "2.0",
        "id": request_id,
        "result": {"kind": "message", "role": "agent",
                   "parts": [{"kind": "data", "data": reply}]},
    })
