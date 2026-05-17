"""Supervisor convergence control plane.

This module tracks delegated work independently of any one worker process.
It is intentionally deterministic: leases, heartbeats, recovery packets, and
override actions are persisted in SQLite so the supervisor can reclaim or
reassign stuck work after restarts without trusting a model transcript.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import time
import uuid
from typing import Any, Dict, List, Optional

from hermes_cli.config import load_config
from hermes_state import SessionDB


TERMINAL_STATES = {"completed", "abandoned"}
GOAL_BLOCKED_STATES = {"reclaimed", "blocked", "validation_failed", "reassigned", "abandoned"}


def _now() -> float:
    return time.time()


def _json_dumps(value: Any) -> str:
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


def _list_json_loads(value: Any) -> List[Any]:
    if not value:
        return []
    if isinstance(value, list):
        return value
    try:
        parsed = json.loads(value)
    except Exception:
        return []
    return parsed if isinstance(parsed, list) else []


@dataclass
class SupervisorTaskLedgerEntry:
    task_id: str
    state: str
    tenant_id: Optional[str] = None
    repo_id: Optional[str] = None
    worker_id: Optional[str] = None
    worker_kind: Optional[str] = None
    task_description: str = ""
    lease_owner: Optional[str] = None
    lease_expires_at: Optional[float] = None
    heartbeat_at: Optional[float] = None
    retry_budget: int = 3
    retry_count: int = 0
    spec_kit_refs: List[str] = field(default_factory=list)
    git_refs: List[str] = field(default_factory=list)
    metadata_json: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=_now)
    updated_at: float = field(default_factory=_now)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class WorkerHeartbeat:
    id: str
    task_id: str
    worker_id: str
    status: str
    progress_signature: Optional[str] = None
    command_signature: Optional[str] = None
    error_signature: Optional[str] = None
    git_head: Optional[str] = None
    test_signature: Optional[str] = None
    metadata_json: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=_now)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class RecoveryPacket:
    id: str
    task_id: str
    reason: str
    status: str
    failed_commands: List[str] = field(default_factory=list)
    error_signatures: List[str] = field(default_factory=list)
    validation_failures: List[str] = field(default_factory=list)
    memory_packet_refs: List[str] = field(default_factory=list)
    git_refs: List[str] = field(default_factory=list)
    next_worker_recommendation: Optional[str] = None
    evidence_json: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=_now)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class OverrideAction:
    id: str
    task_id: str
    action: str
    operator: str
    reason: str
    previous_state: str
    new_state: str
    worker_id: Optional[str] = None
    metadata_json: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=_now)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ConvergenceAssessment:
    task_id: str
    status: str
    reclaimable: bool
    reasons: List[str] = field(default_factory=list)
    recommended_action: str = "none"
    metrics: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def ensure_supervisor_control_schema(db: SessionDB) -> None:
    def _do(conn):
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS hermes_supervisor_tasks (
                task_id TEXT PRIMARY KEY,
                tenant_id TEXT,
                repo_id TEXT,
                state TEXT NOT NULL,
                worker_id TEXT,
                worker_kind TEXT,
                task_description TEXT,
                lease_owner TEXT,
                lease_expires_at REAL,
                heartbeat_at REAL,
                retry_budget INTEGER NOT NULL DEFAULT 3,
                retry_count INTEGER NOT NULL DEFAULT 0,
                spec_kit_refs_json TEXT,
                git_refs_json TEXT,
                metadata_json TEXT,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS hermes_supervisor_heartbeats (
                id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                worker_id TEXT NOT NULL,
                status TEXT NOT NULL,
                progress_signature TEXT,
                command_signature TEXT,
                error_signature TEXT,
                git_head TEXT,
                test_signature TEXT,
                metadata_json TEXT,
                created_at REAL NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_hermes_supervisor_heartbeats_task
                ON hermes_supervisor_heartbeats(task_id, created_at DESC)
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS hermes_supervisor_recovery_packets (
                id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                reason TEXT NOT NULL,
                status TEXT NOT NULL,
                failed_commands_json TEXT,
                error_signatures_json TEXT,
                validation_failures_json TEXT,
                memory_packet_refs_json TEXT,
                git_refs_json TEXT,
                next_worker_recommendation TEXT,
                evidence_json TEXT,
                created_at REAL NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS hermes_supervisor_override_actions (
                id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                action TEXT NOT NULL,
                operator TEXT NOT NULL,
                reason TEXT NOT NULL,
                previous_state TEXT NOT NULL,
                new_state TEXT NOT NULL,
                worker_id TEXT,
                metadata_json TEXT,
                created_at REAL NOT NULL
            )
            """
        )

    db._execute_write(_do)


def _row_to_task(row: Any) -> SupervisorTaskLedgerEntry:
    return SupervisorTaskLedgerEntry(
        task_id=row["task_id"],
        tenant_id=row["tenant_id"],
        repo_id=row["repo_id"],
        state=row["state"],
        worker_id=row["worker_id"],
        worker_kind=row["worker_kind"],
        task_description=row["task_description"] or "",
        lease_owner=row["lease_owner"],
        lease_expires_at=row["lease_expires_at"],
        heartbeat_at=row["heartbeat_at"],
        retry_budget=int(row["retry_budget"] or 3),
        retry_count=int(row["retry_count"] or 0),
        spec_kit_refs=[str(x) for x in _list_json_loads(row["spec_kit_refs_json"])],
        git_refs=[str(x) for x in _list_json_loads(row["git_refs_json"])],
        metadata_json=_json_loads(row["metadata_json"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_heartbeat(row: Any) -> WorkerHeartbeat:
    return WorkerHeartbeat(
        id=row["id"],
        task_id=row["task_id"],
        worker_id=row["worker_id"],
        status=row["status"],
        progress_signature=row["progress_signature"],
        command_signature=row["command_signature"],
        error_signature=row["error_signature"],
        git_head=row["git_head"],
        test_signature=row["test_signature"],
        metadata_json=_json_loads(row["metadata_json"]),
        created_at=row["created_at"],
    )


def create_task_ledger_entry(
    db: SessionDB,
    *,
    task_id: Optional[str] = None,
    tenant_id: Optional[str] = None,
    repo_id: Optional[str] = None,
    task_description: str = "",
    worker_id: Optional[str] = None,
    worker_kind: Optional[str] = None,
    lease_owner: Optional[str] = None,
    lease_seconds: float = 900.0,
    retry_budget: int = 3,
    spec_kit_refs: Optional[List[str]] = None,
    git_refs: Optional[List[str]] = None,
    metadata: Optional[Dict[str, Any]] = None,
    now: Optional[float] = None,
) -> SupervisorTaskLedgerEntry:
    ensure_supervisor_control_schema(db)
    current = _now() if now is None else float(now)
    tid = task_id or f"task_{uuid.uuid4().hex[:16]}"
    owner = lease_owner or worker_id
    lease_expires = current + max(1.0, float(lease_seconds or 900.0)) if owner else None

    def _do(conn):
        conn.execute(
            """
            INSERT INTO hermes_supervisor_tasks (
                task_id, tenant_id, repo_id, state, worker_id, worker_kind,
                task_description, lease_owner, lease_expires_at, heartbeat_at,
                retry_budget, retry_count, spec_kit_refs_json, git_refs_json,
                metadata_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, 0, ?, ?, ?, ?, ?)
            ON CONFLICT(task_id) DO UPDATE SET
                tenant_id = excluded.tenant_id,
                repo_id = excluded.repo_id,
                worker_id = excluded.worker_id,
                worker_kind = excluded.worker_kind,
                task_description = excluded.task_description,
                lease_owner = excluded.lease_owner,
                lease_expires_at = excluded.lease_expires_at,
                retry_budget = excluded.retry_budget,
                spec_kit_refs_json = excluded.spec_kit_refs_json,
                git_refs_json = excluded.git_refs_json,
                metadata_json = excluded.metadata_json,
                updated_at = excluded.updated_at
            """,
            (
                tid,
                tenant_id,
                repo_id,
                "running" if worker_id else "ready",
                worker_id,
                worker_kind,
                task_description,
                owner,
                lease_expires,
                int(retry_budget),
                _json_dumps(spec_kit_refs or []),
                _json_dumps(git_refs or []),
                _json_dumps(metadata or {}),
                current,
                current,
            ),
        )

    db._execute_write(_do)
    entry = get_task_ledger_entry(db, tid)
    assert entry is not None
    return entry


def get_task_ledger_entry(db: SessionDB, task_id: str) -> Optional[SupervisorTaskLedgerEntry]:
    ensure_supervisor_control_schema(db)
    row = db._conn.execute(
        "SELECT * FROM hermes_supervisor_tasks WHERE task_id = ?",
        (task_id,),
    ).fetchone()
    return _row_to_task(row) if row else None


def list_task_ledger_entries(
    db: SessionDB,
    *,
    tenant_id: Optional[str] = None,
    repo_id: Optional[str] = None,
    state: Optional[str] = None,
    limit: int = 100,
) -> List[SupervisorTaskLedgerEntry]:
    ensure_supervisor_control_schema(db)
    clauses: List[str] = []
    params: List[Any] = []
    for key, value in (("tenant_id", tenant_id), ("repo_id", repo_id), ("state", state)):
        if value is not None:
            clauses.append(f"{key} = ?")
            params.append(value)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = db._conn.execute(
        f"""
        SELECT * FROM hermes_supervisor_tasks
        {where}
        ORDER BY updated_at DESC
        LIMIT ?
        """,
        (*params, max(1, int(limit))),
    ).fetchall()
    return [_row_to_task(row) for row in rows]


def record_worker_heartbeat(
    db: SessionDB,
    *,
    task_id: str,
    worker_id: str,
    status: str = "running",
    progress_signature: Optional[str] = None,
    command_signature: Optional[str] = None,
    error_signature: Optional[str] = None,
    git_head: Optional[str] = None,
    test_signature: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    lease_seconds: float = 900.0,
    now: Optional[float] = None,
) -> WorkerHeartbeat:
    ensure_supervisor_control_schema(db)
    current = _now() if now is None else float(now)
    hid = f"hb_{uuid.uuid4().hex[:16]}"

    def _do(conn):
        conn.execute(
            """
            INSERT INTO hermes_supervisor_heartbeats (
                id, task_id, worker_id, status, progress_signature,
                command_signature, error_signature, git_head, test_signature,
                metadata_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                hid,
                task_id,
                worker_id,
                status,
                progress_signature,
                command_signature,
                error_signature,
                git_head,
                test_signature,
                _json_dumps(metadata or {}),
                current,
            ),
        )
        conn.execute(
            """
            UPDATE hermes_supervisor_tasks
               SET worker_id = ?,
                   heartbeat_at = ?,
                   lease_owner = ?,
                   lease_expires_at = ?,
                   state = CASE WHEN state IN ('ready', 'running') THEN 'running' ELSE state END,
                   updated_at = ?
             WHERE task_id = ?
            """,
            (
                worker_id,
                current,
                worker_id,
                current + max(1.0, float(lease_seconds or 900.0)),
                current,
                task_id,
            ),
        )

    db._execute_write(_do)
    row = db._conn.execute(
        "SELECT * FROM hermes_supervisor_heartbeats WHERE id = ?",
        (hid,),
    ).fetchone()
    return _row_to_heartbeat(row)


def list_worker_heartbeats(db: SessionDB, *, task_id: str, limit: int = 20) -> List[WorkerHeartbeat]:
    ensure_supervisor_control_schema(db)
    rows = db._conn.execute(
        """
        SELECT * FROM hermes_supervisor_heartbeats
         WHERE task_id = ?
         ORDER BY created_at DESC
         LIMIT ?
        """,
        (task_id, max(1, int(limit))),
    ).fetchall()
    return [_row_to_heartbeat(row) for row in rows]


def _control_policy(config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    cfg = config or load_config()
    supervisor = cfg.get("supervisor") if isinstance(cfg, dict) else {}
    control = (supervisor or {}).get("control_plane") if isinstance(supervisor, dict) else {}
    return control if isinstance(control, dict) else {}


def assess_task_convergence(
    db: SessionDB,
    *,
    task_id: str,
    config: Optional[Dict[str, Any]] = None,
    now: Optional[float] = None,
) -> ConvergenceAssessment:
    entry = get_task_ledger_entry(db, task_id)
    if entry is None:
        raise ValueError(f"unknown supervisor task: {task_id}")
    current = _now() if now is None else float(now)
    policy = _control_policy(config)
    heartbeat_timeout = float(policy.get("heartbeat_timeout_seconds", 600) or 600)
    no_progress_window = int(policy.get("no_progress_heartbeat_window", 3) or 3)
    repeated_error_window = int(policy.get("repeated_error_window", 3) or 3)
    reasons: List[str] = []

    if entry.state in TERMINAL_STATES:
        return ConvergenceAssessment(
            task_id=task_id,
            status="terminal",
            reclaimable=False,
            reasons=[f"state:{entry.state}"],
            recommended_action="none",
            metrics={"state": entry.state},
        )
    if entry.lease_expires_at is not None and entry.lease_expires_at <= current:
        reasons.append("lease_expired")
    if entry.heartbeat_at is None:
        reasons.append("missing_heartbeat")
    elif current - entry.heartbeat_at >= heartbeat_timeout:
        reasons.append("heartbeat_stale")
    if entry.retry_count >= entry.retry_budget:
        reasons.append("retry_budget_exhausted")

    heartbeats = list_worker_heartbeats(db, task_id=task_id, limit=max(no_progress_window, repeated_error_window, 5))
    newest = list(reversed(heartbeats))
    if len(newest) >= no_progress_window:
        recent = newest[-no_progress_window:]
        progress_values = {hb.progress_signature for hb in recent if hb.progress_signature}
        git_values = {hb.git_head for hb in recent if hb.git_head}
        test_values = {hb.test_signature for hb in recent if hb.test_signature}
        if len(progress_values) == 1 and len(git_values) <= 1 and len(test_values) <= 1:
            reasons.append("no_progress_loop")
    if len(newest) >= repeated_error_window:
        recent = newest[-repeated_error_window:]
        errors = [hb.error_signature for hb in recent if hb.error_signature]
        commands = [hb.command_signature for hb in recent if hb.command_signature]
        if len(errors) == repeated_error_window and len(set(errors)) == 1:
            reasons.append("repeated_error_signature")
        if len(commands) == repeated_error_window and len(set(commands)) == 1:
            reasons.append("repeated_command_signature")

    reclaimable = bool(reasons)
    status = "reclaimable" if reclaimable else "healthy"
    action = "reclaim" if reclaimable else "none"
    return ConvergenceAssessment(
        task_id=task_id,
        status=status,
        reclaimable=reclaimable,
        reasons=sorted(set(reasons)),
        recommended_action=action,
        metrics={
            "state": entry.state,
            "heartbeat_count": len(heartbeats),
            "retry_count": entry.retry_count,
            "retry_budget": entry.retry_budget,
            "lease_expires_at": entry.lease_expires_at,
            "heartbeat_at": entry.heartbeat_at,
            "now": current,
        },
    )


def create_recovery_packet(
    db: SessionDB,
    *,
    task_id: str,
    reason: str,
    config: Optional[Dict[str, Any]] = None,
) -> RecoveryPacket:
    entry = get_task_ledger_entry(db, task_id)
    if entry is None:
        raise ValueError(f"unknown supervisor task: {task_id}")
    heartbeats = list_worker_heartbeats(db, task_id=task_id, limit=20)
    failed_commands = sorted({hb.command_signature for hb in heartbeats if hb.command_signature and hb.status in {"failed", "blocked", "error"}})
    error_signatures = sorted({hb.error_signature for hb in heartbeats if hb.error_signature})
    validation_failures = [
        str(hb.metadata_json.get("validation_failure"))
        for hb in heartbeats
        if hb.metadata_json.get("validation_failure")
    ]
    memory_refs = [
        str(hb.metadata_json.get("memory_packet_id"))
        for hb in heartbeats
        if hb.metadata_json.get("memory_packet_id")
    ]
    policy = _control_policy(config)
    fallback_order = [str(x) for x in (policy.get("worker_fallback_order") or ["codex", "claude-code", "deepseek"]) if str(x)]
    next_worker = next((worker for worker in fallback_order if worker != entry.worker_id), None)
    packet = RecoveryPacket(
        id=f"recov_{uuid.uuid4().hex[:16]}",
        task_id=task_id,
        reason=reason,
        status="ready",
        failed_commands=failed_commands,
        error_signatures=error_signatures,
        validation_failures=validation_failures,
        memory_packet_refs=sorted(set(memory_refs)),
        git_refs=entry.git_refs,
        next_worker_recommendation=next_worker,
        evidence_json={
            "current_worker": entry.worker_id,
            "state": entry.state,
            "heartbeat_count": len(heartbeats),
        },
    )
    current = _now()

    def _do(conn):
        conn.execute(
            """
            INSERT INTO hermes_supervisor_recovery_packets (
                id, task_id, reason, status, failed_commands_json,
                error_signatures_json, validation_failures_json,
                memory_packet_refs_json, git_refs_json,
                next_worker_recommendation, evidence_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                packet.id,
                packet.task_id,
                packet.reason,
                packet.status,
                _json_dumps(packet.failed_commands),
                _json_dumps(packet.error_signatures),
                _json_dumps(packet.validation_failures),
                _json_dumps(packet.memory_packet_refs),
                _json_dumps(packet.git_refs),
                packet.next_worker_recommendation,
                _json_dumps(packet.evidence_json),
                current,
            ),
        )

    db._execute_write(_do)
    return packet


def apply_override_action(
    db: SessionDB,
    *,
    task_id: str,
    action: str,
    operator: str = "operator",
    reason: str = "",
    worker_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> OverrideAction:
    ensure_supervisor_control_schema(db)
    entry = get_task_ledger_entry(db, task_id)
    if entry is None:
        raise ValueError(f"unknown supervisor task: {task_id}")
    action = str(action).strip()
    state_map = {
        "interrupt": "interrupted",
        "request_status": entry.state,
        "pause": "paused",
        "block": "blocked",
        "reclaim": "reclaimed",
        "reassign": "reassigned",
        "escalate": "needs_operator",
        "abandon": "abandoned",
        "validation_failed": "validation_failed",
    }
    if action not in state_map:
        raise ValueError(f"unsupported override action: {action}")
    new_state = state_map[action]
    new_worker = worker_id if action == "reassign" and worker_id else entry.worker_id
    current = _now()
    oid = f"override_{uuid.uuid4().hex[:16]}"

    def _do(conn):
        conn.execute(
            """
            INSERT INTO hermes_supervisor_override_actions (
                id, task_id, action, operator, reason, previous_state,
                new_state, worker_id, metadata_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                oid,
                task_id,
                action,
                operator,
                reason,
                entry.state,
                new_state,
                new_worker,
                _json_dumps(metadata or {}),
                current,
            ),
        )
        retry_increment = 1 if action in {"reclaim", "reassign"} else 0
        conn.execute(
            """
            UPDATE hermes_supervisor_tasks
               SET state = ?,
                   worker_id = ?,
                   lease_owner = CASE WHEN ? = 'reassign' THEN ? ELSE lease_owner END,
                   lease_expires_at = CASE WHEN ? = 'reassign' THEN NULL ELSE lease_expires_at END,
                   retry_count = retry_count + ?,
                   updated_at = ?
             WHERE task_id = ?
            """,
            (new_state, new_worker, action, new_worker, action, retry_increment, current, task_id),
        )

    db._execute_write(_do)
    return OverrideAction(
        id=oid,
        task_id=task_id,
        action=action,
        operator=operator,
        reason=reason,
        previous_state=entry.state,
        new_state=new_state,
        worker_id=new_worker,
        metadata_json=metadata or {},
        created_at=current,
    )


def goal_continuation_allowed(db: SessionDB, *, task_id: str) -> Dict[str, Any]:
    entry = get_task_ledger_entry(db, task_id)
    if entry is None:
        return {"task_id": task_id, "allowed": False, "reason": "unknown_task"}
    if entry.state in GOAL_BLOCKED_STATES:
        return {
            "task_id": task_id,
            "allowed": False,
            "reason": f"supervisor_state_blocks_goal_continuation:{entry.state}",
            "state": entry.state,
        }
    return {"task_id": task_id, "allowed": True, "reason": "goal_is_metadata_only", "state": entry.state}
