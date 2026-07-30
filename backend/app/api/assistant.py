"""정산 어시스턴트 API — 대시보드 채팅 패널의 백엔드."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app import config
from app.assistant import agent as assistant

router = APIRouter(prefix="/api/assistant", tags=["assistant"])


class ChatIn(BaseModel):
    message: str
    session_id: str = "dashboard"


@router.post("/chat")
async def chat(body: ChatIn) -> dict:
    """한 턴 대화. 어시스턴트는 LLM 그 자체라 mock 모드에서는 동작하지 않는다."""
    if config.LLM_PROVIDER == "mock":
        raise HTTPException(503, "어시스턴트는 Gemini/Vertex 모드에서 동작합니다 (지금은 LLM_PROVIDER=mock)")
    if not body.message.strip():
        raise HTTPException(400, "메시지가 비어 있습니다")
    try:
        reply = await assistant.chat(body.session_id, body.message.strip())
    except Exception as exc:
        # 공급자 오류 원문(문서 링크·스택)을 대화창에 흘리지 않는다. 진단은 서버 로그에 남긴다.
        print(f"[assistant] 응답 실패: {exc}")
        raise HTTPException(502, "지금 답을 만들지 못했어요. 잠시 뒤 다시 물어봐 주세요.") from exc
    return {"reply": reply or "…답변을 만들지 못했습니다. 다시 물어봐 주세요."}
