"""PostgreSQL 저장소.

문서형 인터페이스를 그대로 유지하기 위해 JSONB 한 컬럼에 문서를 담는다.
컬렉션마다 테이블을 나누지 않는 이유: 스키마가 아직 움직이는 중이고,
Firestore(문서 DB)로 갈아끼울 여지도 남겨두기 위해서다.

  documents(collection, doc_id, data JSONB, updated_at)   ← 기본키 (collection, doc_id)
  events(id BIGSERIAL, ts, actor, action, payload JSONB)  ← append-only 실행 증빙

연결: DATABASE_URL=postgresql://user:pass@host:5432/solply
Cloud SQL로 옮길 때도 이 URL만 바꾸면 된다.
"""

import atexit
from typing import Any

from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from app.core import kst

_SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    collection  TEXT        NOT NULL,
    doc_id      TEXT        NOT NULL,
    data        JSONB       NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (collection, doc_id)
);

CREATE INDEX IF NOT EXISTS documents_collection_idx ON documents (collection);
-- 지점별 조회가 잦다: list_docs("invoices", store_id=...)
CREATE INDEX IF NOT EXISTS documents_store_idx ON documents ((data ->> 'store_id'));
-- 대시보드는 '그날 하루'만 읽는다 — 기록이 몇 달 쌓여도 화면은 하루치만 훑는다
CREATE INDEX IF NOT EXISTS documents_day_idx ON documents (collection, updated_at DESC);

CREATE TABLE IF NOT EXISTS events (
    id       BIGSERIAL   PRIMARY KEY,
    ts       TIMESTAMPTZ NOT NULL DEFAULT now(),
    actor    TEXT        NOT NULL,
    action   TEXT        NOT NULL,
    payload  JSONB       NOT NULL
);

-- 반드시 events 테이블 뒤에 — 빈 DB에서 이 파일이 처음 실행될 때의 순서가 곧 스키마다
CREATE INDEX IF NOT EXISTS events_ts_idx ON events (ts DESC);
"""


class PostgresStore:
    def __init__(self, dsn: str, *, min_size: int = 1, max_size: int = 8) -> None:
        # check: 대여 직전에 연결을 확인한다 — DB를 재시작하면 풀이 죽은 커넥션을 들고 있고,
        # 그러면 AdminShutdown이 뜨면서 서비스가 재시작 없이는 복구되지 않는다.
        self.pool = ConnectionPool(
            dsn,
            min_size=min_size,
            max_size=max_size,
            open=True,
            check=ConnectionPool.check_connection,
        )
        self._ensure_schema()
        atexit.register(self.close)  # 프로세스 종료 시 풀 경고를 남기지 않는다

    def _ensure_schema(self) -> None:
        with self.pool.connection() as conn:
            conn.execute(_SCHEMA)

    # ── 문서 ──────────────────────────────────────────────────────
    def get(self, collection: str, doc_id: str) -> dict | None:
        with self.pool.connection() as conn:
            row = conn.execute(
                "SELECT data FROM documents WHERE collection = %s AND doc_id = %s",
                (collection, doc_id),
            ).fetchone()
        return row[0] if row else None

    def put(self, collection: str, doc_id: str, doc: dict) -> dict:
        doc = {**doc, "id": doc_id}
        with self.pool.connection() as conn:
            row = conn.execute(
                """
                INSERT INTO documents (collection, doc_id, data)
                VALUES (%s, %s, %s)
                ON CONFLICT (collection, doc_id)
                DO UPDATE SET data = EXCLUDED.data, updated_at = now()
                RETURNING data, updated_at
                """,
                (collection, doc_id, Jsonb(doc)),
            ).fetchone()
        return {**row[0], "updated_at": row[1].isoformat()}

    def update(self, collection: str, doc_id: str, patch: dict) -> dict:
        """JSONB 병합(||)으로 갱신 — 읽고-쓰는 왕복 없이 원자적으로 처리한다."""
        with self.pool.connection() as conn:
            row = conn.execute(
                """
                UPDATE documents
                   SET data = data || %s, updated_at = now()
                 WHERE collection = %s AND doc_id = %s
                RETURNING data, updated_at
                """,
                (Jsonb(patch), collection, doc_id),
            ).fetchone()
        if not row:
            raise KeyError(f"{collection}/{doc_id} 없음")
        return {**row[0], "updated_at": row[1].isoformat()}

    def list_docs(self, collection: str, day: str | None = None, **filters: Any) -> list[dict]:
        sql = "SELECT data, updated_at FROM documents WHERE collection = %s"
        params: list[Any] = [collection]
        if day:
            start, end = kst.bounds(day)
            sql += " AND updated_at >= %s AND updated_at < %s"
            params += [start, end]
        for key, value in filters.items():
            if value is None:
                continue
            if not key.isidentifier():
                raise ValueError(f"허용되지 않는 필터 키: {key!r}")
            sql += f" AND data ->> '{key}' = %s"
            params.append(str(value))
        sql += " ORDER BY updated_at"
        with self.pool.connection() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [{**r[0], "updated_at": r[1].isoformat()} for r in rows]

    def count_docs(self, collection: str, **filters: Any) -> int:
        sql = "SELECT count(*) FROM documents WHERE collection = %s"
        params: list[Any] = [collection]
        for key, value in filters.items():
            if value is None:
                continue
            if not key.isidentifier():
                raise ValueError(f"허용되지 않는 필터 키: {key!r}")
            sql += f" AND data ->> '{key}' = %s"
            params.append(str(value))
        with self.pool.connection() as conn:
            return conn.execute(sql, params).fetchone()[0]

    def count_stale(self, collection: str, statuses: tuple[str, ...], before: str,
                    **filters: Any) -> int:
        """상태·정체 시각으로 세는 전용 경로 — 문서를 읽지 않고 count로 끝낸다.
        갱신 시각은 컬럼(updated_at)을 쓴다: documents_day_idx가 그대로 태워진다."""
        sql = ("SELECT count(*) FROM documents WHERE collection = %s "
               "AND data ->> 'status' = ANY(%s) AND updated_at < %s")
        params: list[Any] = [collection, list(statuses), before]
        for key, value in filters.items():
            if value is None:
                continue
            if not key.isidentifier():
                raise ValueError(f"허용되지 않는 필터 키: {key!r}")
            sql += f" AND data ->> '{key}' = %s"
            params.append(str(value))
        with self.pool.connection() as conn:
            return conn.execute(sql, params).fetchone()[0]

    def first_day(self) -> str | None:
        """기록이 시작된 KST 날짜 — 날짜 이동의 왼쪽 끝."""
        with self.pool.connection() as conn:
            row = conn.execute(
                "SELECT least("
                " (SELECT min(updated_at) FROM documents),"
                " (SELECT min(ts) FROM events))"
            ).fetchone()
        return kst.day_of(row[0]) if row and row[0] else None

    # ── 이벤트 ────────────────────────────────────────────────────
    def list_events(self) -> list[dict]:
        with self.pool.connection() as conn:
            rows = conn.execute(
                "SELECT ts, actor, action, payload FROM events ORDER BY id"
            ).fetchall()
        return [
            {"ts": r[0].isoformat(), "actor": r[1], "action": r[2], "payload": r[3]} for r in rows
        ]

    def events_for(self, invoice_ids: tuple[str, ...]) -> list[dict]:
        with self.pool.connection() as conn:
            rows = conn.execute(
                "SELECT ts, actor, action, payload FROM events "
                "WHERE payload ->> 'invoice_id' = ANY(%s) ORDER BY id",
                [list(invoice_ids)],
            ).fetchall()
        return [
            {"ts": r[0].isoformat(), "actor": r[1], "action": r[2], "payload": r[3]} for r in rows
        ]

    def count_events(self, actor: str | None = None, day: str | None = None) -> int:
        sql, params, where = "SELECT count(*) FROM events", [], []
        if actor:
            where.append("actor = %s")
            params.append(actor)
        if day:
            start, end = kst.bounds(day)
            where.append("ts >= %s AND ts < %s")
            params += [start, end]
        if where:
            sql += " WHERE " + " AND ".join(where)
        with self.pool.connection() as conn:
            return conn.execute(sql, params).fetchone()[0]

    def recent_events(self, limit: int, day: str | None = None,
                      action: str | None = None) -> list[dict]:
        sql, where = "SELECT ts, actor, action, payload FROM events", []
        params: list[Any] = []
        if day:
            start, end = kst.bounds(day)
            where.append("ts >= %s AND ts < %s")
            params += [start, end]
        if action:
            where.append("action = %s")
            params.append(action)
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY id DESC LIMIT %s"
        params.append(limit)
        with self.pool.connection() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [
            {"ts": r[0].isoformat(), "actor": r[1], "action": r[2], "payload": r[3]} for r in rows
        ]

    def events_after(self, cursor: int) -> list[dict]:
        """append-only라 '앞에서 cursor개를 건너뛴 나머지'가 곧 새 이벤트다."""
        with self.pool.connection() as conn:
            rows = conn.execute(
                "SELECT ts, actor, action, payload FROM events ORDER BY id OFFSET %s",
                [cursor],
            ).fetchall()
        return [
            {"ts": r[0].isoformat(), "actor": r[1], "action": r[2], "payload": r[3]} for r in rows
        ]

    def log_event(self, actor: str, action: str, payload: dict) -> None:
        with self.pool.connection() as conn:
            conn.execute(
                "INSERT INTO events (actor, action, payload) VALUES (%s, %s, %s)",
                (actor, action, Jsonb(payload)),
            )

    # ── 관리 ──────────────────────────────────────────────────────
    def reset(self, keep: tuple[str, ...] = ()) -> None:
        with self.pool.connection() as conn:
            if keep:
                conn.execute("DELETE FROM documents WHERE collection <> ALL(%s)", (list(keep),))
                conn.execute("TRUNCATE events RESTART IDENTITY")
            else:
                conn.execute("TRUNCATE documents, events RESTART IDENTITY")

    def close(self) -> None:
        if not self.pool.closed:
            self.pool.close()
