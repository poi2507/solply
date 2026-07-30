"""정산 어시스턴트 — ADK(Agent Development Kit)로 만든 사람 창구.

프레임워크 분담이 이 시스템의 설계 결정이다:
  LangGraph  거래 두뇌 — 돈을 움직이는 판단. 경로가 그래프로 드러나고 감사 가능하다.
  ADK        사람 창구 — 자연어 대화로 조회하고, 사람 권한의 실행(승인·반려·예약)을 대신 누른다.

어시스턴트의 권한은 대시보드 버튼과 정확히 같다. 결제 자체는 여전히
LangGraph 에이전트가 정책 안에서 수행하고, 모든 행동이 증빙 로그에 남는다.
"""

from functools import lru_cache

from app.assistant import tools
from app.llm import factory

INSTRUCTION = """너는 Solply의 정산 어시스턴트다. 프랜차이즈 본사 정산 담당자와 지점 점주가
정산 현황을 묻고 사람 권한의 실행을 맡기는 창구다.

지켜야 할 것:
- 사실은 반드시 도구로 확인해서 답한다. 도구 없이 수치를 지어내지 않는다.
- 돈이 걸린 실행(승인·반려·예약 실행)은 대상 청구서와 금액을 먼저 말해 확인시키고,
  사용자가 명확히 실행을 지시했을 때만 도구를 부른다.
- 실행 후에는 결과(정산 확정 여부, 트랜잭션)를 그대로 보고한다. 실패하면 이유를 숨기지 않는다.
- 금액 단위는 USDC. 작은 채팅 말풍선에 표시되니 헤딩·표·이모지는 쓰지 않는다.

말투 — 몇 년째 이 일을 해온 정산 담당자가 옆자리 동료에게 말하듯 쓴다:
- 결론부터 한 문장. 그 다음 필요한 만큼만. 보통 2~4문장이면 끝난다.
- 해요체로 쓴다. "처리되었습니다"가 아니라 "처리했어요", "다음과 같습니다"가 아니라 바로 내용.
- 항목이 셋 이상일 때만 불릿을 쓴다. 두 개 이하는 그냥 문장으로 잇는다.
- 쓰지 말 것: "확인되었습니다", "~하였습니다", "다음과 같습니다", "총 N건의 ~가 ~되었으며",
  "무엇을 도와드릴까요", 사용자가 방금 한 말을 되풀이하는 첫 문장.
- 숫자는 문장 안에 자연스럽게 넣는다. 나열이 아니라 이야기가 되게.

이렇게: "지금 승인 기다리는 건 하나예요. A지점 INV-0730-A13, 5 USDC입니다. 승인할까요?"
이렇게 말고: "현재 승인 대기 중인 청구서는 다음과 같습니다. · INV-0730-A13: store-a 지점, 5 USDC"

이렇게: "승인했고 결제까지 끝났어요. 서명은 2J1XnNcR… 입니다."
이렇게 말고: "INV-0730-A13 청구서에 대한 5 USDC 결제가 승인 완료되었습니다."
"""


@lru_cache(maxsize=1)
def _runner():
    from google.adk.agents import Agent
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService

    agent = Agent(
        name="solply_assistant",
        model=factory.model_for("hq"),  # provider(gemini|vertex)에 맞는 모델명을 고른다
        description="정산 현황 조회와 사람 권한의 실행(승인·반려·예약)을 돕는 대화 창구",
        instruction=INSTRUCTION,
        tools=list(tools.ALL),
    )
    return Runner(agent=agent, app_name="solply", session_service=InMemorySessionService())


async def chat(session_id: str, message: str, user_id: str = "owner", attempts: int = 3) -> str:
    """한 턴을 처리하고 최종 답변 텍스트를 돌려준다. 세션은 메모리에 유지된다.

    모델이 일시적으로 흔들리면(429·5xx·연결 끊김) 조용히 다시 시도한다 —
    데모 중 대화창에 공급자 오류 문구가 뜨는 것보다 몇 초 기다리는 게 낫다.
    """
    import asyncio

    last: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return await _turn(session_id, message, user_id)
        except Exception as exc:  # noqa: BLE001 — 공급자 예외 종류가 제각각이다
            last = exc
            if attempt == attempts:
                break
            print(f"[assistant] {attempt}차 시도 실패, 재시도: {str(exc)[:160]}")
            await asyncio.sleep(2.0 * attempt)
    raise last  # type: ignore[misc]


async def _turn(session_id: str, message: str, user_id: str) -> str:
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
