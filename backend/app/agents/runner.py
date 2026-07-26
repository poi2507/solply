"""에이전트 실행 헬퍼.

두 실행 모드를 같은 인터페이스로 감싼다.
  - gemini: ADK Runner로 실제 LLM 판단. 무료 티어 429를 잡아 재시도한다.
  - mock:   규칙 기반 플래너로 도구만 실행. rate limit 없이 리허설할 때.

도구 호출 자체는 두 모드가 동일하므로 **온체인 트랜잭션은 어느 쪽이든 실제로 발생**한다.
"""

import asyncio
import re
import time

from app import config

_MIN_GAP_SEC = 4.0
_last_call_at = 0.0


def _retry_delay(message: str, attempt: int) -> float:
    """429 응답이 알려준 retryDelay를 우선 쓰고, 없으면 지수 백오프."""
    match = re.search(r"'retryDelay':\s*'(\d+)s'", message) or re.search(r"retry in (\d+(?:\.\d+)?)s", message)
    if match:
        return float(match.group(1)) + 1.5
    return min(60.0, 8.0 * (2 ** (attempt - 1)))


async def _run_mock(agent, prompt: str, on_tool, on_text) -> str:
    lines: list[str] = []
    for name, args in agent.plan(prompt):
        if on_tool:
            on_tool(name, args)
        result = agent.tools[name](**args)
        if isinstance(result, dict) and result.get("error"):
            lines.append(f"⚠ {result['error']}")
        await asyncio.sleep(0.15)  # 대시보드에서 흐름이 보이도록 살짝 텀을 준다
    text = "\n".join(lines) or "처리 완료"
    if on_text:
        on_text(text)
    return text


async def _run_gemini(agent, prompt: str, on_tool, on_text, max_attempts: int) -> str:
    global _last_call_at
    from google.adk.runners import InMemoryRunner
    from google.genai import types

    for attempt in range(1, max_attempts + 1):
        gap = _MIN_GAP_SEC - (time.monotonic() - _last_call_at)
        if gap > 0:
            await asyncio.sleep(gap)

        runner = InMemoryRunner(agent=agent, app_name="solply")
        session = await runner.session_service.create_session(app_name="solply", user_id="demo")
        message = types.Content(role="user", parts=[types.Part(text=prompt)])
        final = ""
        try:
            async for event in runner.run_async(user_id="demo", session_id=session.id, new_message=message):
                if not (event.content and event.content.parts):
                    continue
                for part in event.content.parts:
                    if part.function_call and on_tool:
                        on_tool(part.function_call.name, dict(part.function_call.args))
                    elif part.text and part.text.strip():
                        final = part.text.strip()
            _last_call_at = time.monotonic()
            if final and on_text:
                on_text(final)
            return final
        except Exception as exc:  # noqa: BLE001 — 429 외 오류도 재시도 가치가 있다
            _last_call_at = time.monotonic()
            text = str(exc)
            if attempt == max_attempts or not ("429" in text or "RESOURCE_EXHAUSTED" in text):
                raise
            wait = _retry_delay(text, attempt)
            if on_text:
                on_text(f"⏳ 요청 한도 — {wait:.0f}초 후 재시도 ({attempt}/{max_attempts - 1})")
            await asyncio.sleep(wait)
    return ""


async def run_agent(agent, prompt: str, *, on_tool=None, on_text=None, max_attempts: int = 4) -> str:
    """에이전트에게 지시하고 최종 응답을 돌려준다."""
    if config.LLM_PROVIDER == "mock":
        return await _run_mock(agent, prompt, on_tool, on_text)
    return await _run_gemini(agent, prompt, on_tool, on_text, max_attempts)


def latest_event(events: list[dict], action: str) -> dict | None:
    for event in reversed(events):
        if event["action"] == action:
            return event["payload"]
    return None
