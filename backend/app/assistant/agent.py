"""정산 어시스턴트 — ADK(Agent Development Kit)로 만든 사람 창구.

프레임워크 분담이 이 시스템의 설계 결정이다:
  LangGraph  거래 두뇌 — 돈을 움직이는 판단. 경로가 그래프로 드러나고 감사 가능하다.
  ADK        사람 창구 — 자연어 대화로 조회하고, 사람 권한의 실행(승인·반려·예약)을 대신 누른다.

어시스턴트의 권한은 대시보드 버튼과 정확히 같다. 결제 자체는 여전히
LangGraph 에이전트가 정책 안에서 수행하고, 모든 행동이 증빙 로그에 남는다.
"""

from functools import lru_cache

from app import config
from app.assistant import tools

INSTRUCTION = """너는 Solply의 정산 어시스턴트다. 프랜차이즈 본사 정산 담당자와 지점 점주가
정산 현황을 묻고 사람 권한의 실행을 맡기는 창구다.

규칙:
- 사실은 반드시 도구로 확인해서 답한다. 도구 없이 수치를 지어내지 않는다.
- 돈이 걸린 실행(승인·반려·예약 실행)은 대상 청구서와 금액을 먼저 말해 확인시키고,
  사용자가 명확히 실행을 지시했을 때만 도구를 부른다.
- 실행 후에는 결과(정산 확정 여부, 트랜잭션)를 그대로 보고한다. 실패하면 이유를 숨기지 않는다.
- 한국어로 짧고 명확하게 답한다. 금액 단위는 USDC.
"""


@lru_cache(maxsize=1)
def _runner():
    from google.adk.agents import Agent
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService

    agent = Agent(
        name="solply_assistant",
        model=config.HQ_MODEL,
        description="정산 현황 조회와 사람 권한의 실행(승인·반려·예약)을 돕는 대화 창구",
        instruction=INSTRUCTION,
        tools=list(tools.ALL),
    )
    return Runner(agent=agent, app_name="solply", session_service=InMemorySessionService())


async def chat(session_id: str, message: str, user_id: str = "owner") -> str:
    """한 턴을 처리하고 최종 답변 텍스트를 돌려준다. 세션은 메모리에 유지된다."""
    from google.genai import types

    runner = _runner()
    session = await runner.session_service.get_session(
        app_name="solply", user_id=user_id, session_id=session_id
    )
    if session is None:
        await runner.session_service.create_session(
            app_name="solply", user_id=user_id, session_id=session_id
        )

    content = types.Content(role="user", parts=[types.Part(text=message)])
    reply = ""
    async for event in runner.run_async(
        user_id=user_id, session_id=session_id, new_message=content
    ):
        if event.is_final_response() and event.content and event.content.parts:
            reply = "".join(part.text or "" for part in event.content.parts)
    return reply.strip()
