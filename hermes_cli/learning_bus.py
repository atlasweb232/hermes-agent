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
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS hermes_learning_bus_drains (
                drain_key TEXT NOT NULL,
                event_id TEXT NOT NULL,
                consumer TEXT NOT NULL,
                ack INTEGER NOT NULL DEFAULT 1,
                created_at REAL NOT NULL,
                PRIMARY KEY (drain_key, event_id)
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_hermes_learning_bus_drains_event
                ON hermes_learning_bus_drains(event_id, created_at)
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


def _bounded_limit(limit: int, *, default: int = 50) -> int:
    try:
        parsed = int(limit)
    except Exception:
        parsed = default
    return max(1, min(parsed, 500))


def _event_audit_metadata(event: LearningBusEvent, *, now: Optional[float] = None) -> Dict[str, Any]:
    payload_text = _json_dumps(event.payload_json)
    lease_expired = (
        event.status == "leased"
        and event.leased_until is not None
        and event.leased_until <= (_now() if now is None else now)
    )
    return {
        "id": event.id,
        "topic": event.topic,
        "tenant_id": event.tenant_id,
        "repo_id": event.repo_id,
        "task_id": event.task_id,
        "event_key_present": bool(event.event_key),
        "attempts": event.attempts,
        "max_attempts": event.max_attempts,
        "lease_owner": event.lease_owner,
        "lease_expired": bool(lease_expired),
        "created_at": event.created_at,
        "updated_at": event.updated_at,
        "consumed_at": event.consumed_at,
        "payload_redacted": True,
        "payload_size_bytes": len(payload_text.encode("utf-8")),
        "payload_key_count": len(event.payload_json) if isinstance(event.payload_json, dict) else 0,
    }


def _event_where(filters: Dict[str, Optional[str]], params: List[Any]) -> str:
    clauses = []
    for key in ("topic", "tenant_id", "repo_id"):
        value = filters.get(key)
        if value is not None:
            clauses.append(f"{key} = ?")
            params.append(value)
    return f"WHERE {' AND '.join(clauses)}" if clauses else ""


def audit_learning_bus(
    db: SessionDB,
    *,
    topic: Optional[str] = None,
    tenant_id: Optional[str] = None,
    repo_id: Optional[str] = None,
    limit: int = 50,
    now: Optional[float] = None,
) -> Dict[str, Any]:
    """Return redacted, JSON-serializable queue state for operator audits."""
    ensure_learning_bus_schema(db)
    current = _now() if now is None else now
    filters = {"topic": topic, "tenant_id": tenant_id, "repo_id": repo_id}
    count_params: List[Any] = []
    where = _event_where(filters, count_params)
    rows = db._conn.execute(
        f"""
        SELECT status, COUNT(*) AS count
        FROM hermes_learning_events
        {where}
        GROUP BY status
        """,
        tuple(count_params),
    ).fetchall()
    status_counts = {status: 0 for status in ("queued", "leased", "consumed", "dead")}
    status_counts.update({row["status"]: int(row["count"] or 0) for row in rows})

    samples: Dict[str, List[Dict[str, Any]]] = {status: [] for status in status_counts}
    sample_limit = _bounded_limit(limit)
    for status in ("queued", "leased", "consumed", "dead"):
        params: List[Any] = []
        scoped_where = _event_where(filters, params)
        status_clause = "status = ?"
        if scoped_where:
            scoped_where = f"{scoped_where} AND {status_clause}"
        else:
            scoped_where = f"WHERE {status_clause}"
        params.append(status)
        status_rows = db._conn.execute(
            f"""
            SELECT * FROM hermes_learning_events
            {scoped_where}
            ORDER BY created_at ASC
            LIMIT ?
            """,
            (*params, sample_limit),
        ).fetchall()
        samples[status] = [
            _event_audit_metadata(_row_to_event(row), now=current) for row in status_rows
        ]

    replay_params: List[Any] = []
    replay_where = _event_where(filters, replay_params)
    if replay_where:
        replay_where = f"{replay_where} AND status = 'leased' AND leased_until <= ?"
    else:
        replay_where = "WHERE status = 'leased' AND leased_until <= ?"
    replay_params.append(current)
    replayable_expired = db._conn.execute(
        f"SELECT COUNT(*) AS count FROM hermes_learning_events {replay_where}",
        tuple(replay_params),
    ).fetchone()["count"]

    key_params: List[Any] = []
    key_where = _event_where(filters, key_params)
    if key_where:
        key_where = f"{key_where} AND event_key IS NOT NULL"
    else:
        key_where = "WHERE event_key IS NOT NULL"
    idempotency_keys_present = db._conn.execute(
        f"SELECT COUNT(*) AS count FROM hermes_learning_events {key_where}",
        tuple(key_params),
    ).fetchone()["count"]

    queued_backlog = status_counts.get("queued", 0)
    replayable_count = int(replayable_expired or 0)
    sidecar_required = queued_backlog > 0 or replayable_count > 0
    if sidecar_required:
        reason = (
            "queued backlog or replayable expired leases exist; repeated manual drain "
            "or multi-instance operation should use a dedicated local consumer sidecar before Kafka/Redpanda"
        )
    else:
        reason = (
            "no queued backlog or replayable expired leases were found; single-node/dev "
            "operation can remain manual CLI/local sidecar"
        )

    return {
        "status": "ok",
        "backend": "sqlite",
        "filters": {key: value for key, value in filters.items() if value is not None},
        "status_counts": status_counts,
        "samples": samples,
        "replay_safety": {
            "replayable_expired_leases": replayable_count,
            "non_replayable_consumed": status_counts.get("consumed", 0),
            "non_replayable_dead": status_counts.get("dead", 0),
            "idempotency_keys_present": int(idempotency_keys_present or 0),
        },
        "dedicated_consumer_sidecar_required": sidecar_required,
        "dedicated_consumer_sidecar_reason": reason,
    }


def _drain_records_for_key(db: SessionDB, drain_key: str, *, now: Optional[float] = None) -> List[Dict[str, Any]]:
    rows = db._conn.execute(
        """
        SELECT e.*
        FROM hermes_learning_bus_drains d
        JOIN hermes_learning_events e ON e.id = d.event_id
        WHERE d.drain_key = ?
        ORDER BY d.created_at ASC
        """,
        (drain_key,),
    ).fetchall()
    return [_event_audit_metadata(_row_to_event(row), now=now) for row in rows]


def drain_learning_bus_batch(
    db: SessionDB,
    *,
    consumer: str,
    topics: Optional[Iterable[str]] = None,
    limit: int = 10,
    lease_seconds: float = 300.0,
    drain_key: str,
    ack: bool = True,
    now: Optional[float] = None,
) -> Dict[str, Any]:
    """Lease one batch and optionally ack it, idempotently keyed by drain_key."""
    ensure_learning_bus_schema(db)
    key = str(drain_key or "").strip()
    if not key:
        raise ValueError("drain_key is required")
    current = _now() if now is None else now
    existing = _drain_records_for_key(db, key, now=current)
    if existing:
        return {
            "status": "ok",
            "consumer": consumer,
            "drain_key": key,
            "idempotent_replay": True,
            "ack": bool(ack),
            "drained_count": 0,
            "already_drained_count": len(existing),
            "events": [],
            "already_drained": existing,
        }

    result = consume_learning_events(
        db,
        consumer=consumer,
        topics=topics,
        limit=_bounded_limit(limit, default=10),
        lease_seconds=lease_seconds,
        now=current,
    )
    drained: List[Dict[str, Any]] = []
    for event in result.leased:
        def _record(conn, *, event_id=event.id):
            conn.execute(
                """
                INSERT OR IGNORE INTO hermes_learning_bus_drains (
                    drain_key, event_id, consumer, ack, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (key, event_id, consumer, 1 if ack else 0, current),
            )

        db._execute_write(_record)
        final_event = mark_learning_event_consumed(db, event.id, now=current) if ack else get_learning_event(db, event.id)
        drained.append(_event_audit_metadata(final_event or event, now=current))

    return {
        "status": "ok",
        "consumer": consumer,
        "drain_key": key,
        "idempotent_replay": False,
        "ack": bool(ack),
        "drained_count": len(drained),
        "already_drained_count": 0,
        "events": drained,
        "already_drained": [],
        "dead_lettered": result.dead_lettered,
    }


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
