"""로컬 JSON 상태 저장소.

W1에서는 파일 기반으로 개발하고, W3에 Firestore로 교체한다 (인터페이스 유지).
컬렉션: stores / invoices / negotiations / schedules / events (product-design.md 데이터 모델)
"""

import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

_STATE_PATH = Path(os.getenv("SOLPLY_STATE_PATH", Path(__file__).parent.parent / "data" / "state.json"))
_lock = threading.Lock()

_EMPTY = {"stores": {}, "invoices": {}, "negotiations": {}, "schedules": {}, "events": []}


def _load() -> dict:
    if _STATE_PATH.exists():
        return json.loads(_STATE_PATH.read_text())
    return json.loads(json.dumps(_EMPTY))


def _save(state: dict) -> None:
    _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2))


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def get(collection: str, doc_id: str) -> dict | None:
    with _lock:
        return _load()[collection].get(doc_id)


def put(collection: str, doc_id: str, doc: dict) -> dict:
    with _lock:
        state = _load()
        doc = {**doc, "id": doc_id, "updated_at": now()}
        state[collection][doc_id] = doc
        _save(state)
        return doc


def update(collection: str, doc_id: str, patch: dict) -> dict:
    with _lock:
        state = _load()
        doc = state[collection][doc_id]
        doc.update(patch)
        doc["updated_at"] = now()
        _save(state)
        return doc


def list_docs(collection: str, **filters) -> list[dict]:
    with _lock:
        docs = list(_load()[collection].values())
    for key, value in filters.items():
        docs = [d for d in docs if d.get(key) == value]
    return docs


def list_events() -> list[dict]:
    """실행 증빙 로그 전체 (오래된 것부터)."""
    with _lock:
        return _load()["events"]


def log_event(actor: str, action: str, payload: dict) -> None:
    """append-only 실행 증빙 로그 — 심사 기준 4번(실행 로그 기반 확인)의 근거."""
    with _lock:
        state = _load()
        state["events"].append({"ts": now(), "actor": actor, "action": action, "payload": payload})
        _save(state)
