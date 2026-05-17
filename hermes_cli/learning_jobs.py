"""SQLite-backed learning job records for runtime sidecars and orchestration."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

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
class LearningJobRecord:
    id: str
    job_type: str
    status: str
    owner: Optional[str] = None
    tenant_id: Optional[str] = None
    repo_id: Optional[str] = None
    task_id: Optional[str] = None
    heartbeat_at: Optional[float] = None
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    metrics_json: Dict[str, Any] = field(default_factory=dict)
    error_json: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=_now)
    updated_at: float = field(default_factory=_now)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def ensure_learning_jobs_schema(db: SessionDB) -> None:
    """Create learning job tables. Safe to call repeatedly."""

    def _do(conn):
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS hermes_learning_jobs (
                id TEXT PRIMARY KEY,
                tenant_id TEXT,
                repo_id TEXT,
                task_id TEXT,
                job_type TEXT NOT NULL,
                status TEXT NOT NULL,
                owner TEXT,
                heartbeat_at REAL,
                started_at REAL,
                finished_at REAL,
                metrics_json TEXT,
                error_json TEXT,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_hermes_learning_jobs_scope
                ON hermes_learning_jobs(tenant_id, repo_id, task_id, created_at DESC)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_hermes_learning_jobs_status
                ON hermes_learning_jobs(status, job_type, updated_at DESC)
            """
        )

    db._execute_write(_do)


def record_learning_job(
    db: SessionDB,
    *,
    job_type: str,
    status: str = "queued",
    job_id: Optional[str] = None,
    owner: Optional[str] = None,
    tenant_id: Optional[str] = None,
    repo_id: Optional[str] = None,
    task_id: Optional[str] = None,
    metrics: Optional[Dict[str, Any]] = None,
    error: Optional[Dict[str, Any]] = None,
) -> LearningJobRecord:
    ensure_learning_jobs_schema(db)
    now = _now()
    jid = job_id or f"job_{uuid.uuid4().hex[:16]}"
    started_at = now if status == "running" else None
    finished_at = now if status in {"completed", "failed", "blocked"} else None

    def _do(conn):
        conn.execute(
            """
            INSERT INTO hermes_learning_jobs (
                id, tenant_id, repo_id, task_id, job_type, status, owner,
                heartbeat_at, started_at, finished_at, metrics_json, error_json,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                tenant_id = excluded.tenant_id,
                repo_id = excluded.repo_id,
                task_id = excluded.task_id,
                job_type = excluded.job_type,
                status = excluded.status,
                owner = excluded.owner,
                heartbeat_at = excluded.heartbeat_at,
                started_at = COALESCE(hermes_learning_jobs.started_at, excluded.started_at),
                finished_at = excluded.finished_at,
                metrics_json = excluded.metrics_json,
                error_json = excluded.error_json,
                updated_at = excluded.updated_at
            """,
            (
                jid,
                tenant_id,
                repo_id,
                task_id,
                job_type,
                status,
                owner,
                now,
                started_at,
                finished_at,
                _json_dumps(metrics),
                _json_dumps(error),
                now,
                now,
            ),
        )

    db._execute_write(_do)
    return get_learning_job(db, jid)  # type: ignore[return-value]


def update_learning_job(
    db: SessionDB,
    job_id: str,
    *,
    status: Optional[str] = None,
    owner: Optional[str] = None,
    metrics: Optional[Dict[str, Any]] = None,
    error: Optional[Dict[str, Any]] = None,
    heartbeat: bool = True,
) -> Optional[LearningJobRecord]:
    ensure_learning_jobs_schema(db)
    existing = get_learning_job(db, job_id)
    if existing is None:
        return None
    next_status = status or existing.status
    now = _now()
    finished_at = existing.finished_at
    if next_status in {"completed", "failed", "blocked"} and finished_at is None:
        finished_at = now

    def _do(conn):
        conn.execute(
            """
            UPDATE hermes_learning_jobs
               SET status = ?,
                   owner = COALESCE(?, owner),
                   heartbeat_at = CASE WHEN ? THEN ? ELSE heartbeat_at END,
                   finished_at = ?,
                   metrics_json = ?,
                   error_json = ?,
                   updated_at = ?
             WHERE id = ?
            """,
            (
                next_status,
                owner,
                1 if heartbeat else 0,
                now,
                finished_at,
                _json_dumps(metrics if metrics is not None else existing.metrics_json),
                _json_dumps(error if error is not None else existing.error_json),
                now,
                job_id,
            ),
        )

    db._execute_write(_do)
    return get_learning_job(db, job_id)


def _row_to_record(row: Any) -> LearningJobRecord:
    return LearningJobRecord(
        id=row["id"],
        tenant_id=row["tenant_id"],
        repo_id=row["repo_id"],
        task_id=row["task_id"],
        job_type=row["job_type"],
        status=row["status"],
        owner=row["owner"],
        heartbeat_at=row["heartbeat_at"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        metrics_json=_json_loads(row["metrics_json"]),
        error_json=_json_loads(row["error_json"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def get_learning_job(db: SessionDB, job_id: str) -> Optional[LearningJobRecord]:
    ensure_learning_jobs_schema(db)
    row = db._conn.execute(
        "SELECT * FROM hermes_learning_jobs WHERE id = ?",
        (job_id,),
    ).fetchone()
    return _row_to_record(row) if row else None


def list_learning_jobs(
    db: SessionDB,
    *,
    tenant_id: Optional[str] = None,
    repo_id: Optional[str] = None,
    task_id: Optional[str] = None,
    job_type: Optional[str] = None,
    status: Optional[str] = None,
    owner: Optional[str] = None,
    started_after: Optional[float] = None,
    started_before: Optional[float] = None,
    blocker: Optional[str] = None,
    limit: int = 100,
) -> List[LearningJobRecord]:
    ensure_learning_jobs_schema(db)
    clauses: List[str] = []
    params: List[Any] = []
    if tenant_id is not None:
        clauses.append("tenant_id = ?")
        params.append(tenant_id)
    if repo_id is not None:
        clauses.append("repo_id = ?")
        params.append(repo_id)
    if task_id is not None:
        clauses.append("task_id = ?")
        params.append(task_id)
    if job_type is not None:
        clauses.append("job_type = ?")
        params.append(job_type)
    if status is not None:
        clauses.append("status = ?")
        params.append(status)
    if owner is not None:
        clauses.append("owner = ?")
        params.append(owner)
    if started_after is not None:
        clauses.append("created_at >= ?")
        params.append(float(started_after))
    if started_before is not None:
        clauses.append("created_at <= ?")
        params.append(float(started_before))
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(max(1, int(limit)))
    rows = db._conn.execute(
        f"""
        SELECT * FROM hermes_learning_jobs
        {where}
        ORDER BY updated_at DESC
        LIMIT ?
        """,
        params,
    ).fetchall()
    records = [_row_to_record(row) for row in rows]
    if blocker:
        needle = str(blocker).casefold()
        records = [
            record
            for record in records
            if needle
            in json.dumps(
                {"metrics": record.metrics_json, "error": record.error_json},
                sort_keys=True,
                ensure_ascii=False,
            ).casefold()
        ]
    return records
