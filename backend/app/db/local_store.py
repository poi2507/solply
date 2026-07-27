"""JSON 파일 기반 저장소 — 로컬 개발용.

프로세스 여럿(API 서버 + 데모 스크립트)이 같은 파일을 공유하므로
매번 디스크에서 읽어 최신 상태를 본다. 쓰기는 임시 파일 후 교체(원자적).
"""

import json
import threading
from datetime import datetime, timezone
from pathlib import Path

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
        return datetime.now(timezone.utc).isoformat()

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

    def list_docs(self, collection: str, **filters) -> list[dict]:
        with self._lock:
            docs = list(_collection(self._load(), collection).values())
        for key, value in filters.items():
            docs = [d for d in docs if d.get(key) == value]
        return docs

    def list_events(self) -> list[dict]:
        with self._lock:
            return self._load().setdefault("events", [])

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
