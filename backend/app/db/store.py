"""저장소 인터페이스.

로컬 개발은 JSON 파일, 운영은 PostgreSQL(Cloud SQL).
호출부는 이 모듈만 임포트하므로 백엔드 교체 시 다른 코드는 손대지 않는다.

컬렉션: stores / invoices / negotiations / schedules / events
"""

from typing import Protocol

from app import config


class Store(Protocol):
    def get(self, collection: str, doc_id: str) -> dict | None: ...
    def put(self, collection: str, doc_id: str, doc: dict) -> dict: ...
    def update(self, collection: str, doc_id: str, patch: dict) -> dict: ...
    def list_docs(self, collection: str, **filters) -> list[dict]: ...
    def list_events(self) -> list[dict]: ...
    def log_event(self, actor: str, action: str, payload: dict) -> None: ...
    def reset(self, keep: tuple[str, ...] = ()) -> None: ...


def _build() -> Store:
    if config.STORE_BACKEND == "postgres":
        from app.db.postgres_store import PostgresStore

        return PostgresStore(config.DATABASE_URL)
    from app.db.local_store import LocalStore

    return LocalStore(config.STATE_PATH)


_store: Store = _build()


# 모듈 레벨 파사드 — 호출부는 `from app.db import store` 후 store.get(...) 형태로 쓴다.
def get(collection: str, doc_id: str) -> dict | None:
    return _store.get(collection, doc_id)


def put(collection: str, doc_id: str, doc: dict) -> dict:
    return _store.put(collection, doc_id, doc)


def update(collection: str, doc_id: str, patch: dict) -> dict:
    return _store.update(collection, doc_id, patch)


def list_docs(collection: str, **filters) -> list[dict]:
    return _store.list_docs(collection, **filters)


def list_events() -> list[dict]:
    return _store.list_events()


def log_event(actor: str, action: str, payload: dict) -> None:
    """append-only 실행 증빙 로그 — 심사 기준 4번(실행 로그 기반 확인)의 근거."""
    _store.log_event(actor, action, payload)


def reset(keep: tuple[str, ...] = ()) -> None:
    """상태를 비운다. `keep`에 든 컬렉션은 남긴다 — 사용자가 설정한 정책이 대표적이다."""
    _store.reset(keep)


def new_id(prefix: str) -> str:
    import uuid

    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()
