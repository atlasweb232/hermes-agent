"""SQLite learning event bus for runtime learning sidecars."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import time
import uuid
from typing import Any, Dict, Iterable, List, Optional

from hermes_state import SessionDB


def _now() -> float:
    return time.time()


def _json_dumps(value: Optional[Dict[str, Any]]) -> str:
    return json.dumps(value or {}, sort_keys=True)


def _json_loads(value: Any) -> Dict[str, Any]:
    if not value:
        return {}
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(value)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


@dataclass
class LearningBusEvent:
    id: str
    topic: str
    status: str
    payload_json: Dict[str, Any] = field(default_factory=dict)
    tenant_id: Optional[str] = None
    repo_id: Optional[str] = None
    task_id: Optional[str] = None
    event_key: Optional[str] = None
    attempts: int = 0
    max_attempts: int = 3
    lease_owner: Optional[str] = None
    leased_until: Optional[float] = None
    consumed_at: Optional[float] = None
    created_at: float = field(default_factory=_now)
    updated_at: float = field(default_factory=_now)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class LearningBusConsumeResult:
    consumer: str
    leased: List[LearningBusEvent] = field(default_factory=list)
    dead_lettered: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "consumer": self.consumer,
            "leased": [event.to_dict() for event in self.leased],
            "dead_lettered": self.dead_lettered,
        }


def ensure_learning_bus_schema(db: SessionDB) -> None:
    def _do(conn):
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS hermes_learning_events (
                id TEXT PRIMARY KEY,
                tenant_id TEXT,
                repo_id TEXT,
                task_id TEXT,
                topic TEXT NOT NULL,
                event_key TEXT,
                status TEXT NOT NULL,
                payload_json TEXT,
                attempts INTEGER NOT NULL DEFAULT 0,
                max_attempts INTEGER NOT NULL DEFAULT 3,
                lease_owner TEXT,
                leased_until REAL,
                consumed_at REAL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_hermes_learning_events_topic_status
                ON hermes_learning_events(topic, status, created_at)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_hermes_learning_events_scope
                ON hermes_learning_events(tenant_id, repo_id, task_id, created_at DESC)
            """
        )
        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_hermes_learning_events_key
                ON hermes_learning_events(topic, event_key)
                WHERE event_key IS NOT NULL
            """
        )

    db._execute_write(_do)


def _row_to_event(row: Any) -> LearningBusEvent:
    return LearningBusEvent(
        id=row["id"],
        tenant_id=row["tenant_id"],
        repo_id=row["repo_id"],
        task_id=row["task_id"],
        topic=row["topic"],
        event_key=row["event_key"],
        status=row["status"],
        payload_json=_json_loads(row["payload_json"]),
        attempts=int(row["attempts"] or 0),
        max_attempts=int(row["max_attempts"] or 3),
        lease_owner=row["lease_owner"],
        leased_until=row["leased_until"],
        consumed_at=row["consumed_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def publish_learning_event(
    db: SessionDB,
    *,
    topic: str,
    payload: Optional[Dict[str, Any]] = None,
    tenant_id: Optional[str] = None,
    repo_id: Optional[str] = None,
    task_id: Optional[str] = None,
    event_key: Optional[str] = None,
    max_attempts: int = 3,
    event_id: Optional[str] = None,
) -> LearningBusEvent:
    ensure_learning_bus_schema(db)
    now = _now()
    eid = event_id or f"evt_{uuid.uuid4().hex[:16]}"
    attempts_limit = max(1, int(max_attempts or 3))

    if event_key:
        existing = db._conn.execute(
            "SELECT id FROM hermes_learning_events WHERE topic = ? AND event_key = ?",
            (topic, event_key),
        ).fetchone()
        if existing is not None:
            def _update(conn):
                conn.execute(
                    """
                    UPDATE hermes_learning_events
                       SET payload_json = ?,
                           status = CASE WHEN status = 'consumed' THEN status ELSE 'queued' END,
                           updated_at = ?
                     WHERE id = ?
                    """,
                    (_json_dumps(payload), now, existing["id"]),
                )

            db._execute_write(_update)
            row = db._conn.execute(
                "SELECT * FROM hermes_learning_events WHERE id = ?",
                (existing["id"],),
            ).fetchone()
            return _row_to_event(row)

    def _do(conn):
        conn.execute(
            """
            INSERT INTO hermes_learning_events (
                id, tenant_id, repo_id, task_id, topic, event_key, status,
                payload_json, attempts, max_attempts, lease_owner, leased_until,
                consumed_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'queued', ?, 0, ?, NULL, NULL, NULL, ?, ?)
            """,
            (
                eid,
                tenant_id,
                repo_id,
                task_id,
                topic,
                event_key,
                _json_dumps(payload),
                attempts_limit,
                now,
                now,
            ),
        )

    db._execute_write(_do)
    if event_key:
        row = db._conn.execute(
            "SELECT * FROM hermes_learning_events WHERE topic = ? AND event_key = ?",
            (topic, event_key),
        ).fetchone()
    else:
        row = db._conn.execute("SELECT * FROM hermes_learning_events WHERE id = ?", (eid,)).fetchone()
    return _row_to_event(row)


def publish_learning_event_safely(db: SessionDB, **kwargs: Any) -> Optional[LearningBusEvent]:
    try:
        return publish_learning_event(db, **kwargs)
    except Exception:
        return None


def list_learning_events(
    db: SessionDB,
    *,
    topic: Optional[str] = None,
    status: Optional[str] = None,
    tenant_id: Optional[str] = None,
    repo_id: Optional[str] = None,
    limit: int = 50,
) -> List[LearningBusEvent]:
    ensure_learning_bus_schema(db)
    clauses: List[str] = []
    params: List[Any] = []
    for key, value in (
        ("topic", topic),
        ("status", status),
        ("tenant_id", tenant_id),
        ("repo_id", repo_id),
    ):
        if value is not None:
            clauses.append(f"{key} = ?")
            params.append(value)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = db._conn.execute(
        f"""
        SELECT * FROM hermes_learning_events
        {where}
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (*params, max(1, int(limit))),
    ).fetchall()
    return [_row_to_event(row) for row in rows]


def _eligible_topic_clause(topics: Optional[Iterable[str]], params: List[Any]) -> str:
    topic_list = [str(topic) for topic in (topics or []) if str(topic or "").strip()]
    if not topic_list:
        return ""
    params.extend(topic_list)
    return f" AND topic IN ({', '.join(['?'] * len(topic_list))})"


def consume_learning_events(
    db: SessionDB,
    *,
    consumer: str,
    topics: Optional[Iterable[str]] = None,
    limit: int = 10,
    lease_seconds: float = 300.0,
    now: Optional[float] = None,
) -> LearningBusConsumeResult:
    ensure_learning_bus_schema(db)
    job_id = None
    try:
        from hermes_cli.learning_jobs import record_learning_job

        topic_list = [str(topic) for topic in (topics or []) if str(topic or "").strip()]
        job_id = record_learning_job(
            db,
            job_type="learning_bus_consumer",
            status="running",
            owner=consumer,
            metrics={
                "consumer": consumer,
                "topics": topic_list,
                "limit": max(1, int(limit)),
                "lease_seconds": float(lease_seconds or 300.0),
            },
        ).id
    except Exception:
        job_id = None
    current = _now() if now is None else now
    params: List[Any] = [current]
    topic_clause = _eligible_topic_clause(topics, params)
    rows = db._conn.execute(
        f"""
        SELECT * FROM hermes_learning_events
        WHERE status IN ('queued', 'leased')
          AND (status = 'queued' OR leased_until <= ?)
          {topic_clause}
        ORDER BY created_at ASC
        LIMIT ?
        """,
        (*params, max(1, int(limit))),
    ).fetchall()

    leased: List[LearningBusEvent] = []
    dead_lettered: List[str] = []
    for row in rows:
        event = _row_to_event(row)
        next_attempts = event.attempts + 1
        if next_attempts > event.max_attempts:
            mark_learning_event_dead(
                db,
                event.id,
                reason="max_attempts_exceeded",
                now=current,
            )
            dead_lettered.append(event.id)
            continue
        leased_until = current + max(1.0, float(lease_seconds or 300.0))

        def _do(conn, *, event_id=event.id):
            conn.execute(
                """
                UPDATE hermes_learning_events
                   SET status = 'leased',
                       attempts = ?,
                       lease_owner = ?,
                       leased_until = ?,
                       updated_at = ?
                 WHERE id = ?
                """,
                (next_attempts, consumer, leased_until, current, event_id),
            )

        db._execute_write(_do)
        refreshed = get_learning_event(db, event.id)
        if refreshed is not None:
            leased.append(refreshed)
    result = LearningBusConsumeResult(consumer=consumer, leased=leased, dead_lettered=dead_lettered)
    try:
        from hermes_cli.learning_jobs import update_learning_job

        if job_id:
            tenant_ids = sorted({event.tenant_id for event in leased if event.tenant_id})
            repo_ids = sorted({event.repo_id for event in leased if event.repo_id})
            update_learning_job(
                db,
                job_id,
                status="completed",
                metrics={
                    "consumer": consumer,
                    "leased": len(leased),
                    "dead_lettered": len(dead_lettered),
                    "tenant_ids": tenant_ids,
                    "repo_ids": repo_ids,
                },
            )
    except Exception:
        pass
    return result


def mark_learning_event_consumed(db: SessionDB, event_id: str, *, now: Optional[float] = None) -> Optional[LearningBusEvent]:
    ensure_learning_bus_schema(db)
    current = _now() if now is None else now

    def _do(conn):
        conn.execute(
            """
            UPDATE hermes_learning_events
               SET status = 'consumed',
                   consumed_at = ?,
                   lease_owner = NULL,
                   leased_until = NULL,
                   updated_at = ?
             WHERE id = ?
            """,
            (current, current, event_id),
        )

    db._execute_write(_do)
    return get_learning_event(db, event_id)


def mark_learning_event_dead(
    db: SessionDB,
    event_id: str,
    *,
    reason: str = "dead_lettered",
    now: Optional[float] = None,
) -> Optional[LearningBusEvent]:
    ensure_learning_bus_schema(db)
    current = _now() if now is None else now
    event = get_learning_event(db, event_id)
    payload = dict(event.payload_json) if event else {}
    payload["dead_letter_reason"] = reason

    def _do(conn):
        conn.execute(
            """
            UPDATE hermes_learning_events
               SET status = 'dead',
                   payload_json = ?,
                   lease_owner = NULL,
                   leased_until = NULL,
                   updated_at = ?
             WHERE id = ?
            """,
            (_json_dumps(payload), current, event_id),
        )

    db._execute_write(_do)
    return get_learning_event(db, event_id)


def get_learning_event(db: SessionDB, event_id: str) -> Optional[LearningBusEvent]:
    ensure_learning_bus_schema(db)
    row = db._conn.execute(
        "SELECT * FROM hermes_learning_events WHERE id = ?",
        (event_id,),
    ).fetchone()
    return _row_to_event(row) if row else None


def learning_bus_metrics(db: SessionDB) -> Dict[str, Any]:
    ensure_learning_bus_schema(db)
    rows = db._conn.execute(
        """
        SELECT status, COUNT(*) AS count
        FROM hermes_learning_events
        GROUP BY status
        """
    ).fetchall()
    by_status = {row["status"]: int(row["count"] or 0) for row in rows}
    return {
        "status": "ok",
        "by_status": by_status,
        "queued": by_status.get("queued", 0),
        "leased": by_status.get("leased", 0),
        "consumed": by_status.get("consumed", 0),
        "dead": by_status.get("dead", 0),
    }
