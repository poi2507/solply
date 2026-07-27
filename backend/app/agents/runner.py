"""그래프 실행기.

에이전트 그래프를 돌리고, 노드 단위 진행을 콜백으로 중계한다.
LLM 재시도·provider 분기는 `app/llm/judge.py`가 처리하므로 여기는 흐름만 본다.
"""

from typing import Any, Callable

from app.agents import hq, store
from app.agents.state import initial_state

_GRAPHS = {"hq": hq.graph.build, "store": store.graph.build}


async def run(
    agent: str,
    intent: str,
    *,
    on_node: Callable[[str], None] | None = None,
    on_message: Callable[[str], None] | None = None,
    **state_kwargs: Any,
) -> dict[str, Any]:
    """에이전트 그래프를 한 번 돌리고 최종 상태를 돌려준다.

    Args:
        agent: hq | store
        intent: 무엇을 시킬지 (invoice.issue, invoice.handle, proposal.adjustment …)
        on_node: 노드가 끝날 때마다 이름을 받는 콜백 (데모에서 진행 표시)
        on_message: 새 보고 문장이 생길 때마다 받는 콜백
    """
    actor = f"{state_kwargs.get('store_id')}-agent" if agent == "store" else "hq-agent"
    state = initial_state(actor=actor, intent=intent, **state_kwargs)
    graph = _GRAPHS[agent]()

    final: dict[str, Any] = dict(state)
    seen_messages = 0
    async for chunk in graph.astream(state, stream_mode="values"):
        final = chunk
        if on_node:
            pass  # values 모드에서는 노드명이 오지 않는다 — 아래 updates 스트림에서 받는다
        messages = chunk.get("messages", [])
        if on_message and len(messages) > seen_messages:
            for message in messages[seen_messages:]:
                on_message(message)
            seen_messages = len(messages)
    return final


async def run_verbose(
    agent: str,
    intent: str,
    *,
    on_node: Callable[[str, dict], None] | None = None,
    on_message: Callable[[str], None] | None = None,
    **state_kwargs: Any,
) -> dict[str, Any]:
    """노드 이름까지 중계하는 실행 — 데모에서 판단 경로를 보여줄 때 쓴다."""
    actor = f"{state_kwargs.get('store_id')}-agent" if agent == "store" else "hq-agent"
    state = initial_state(actor=actor, intent=intent, **state_kwargs)
    graph = _GRAPHS[agent]()

    merged: dict = dict(state)
    reported: set[str] = set()
    async for step in graph.astream(state, stream_mode="updates"):
        for node_name, update in step.items():
            if not isinstance(update, dict):
                continue
            if on_node:
                on_node(node_name, update)
            for message in update.get("messages", []) or []:
                if on_message and message not in reported:
                    on_message(message)
                    reported.add(message)
            for key, value in update.items():
                if key in ("messages", "reasoning"):
                    merged.setdefault(key, [])
                    merged[key] = list(merged[key]) + list(value or [])
                else:
                    merged[key] = value
    return merged


def latest_event(events: list[dict], action: str) -> dict | None:
    for event in reversed(events):
        if event["action"] == action:
            return event["payload"]
    return None
