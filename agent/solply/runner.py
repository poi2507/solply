"""에이전트 실행 헬퍼.

Gemini 무료 티어는 모델당 분당 요청 수가 제한된다(429 RESOURCE_EXHAUSTED).
데모가 중간에 죽지 않도록 429를 잡아 재시도하고, 호출 사이에 최소 간격을 둔다.
"""

import asyncio
import json
import re
import time

from google.adk.runners import InMemoryRunner
from google.genai import types

_MIN_GAP_SEC = 4.0  # 연속 호출 사이 최소 간격
_last_call_at = 0.0


def _retry_delay(message: str, attempt: int) -> float:
    """429 메시지의 retryDelay를 우선 쓰고, 없으면 지수 백오프."""
    match = re.search(r"'retryDelay':\s*'(\d+)s'", message) or re.search(r"retry in (\d+(?:\.\d+)?)s", message)
    if match:
        return float(match.group(1)) + 1.5
    return min(60.0, 8.0 * (2 ** (attempt - 1)))


async def run_agent(
    agent,
    prompt: str,
    *,
    on_tool=None,
    on_text=None,
    max_attempts: int = 4,
) -> str:
    """에이전트에게 지시하고 최종 응답을 돌려준다.

    on_tool(name, args) / on_text(text) 콜백으로 진행 상황을 중계한다.
    """
    global _last_call_at

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
            is_quota = "429" in text or "RESOURCE_EXHAUSTED" in text
            if attempt == max_attempts or not is_quota:
                raise
            wait = _retry_delay(text, attempt)
            if on_text:
                on_text(f"⏳ 요청 한도에 걸려 {wait:.0f}초 후 재시도합니다 ({attempt}/{max_attempts - 1})")
            await asyncio.sleep(wait)

    return ""


def latest_event(events: list[dict], action: str) -> dict | None:
    for event in reversed(events):
        if event["action"] == action:
            return event["payload"]
    return None
