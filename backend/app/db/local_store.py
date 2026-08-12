"""JSON 파일 기반 저장소 — 로컬 개발용.

프로세스 여럿(API 서버 + 데모 스크립트)이 같은 파일을 공유하므로
매번 디스크에서 읽어 최신 상태를 본다. 쓰기는 임시 파일 후 교체(원자적).
"""

import json
import threading
from datetime import UTC, datetime
from pathlib import Path

from app.core import kst

_EMPTY: dict = {"events": []}


def _collection(state: dict, name: str) -> dict:
    """컬렉션을 늘려도 코드를 고치지 않도록 없으면 만들어 쓴다 (Postgres 쪽과 같은 성질)."""
    return state.setdefault(name, {})


class LocalStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()

    # ── 내부 ──
    def _load(self) -> dict:
        if self.path.exists():
            try:
                return json.loads(self.path.read_text())
            except json.JSONDecodeError:  # 쓰기 도중 읽으면 발생할 수 있다
                return json.loads(json.dumps(_EMPTY))
        return json.loads(json.dumps(_EMPTY))

    def _save(self, state: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2))
        tmp.replace(self.path)

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat()

    # ── 인터페이스 ──
    def get(self, collection: str, doc_id: str) -> dict | None:
        with self._lock:
            return _collection(self._load(), collection).get(doc_id)

    def put(self, collection: str, doc_id: str, doc: dict) -> dict:
        with self._lock:
            state = self._load()
            doc = {**doc, "id": doc_id, "updated_at": self._now()}
            _collection(state, collection)[doc_id] = doc
            self._save(state)
            return doc

    def update(self, collection: str, doc_id: str, patch: dict) -> dict:
        with self._lock:
            state = self._load()
            doc = _collection(state, collection)[doc_id]
            doc.update(patch)
            doc["updated_at"] = self._now()
            self._save(state)
            return doc

    def list_docs(self, collection: str, day: str | None = None, **filters) -> list[dict]:
        with self._lock:
            docs = list(_collection(self._load(), collection).values())
        if day:
            docs = [d for d in docs if d.get("updated_at") and kst.day_of(d["updated_at"]) == day]
        for key, value in filters.items():
            docs = [d for d in docs if d.get(key) == value]
        return docs

    def count_docs(self, collection: str, **filters) -> int:
        return len(self.list_docs(collection, **filters))

    def events_for(self, invoice_ids: tuple[str, ...]) -> list[dict]:
        wanted = set(invoice_ids)
        return [e for e in self.list_events()
                if (e.get("payload") or {}).get("invoice_id") in wanted]

    def count_stale(self, collection: str, statuses: tuple[str, ...], before: str,
                    **filters) -> int:
        return sum(
            1 for d in self.list_docs(collection, **filters)
            if d.get("status") in statuses and str(d.get("updated_at", "")) < before
        )

    def first_day(self) -> str | None:
        with self._lock:
            state = self._load()
        stamps = [e["ts"] for e in state.get("events", [])]
        for docs in state.values():
            if isinstance(docs, dict):
                stamps += [d["updated_at"] for d in docs.values() if d.get("updated_at")]
        return kst.day_of(min(stamps)) if stamps else None

    def list_events(self) -> list[dict]:
        with self._lock:
            return self._load().setdefault("events", [])

    def count_events(self, actor: str | None = None, day: str | None = None) -> int:
        return len(self._events(actor=actor, day=day))

    def recent_events(self, limit: int, day: str | None = None,
                      action: str | None = None) -> list[dict]:
        events = self._events(day=day)
        if action:
            events = [e for e in events if e["action"] == action]
        return events[-limit:][::-1]

    def _events(self, actor: str | None = None, day: str | None = None) -> list[dict]:
        with self._lock:
            events = list(self._load().setdefault("events", []))
        if actor:
            events = [e for e in events if e["actor"] == actor]
        if day:
            events = [e for e in events if kst.day_of(e["ts"]) == day]
        return events

    def events_after(self, cursor: int) -> list[dict]:
        with self._lock:
            return self._load().setdefault("events", [])[cursor:]

    def log_event(self, actor: str, action: str, payload: dict) -> None:
        with self._lock:
            state = self._load()
            state.setdefault("events", []).append(
                {"ts": self._now(), "actor": actor, "action": action, "payload": payload}
            )
            self._save(state)

    def reset(self, keep: tuple[str, ...] = ()) -> None:
        with self._lock:
            if not keep:
                self.path.unlink(missing_ok=True)
                return
            preserved = {name: self._load().get(name, {}) for name in keep}
            fresh = json.loads(json.dumps(_EMPTY))
            fresh.update(preserved)
            self._save(fresh)
