"""Durable worker/tool/sidecar event store for context offloading."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import time
import uuid
from typing import Any, Mapping

from hermes_state import SessionDB
from hermes_cli.redaction_guard import redact_text as _guard_redact_text, redact_value


def _now() -> float:
    return time.time()


def redact_text(text: str, *, max_chars: int | None = None) -> str:
    return _guard_redact_text(text, max_chars=max_chars)


def redact_payload(value: Any) -> Any:
    """Recursively redact provider credentials before persistence.

    Worker event payloads often contain command metadata, env excerpts, or
    validation output. They are stored outside supervisor context, but still
    must be safe for UI, Slack, audit, and corpus sidecars.
    """

    return redact_value(value)


def _json_dumps(value: Mapping[str, Any] | None) -> str:
    return json.dumps(value or {}, sort_keys=True)


def _json_loads(value: Any) -> dict[str, Any]:
    if not value:
        return {}
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(value)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


@dataclass(frozen=True)
class WorkerEvent:
    id: str
    ref: str
    kind: str
    source: str
    summary: str
    tenant_id: str | None = None
    repo_id: str | None = None
    task_id: str | None = None
    worker_id: str | None = None
    payload_json: dict[str, Any] = field(default_factory=dict)
    raw_size_bytes: int = 0
    redacted: bool = True
    foreground_admitted: bool = False
    created_at: float = field(default_factory=_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def ensure_worker_event_schema(db: SessionDB) -> None:
    def _do(conn):
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS hermes_worker_events (
                id TEXT PRIMARY KEY,
                ref TEXT NOT NULL UNIQUE,
                tenant_id TEXT,
                repo_id TEXT,
                task_id TEXT,
                worker_id TEXT,
                kind TEXT NOT NULL,
                source TEXT,
                summary TEXT,
                payload_json TEXT,
                raw_size_bytes INTEGER NOT NULL DEFAULT 0,
                redacted INTEGER NOT NULL DEFAULT 1,
                foreground_admitted INTEGER NOT NULL DEFAULT 0,
                created_at REAL NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_hermes_worker_events_task
                ON hermes_worker_events(tenant_id, repo_id, task_id, created_at DESC)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_hermes_worker_events_kind
                ON hermes_worker_events(kind, created_at DESC)
            """
        )

    db._execute_write(_do)


def _row_to_event(row: Any) -> WorkerEvent:
    return WorkerEvent(
        id=row["id"],
        ref=row["ref"],
        tenant_id=row["tenant_id"],
        repo_id=row["repo_id"],
        task_id=row["task_id"],
        worker_id=row["worker_id"],
        kind=row["kind"],
        source=row["source"] or "",
        summary=row["summary"] or "",
        payload_json=_json_loads(row["payload_json"]),
        raw_size_bytes=int(row["raw_size_bytes"] or 0),
        redacted=bool(row["redacted"]),
        foreground_admitted=bool(row["foreground_admitted"]),
        created_at=float(row["created_at"] or 0),
    )


def store_worker_event(
    db: SessionDB,
    *,
    kind: str,
    content: str,
    source: str = "",
    tenant_id: str | None = None,
    repo_id: str | None = None,
    task_id: str | None = None,
    worker_id: str | None = None,
    payload: Mapping[str, Any] | None = None,
    foreground_admitted: bool = False,
    event_id: str | None = None,
    now: float | None = None,
) -> WorkerEvent:
    ensure_worker_event_schema(db)
    timestamp = _now() if now is None else float(now)
    eid = event_id or f"wevt_{uuid.uuid4().hex[:16]}"
    ref = f"event://worker/{eid}"
    raw_size = len(str(content or "").encode("utf-8"))
    summary = redact_text(content, max_chars=500)
    payload_json = {
        **redact_payload(dict(payload or {})),
        "content_ref": ref,
        "raw_size_bytes": raw_size,
        "redaction_state": "redacted",
    }

    def _do(conn):
        conn.execute(
            """
            INSERT OR REPLACE INTO hermes_worker_events (
                id, ref, tenant_id, repo_id, task_id, worker_id, kind, source,
                summary, payload_json, raw_size_bytes, redacted,
                foreground_admitted, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
            """,
            (
                eid,
                ref,
                tenant_id,
                repo_id,
                task_id,
                worker_id,
                kind,
                source,
                summary,
                _json_dumps(payload_json),
                raw_size,
                1 if foreground_admitted else 0,
                timestamp,
            ),
        )

    db._execute_write(_do)
    row = db._conn.execute("SELECT * FROM hermes_worker_events WHERE id = ?", (eid,)).fetchone()
    return _row_to_event(row)


def list_worker_events(
    db: SessionDB,
    *,
    tenant_id: str | None = None,
    repo_id: str | None = None,
    task_id: str | None = None,
    kind: str | None = None,
    limit: int = 50,
) -> list[WorkerEvent]:
    ensure_worker_event_schema(db)
    clauses: list[str] = []
    params: list[Any] = []
    for key, value in (
        ("tenant_id", tenant_id),
        ("repo_id", repo_id),
        ("task_id", task_id),
        ("kind", kind),
    ):
        if value is not None:
            clauses.append(f"{key} = ?")
            params.append(value)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = db._conn.execute(
        f"""
        SELECT * FROM hermes_worker_events
        {where}
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (*params, max(1, min(int(limit or 50), 500))),
    ).fetchall()
    return [_row_to_event(row) for row in rows]
