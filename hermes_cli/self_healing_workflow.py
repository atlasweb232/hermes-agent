"""Self-healing workflow control-plane helpers.

This module is intentionally local and deterministic. It stores task graphs,
health/recovery actions, and restart recovery metadata in ``SessionDB.state_meta``
so foreground chat/delegation paths can continue without waiting on sidecars.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import time
import uuid
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from hermes_cli.goal_allocator import (
    WorkerAllocationPlan,
    WorkerHealth,
    allocation_status_payload,
    get_allocation_plan_by_id,
    list_allocation_plans,
    list_worker_attempts,
    list_worker_health_records,
    load_worker_health,
    save_allocation_plan,
    save_worker_health,
)
from hermes_cli.supervisor_control_plane import (
    assess_task_convergence,
    create_recovery_packet,
    get_task_ledger_entry,
    list_task_ledger_entries,
)
from hermes_state import SessionDB


GRAPH_STATUSES = {"active", "paused", "blocked", "completed", "cancelled"}
NODE_STATUSES = {"ready", "assigned", "running", "blocked", "needs_status", "review", "validated", "completed", "cancelled", "failed"}
ACTIVE_NODE_STATUSES = {"assigned", "running"}
DONE_NODE_STATUSES = {"validated", "completed"}
STATE_VERSION = "2026.05.task-graph.v1"
WORKER_PROGRESS_EVENT_TYPES = {
    "worker_started",
    "worker_heartbeat",
    "worker_stream_ref",
    "worker_progress_checkpoint",
    "worker_blocked",
    "worker_degraded",
    "worker_validation",
    "worker_final",
}
SUPERVISOR_CONTEXT_PACKET_TYPES = {
    "worker_checkpoint",
    "worker_blocked",
    "worker_validation",
    "worker_final",
    "allocation_decision",
    "recovery_packet",
}
RAW_CONTEXT_MARKERS = {
    "raw stdout",
    "raw stderr",
    "terminal transcript",
    "full terminal transcript",
    "worker watch stream",
    "watch stream",
    "raw log tail",
    "log tail",
    "unbounded tool output",
}
RAW_REF_PREFIXES = ("stdout://", "stderr://", "terminal://raw", "watch://", "logtail://")


def _now() -> float:
    return time.time()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def _json_dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True)


def _json_loads(raw: Any, default: Any) -> Any:
    if raw is None:
        return default
    if not isinstance(raw, str):
        return raw
    try:
        return json.loads(raw)
    except Exception:
        return default


def _bounded_text(value: Any, max_chars: int) -> str:
    text = str(value or "").strip()
    limit = max(1, int(max_chars))
    if len(text) <= limit:
        return text
    if limit <= 3:
        return text[:limit]
    return text[: limit - 3].rstrip() + "..."


def _clean_str_list(values: Optional[Iterable[Any]], *, field_name: str) -> List[str]:
    if values is None:
        return []
    if not isinstance(values, list):
        raise ValueError(f"{field_name} must be a list")
    return [str(value).strip() for value in values if str(value).strip()]


def _list_state_meta_prefix(db: SessionDB, prefix: str) -> List[Dict[str, str]]:
    with db._lock:
        rows = db._conn.execute(
            "SELECT key, value FROM state_meta WHERE key LIKE ? ORDER BY key",
            (f"{prefix}%",),
        ).fetchall()
    return [{"key": row["key"], "value": row["value"]} for row in rows]


def _paths_overlap(left: Iterable[str], right: Iterable[str]) -> bool:
    for raw_left in left:
        lpath = str(raw_left).strip().rstrip("/")
        if not lpath:
            continue
        for raw_right in right:
            rpath = str(raw_right).strip().rstrip("/")
            if not rpath:
                continue
            if lpath == rpath or lpath.startswith(f"{rpath}/") or rpath.startswith(f"{lpath}/"):
                return True
    return False


@dataclass
class TaskNode:
    task_id: str
    graph_id: str
    title: str
    objective: str
    parent_task_id: Optional[str] = None
    status: str = "ready"
    priority: int = 0
    dependencies: List[str] = field(default_factory=list)
    owned_paths: List[str] = field(default_factory=list)
    read_only: bool = False
    worktree_ref: Optional[str] = None
    assigned_worker: Optional[str] = None
    allocation_id: Optional[str] = None
    memory_packet_id: Optional[str] = None
    validation_required: bool = True
    validation_refs: List[str] = field(default_factory=list)
    artifact_refs: List[str] = field(default_factory=list)
    proposed_by: str = "supervisor"
    supervisor_accepted: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=_now)
    updated_at: float = field(default_factory=_now)

    def __post_init__(self) -> None:
        self.task_id = str(self.task_id).strip()
        self.graph_id = str(self.graph_id).strip()
        self.title = str(self.title).strip()
        self.objective = str(self.objective).strip()
        self.status = str(self.status).strip()
        if not self.task_id:
            raise ValueError("task_id is required")
        if not self.graph_id:
            raise ValueError("graph_id is required")
        if not self.title:
            raise ValueError("title is required")
        if not self.objective:
            raise ValueError("objective is required")
        if self.status not in NODE_STATUSES:
            raise ValueError(f"invalid task node status: {self.status}")
        self.dependencies = _clean_str_list(self.dependencies, field_name="dependencies")
        self.owned_paths = _clean_str_list(self.owned_paths, field_name="owned_paths")
        self.validation_refs = _clean_str_list(self.validation_refs, field_name="validation_refs")
        self.artifact_refs = _clean_str_list(self.artifact_refs, field_name="artifact_refs")
        if not isinstance(self.read_only, bool):
            raise ValueError("read_only must be boolean")
        if not self.read_only and not self.owned_paths:
            raise ValueError("owned_paths are required for write-capable task nodes")
        if not isinstance(self.validation_required, bool):
            raise ValueError("validation_required must be boolean")
        if not isinstance(self.supervisor_accepted, bool):
            raise ValueError("supervisor_accepted must be boolean")
        if self.proposed_by != "supervisor" and not self.supervisor_accepted:
            raise ValueError("worker-proposed subtasks require supervisor_accepted=true")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return _json_dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TaskNode":
        return cls(**dict(data))


@dataclass
class TaskGraph:
    graph_id: str
    session_id: str
    tenant_id: Optional[str]
    repo_id: Optional[str]
    root_task_id: str
    status: str = "active"
    concurrency_limit: int = 1
    source: str = "chat"
    goal_key: str = ""
    version: str = STATE_VERSION
    nodes: Dict[str, TaskNode] = field(default_factory=dict)
    spec_kit_refs: List[str] = field(default_factory=list)
    artifact_refs: List[str] = field(default_factory=list)
    validation_refs: List[str] = field(default_factory=list)
    session_summary_ref: Optional[str] = None
    created_at: float = field(default_factory=_now)
    updated_at: float = field(default_factory=_now)

    def __post_init__(self) -> None:
        self.graph_id = str(self.graph_id).strip()
        self.session_id = str(self.session_id).strip()
        self.root_task_id = str(self.root_task_id).strip()
        self.status = str(self.status).strip()
        self.source = str(self.source or "chat").strip()
        if not self.graph_id:
            raise ValueError("graph_id is required")
        if not self.session_id:
            raise ValueError("session_id is required")
        if not self.root_task_id:
            raise ValueError("root_task_id is required")
        if self.status not in GRAPH_STATUSES:
            raise ValueError(f"invalid graph status: {self.status}")
        if int(self.concurrency_limit) <= 0:
            raise ValueError("concurrency_limit must be positive")
        self.concurrency_limit = int(self.concurrency_limit)
        if not self.goal_key:
            self.goal_key = f"goal:{self.session_id}"
        self.spec_kit_refs = _clean_str_list(self.spec_kit_refs, field_name="spec_kit_refs")
        self.artifact_refs = _clean_str_list(self.artifact_refs, field_name="artifact_refs")
        self.validation_refs = _clean_str_list(self.validation_refs, field_name="validation_refs")
        converted: Dict[str, TaskNode] = {}
        for key, value in (self.nodes or {}).items():
            node = value if isinstance(value, TaskNode) else TaskNode.from_dict(value)
            converted[str(key)] = node
        self.nodes = converted

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["nodes"] = {task_id: node.to_dict() for task_id, node in sorted(self.nodes.items())}
        return payload

    def to_json(self) -> str:
        return _json_dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TaskGraph":
        return cls(**dict(data))

    @classmethod
    def from_json(cls, raw: str) -> "TaskGraph":
        return cls.from_dict(json.loads(raw))


@dataclass
class RecoveryAction:
    action_id: str
    graph_id: Optional[str]
    task_id: Optional[str]
    action: str
    reason: str
    allocation_id: Optional[str] = None
    worker_id: Optional[str] = None
    status: str = "recorded"
    retry_after_seconds: float = 0.0
    recovery_packet_id: Optional[str] = None
    artifact_refs: List[str] = field(default_factory=list)
    created_at: float = field(default_factory=_now)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RecoveryAction":
        return cls(**dict(data))


@dataclass
class SupervisorContextGateResult:
    accepted: bool
    reason: str
    context_packet: Optional[Dict[str, Any]] = None
    artifact_refs: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class WorkerProgressEvent:
    event_id: str
    event_type: str
    task_id: str
    allocation_id: str
    attempt_id: str
    worker_id: str
    repo_id: str
    branch: str
    created_at: float
    artifact_refs: List[str] = field(default_factory=list)
    store_only: bool = False
    status: str = "running"
    summary: str = ""
    evidence_refs: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.event_type not in WORKER_PROGRESS_EVENT_TYPES:
            raise ValueError(f"invalid worker progress event type: {self.event_type}")
        for field_name in ("task_id", "allocation_id", "attempt_id", "worker_id", "repo_id", "branch"):
            if not str(getattr(self, field_name, "")).strip():
                raise ValueError(f"{field_name} is required")
        self.artifact_refs = _clean_str_list(self.artifact_refs, field_name="artifact_refs")
        self.evidence_refs = _clean_str_list(self.evidence_refs, field_name="evidence_refs")
        self.summary = _bounded_text(self.summary, 1000)
        if self.event_type == "worker_stream_ref":
            self.store_only = True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WorkerProgressEvent":
        return cls(**dict(data))


class SupervisorContextGate:
    """Admit only bounded typed packets into supervisor model context."""

    def __init__(self, *, max_chars: int = 2000, max_evidence_refs: int = 12) -> None:
        self.max_chars = max(1, int(max_chars))
        self.max_evidence_refs = max(0, int(max_evidence_refs))

    def admit(self, packet: Dict[str, Any]) -> SupervisorContextGateResult:
        if not isinstance(packet, dict):
            return SupervisorContextGateResult(False, "packet_not_dict")
        if packet.get("store_only") is True or packet.get("event_type") == "worker_stream_ref":
            return SupervisorContextGateResult(False, "store_only_raw_stream")
        packet_type = str(packet.get("packet_type") or "").strip()
        if packet_type not in SUPERVISOR_CONTEXT_PACKET_TYPES:
            return SupervisorContextGateResult(False, "unsupported_packet_type")
        summary = str(packet.get("summary") or "")
        refs = _clean_str_list(packet.get("evidence_refs") or [], field_name="evidence_refs")
        artifact_refs = _clean_str_list(packet.get("artifact_refs") or [], field_name="artifact_refs")
        lowered = summary.lower()
        if any(marker in lowered for marker in RAW_CONTEXT_MARKERS):
            return SupervisorContextGateResult(False, "raw_or_unbounded_content")
        if any(ref.startswith(RAW_REF_PREFIXES) for ref in refs):
            return SupervisorContextGateResult(False, "raw_ref_requires_artifact_ref")
        if len(refs) > self.max_evidence_refs:
            return SupervisorContextGateResult(False, "too_many_evidence_refs")
        bounded_summary = _bounded_text(summary, self.max_chars)
        context_packet = {
            "packet_type": packet_type,
            "task_id": packet.get("task_id"),
            "allocation_id": packet.get("allocation_id"),
            "attempt_id": packet.get("attempt_id"),
            "worker_id": packet.get("worker_id"),
            "repo_id": packet.get("repo_id"),
            "branch": packet.get("branch"),
            "summary": bounded_summary,
            "status": packet.get("status") or "unknown",
            "decision_needed": packet.get("decision_needed"),
            "evidence_refs": refs,
            "artifact_refs": artifact_refs,
            "max_chars": self.max_chars,
            "max_evidence_refs": self.max_evidence_refs,
            "created_at": packet.get("created_at") or _now(),
        }
        return SupervisorContextGateResult(True, "accepted", context_packet, artifact_refs)


def _graph_key(graph_id: str) -> str:
    return f"task_graph:{graph_id}"


def _recovery_action_key(identity: str) -> str:
    return f"runtime_recovery_action:{identity}"


def _worker_progress_event_key(created_at: float, event_id: str) -> str:
    return f"worker_progress_event:{created_at:020.6f}:{event_id}"


def _sidecar_checkpoint_key(run_id: str) -> str:
    return f"worker_progress_checkpoint:{run_id}"


def emit_worker_progress_event(
    db: SessionDB,
    *,
    event_type: str,
    task_id: str,
    allocation_id: str,
    attempt_id: str,
    worker_id: str,
    repo_id: str,
    branch: str,
    created_at: Optional[float] = None,
    artifact_refs: Optional[List[str]] = None,
    store_only: bool = False,
    status: str = "running",
    summary: str = "",
    evidence_refs: Optional[List[str]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    event = WorkerProgressEvent(
        event_id=_new_id("evt"),
        event_type=event_type,
        task_id=task_id,
        allocation_id=allocation_id,
        attempt_id=attempt_id,
        worker_id=worker_id,
        repo_id=repo_id,
        branch=branch,
        created_at=_now() if created_at is None else float(created_at),
        artifact_refs=artifact_refs or [],
        store_only=bool(store_only),
        status=status,
        summary=summary,
        evidence_refs=evidence_refs or [],
        metadata=metadata or {},
    )
    payload = event.to_dict()
    db.set_meta(_worker_progress_event_key(event.created_at, event.event_id), _json_dumps(payload))
    return payload


def list_worker_progress_events(
    db: SessionDB,
    *,
    task_id: Optional[str] = None,
    allocation_id: Optional[str] = None,
    worker_id: Optional[str] = None,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    for row in _list_state_meta_prefix(db, "worker_progress_event:"):
        payload = _json_loads(row["value"], {})
        if not isinstance(payload, dict):
            continue
        if task_id and payload.get("task_id") != task_id:
            continue
        if allocation_id and payload.get("allocation_id") != allocation_id:
            continue
        if worker_id and payload.get("worker_id") != worker_id:
            continue
        events.append(payload)
    events.sort(key=lambda item: (float(item.get("created_at") or 0), str(item.get("event_id") or "")))
    return events[-max(1, int(limit)) :]


def run_worker_with_progress_events(
    db: SessionDB,
    *,
    task_id: str,
    allocation_id: str,
    attempt_id: str,
    worker_id: str,
    repo_id: str,
    branch: str,
    worker_run: Callable[[], Any],
    now: Optional[float] = None,
) -> Dict[str, Any]:
    current = _now() if now is None else float(now)
    common = {
        "task_id": task_id,
        "allocation_id": allocation_id,
        "attempt_id": attempt_id,
        "worker_id": worker_id,
        "repo_id": repo_id,
        "branch": branch,
    }

    def emit(event_type: str, offset: float, **kwargs: Any) -> Dict[str, Any]:
        return emit_worker_progress_event(db, event_type=event_type, created_at=current + offset, **common, **kwargs)

    emit("worker_started", 0.0, status="started", summary="worker attempt started")
    emit("worker_heartbeat", 0.001, status="running", summary="worker heartbeat recorded")
    final_status = "completed"
    summary = ""
    artifact_refs: List[str] = []
    evidence_refs: List[str] = []
    validation_refs: List[str] = []
    degraded_reason = ""
    try:
        raw_result = worker_run()
        result = raw_result if isinstance(raw_result, dict) else {"status": "completed", "summary": str(raw_result or "")}
        final_status = str(result.get("status") or "completed")
        summary = str(result.get("summary") or result.get("output") or "")
        artifact_refs = _clean_str_list(result.get("artifact_refs") or [], field_name="artifact_refs")
        evidence_refs = _clean_str_list(result.get("evidence_refs") or [], field_name="evidence_refs")
        validation_refs = _clean_str_list(result.get("validation_refs") or [], field_name="validation_refs")
        for key, stream_name in (("stdout_ref", "stdout"), ("stderr_ref", "stderr"), ("stream_ref", "stream")):
            if result.get(key):
                stream_ref = str(result[key])
                emit(
                    "worker_stream_ref",
                    0.002,
                    status="store_only",
                    summary=f"{stream_name} stored by reference",
                    artifact_refs=[stream_ref],
                    store_only=True,
                    metadata={"stream": stream_name},
                )
        if not summary.strip():
            final_status = "degraded"
            degraded_reason = "empty_output"
    except TimeoutError as exc:
        final_status = "degraded"
        degraded_reason = "timeout"
        summary = str(exc) or "worker timed out"
    except Exception as exc:
        final_status = "degraded"
        message = str(exc) or exc.__class__.__name__
        degraded_reason = "model_unavailable" if "unavailable" in message.lower() else "worker_error"
        summary = message

    if final_status == "degraded":
        emit(
            "worker_degraded",
            0.003,
            status="degraded",
            summary=degraded_reason or summary,
            artifact_refs=artifact_refs,
            evidence_refs=evidence_refs,
            metadata={"reason": degraded_reason},
        )
    else:
        emit(
            "worker_progress_checkpoint",
            0.003,
            status=final_status,
            summary=summary,
            artifact_refs=artifact_refs,
            evidence_refs=evidence_refs,
        )
        if final_status == "blocked":
            emit("worker_blocked", 0.004, status="blocked", summary=summary, artifact_refs=artifact_refs, evidence_refs=evidence_refs)
        if validation_refs:
            emit(
                "worker_validation",
                0.005,
                status="validated",
                summary="worker validation refs recorded",
                artifact_refs=artifact_refs,
                evidence_refs=validation_refs,
            )
    final_event = emit(
        "worker_final",
        0.006,
        status=final_status,
        summary=summary or degraded_reason or final_status,
        artifact_refs=artifact_refs,
        evidence_refs=evidence_refs + validation_refs,
        metadata={"degraded_reason": degraded_reason} if degraded_reason else {},
    )
    return {"status": final_status, "summary": summary, "final_event": final_event}


def create_task_graph(db: SessionDB, graph: TaskGraph, nodes: Optional[List[TaskNode]] = None) -> TaskGraph:
    current = _now()
    graph.updated_at = current
    for node in nodes or []:
        if node.graph_id != graph.graph_id:
            raise ValueError("node graph_id does not match graph")
        graph.nodes[node.task_id] = node
    for node in graph.nodes.values():
        for dep in node.dependencies:
            if dep not in graph.nodes:
                raise ValueError(f"unknown dependency: {dep}")
        if node.status in ACTIVE_NODE_STATUSES:
            _raise_on_owned_path_conflict(graph, node)
    db.set_meta(_graph_key(graph.graph_id), graph.to_json())
    return graph


def get_task_graph(db: SessionDB, graph_id: str) -> TaskGraph:
    raw = db.get_meta(_graph_key(graph_id))
    if not raw:
        raise ValueError(f"unknown task graph: {graph_id}")
    return TaskGraph.from_json(raw)


def list_task_graphs(db: SessionDB, *, status: Optional[str] = None, limit: int = 100) -> List[TaskGraph]:
    graphs: List[TaskGraph] = []
    for row in _list_state_meta_prefix(db, "task_graph:"):
        try:
            graph = TaskGraph.from_json(row["value"])
        except Exception:
            continue
        if status and graph.status != status:
            continue
        graphs.append(graph)
    return sorted(graphs, key=lambda item: item.updated_at, reverse=True)[: max(1, int(limit))]


def _raise_on_owned_path_conflict(graph: TaskGraph, node: TaskNode) -> None:
    if node.read_only:
        return
    for other in graph.nodes.values():
        if other.task_id == node.task_id or other.read_only:
            continue
        if other.status in ACTIVE_NODE_STATUSES and _paths_overlap(node.owned_paths, other.owned_paths):
            raise ValueError(f"owned-path conflict between {node.task_id} and {other.task_id}")


def _dependencies_ready(graph: TaskGraph, node: TaskNode) -> bool:
    return all(graph.nodes.get(dep) and graph.nodes[dep].status in DONE_NODE_STATUSES for dep in node.dependencies)


def update_task_node(db: SessionDB, graph_id: str, task_id: str, **updates: Any) -> TaskNode:
    graph = get_task_graph(db, graph_id)
    if task_id not in graph.nodes:
        raise ValueError(f"unknown task node: {task_id}")
    data = graph.nodes[task_id].to_dict()
    data.update(updates)
    data["updated_at"] = _now()
    node = TaskNode.from_dict(data)
    if node.status == "completed" and node.validation_required and not node.validation_refs:
        raise ValueError("validation_refs are required before completing this node")
    if node.status in ACTIVE_NODE_STATUSES:
        graph.nodes[task_id] = node
        _raise_on_owned_path_conflict(graph, node)
    graph.nodes[task_id] = node
    graph.updated_at = _now()
    db.set_meta(_graph_key(graph_id), graph.to_json())
    return node


def complete_task_graph(db: SessionDB, graph_id: str, *, session_summary_ref: str) -> TaskGraph:
    graph = get_task_graph(db, graph_id)
    incomplete = [
        node.task_id
        for node in graph.nodes.values()
        if node.status not in {"completed", "cancelled"} and not (node.status == "validated" and node.validation_refs)
    ]
    if incomplete:
        raise ValueError(f"task graph is not completeable; incomplete nodes: {', '.join(sorted(incomplete))}")
    graph.status = "completed"
    graph.session_summary_ref = session_summary_ref
    graph.updated_at = _now()
    db.set_meta(_graph_key(graph_id), graph.to_json())
    return graph


def _active_node_count(graph: TaskGraph) -> int:
    return sum(1 for node in graph.nodes.values() if node.status in ACTIVE_NODE_STATUSES)


def _active_owned_paths(graph: TaskGraph) -> List[str]:
    paths: List[str] = []
    for node in graph.nodes.values():
        if node.status in ACTIVE_NODE_STATUSES and not node.read_only:
            paths.extend(node.owned_paths)
    return paths


def dispatch_ready_nodes(
    db: SessionDB,
    graph_id: str,
    *,
    candidate_workers: Optional[List[str]] = None,
    now: Optional[float] = None,
) -> Dict[str, Any]:
    graph = get_task_graph(db, graph_id)
    current = _now() if now is None else float(now)
    workers = candidate_workers or ["codex", "claude-code", "deepseek"]
    dispatched: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    active_count = _active_node_count(graph)
    active_paths = _active_owned_paths(graph)
    health = {record.worker_id: record for record in list_worker_health_records(db)}

    for node in sorted(graph.nodes.values(), key=lambda item: (item.priority, item.task_id)):
        if node.status != "ready":
            continue
        if active_count >= graph.concurrency_limit:
            skipped.append({"task_id": node.task_id, "reason": "concurrency_limit_reached"})
            continue
        if not _dependencies_ready(graph, node):
            skipped.append({"task_id": node.task_id, "reason": "dependencies_not_ready"})
            continue
        if not node.read_only and _paths_overlap(node.owned_paths, active_paths):
            skipped.append({"task_id": node.task_id, "reason": "owned_path_conflict"})
            continue

        plan = WorkerAllocationPlan(
            task_id=node.task_id,
            session_id=graph.session_id,
            objective=node.objective,
            candidate_workers=workers,
            primary_worker=workers[0],
            fallback_order=workers[1:],
            tenant_id=graph.tenant_id,
            repo_id=graph.repo_id,
            memory_packet_id=node.memory_packet_id,
            validation_required=node.validation_required,
        )
        save_allocation_plan(db, plan)
        packet = allocation_status_payload(db, plan, now=current)
        decision = packet["decision"]
        if decision.get("action") != "dispatch":
            skipped.append({"task_id": node.task_id, "reason": f"allocator_{decision.get('action')}", "allocation": packet})
            continue
        node.status = "assigned"
        node.assigned_worker = decision.get("worker_id")
        node.allocation_id = plan.allocation_id
        node.updated_at = current
        graph.nodes[node.task_id] = node
        active_count += 1
        if not node.read_only:
            active_paths.extend(node.owned_paths)
        dispatched.append(
            {
                "packet_type": "allocation_decision",
                "graph_id": graph.graph_id,
                "task_id": node.task_id,
                "source": graph.source,
                "allocation_id": plan.allocation_id,
                "worker_id": node.assigned_worker,
                "owned_paths": node.owned_paths,
                "read_only": node.read_only,
                "allocation": packet,
                "max_chars": 2000,
                "created_at": current,
            }
        )

    graph.updated_at = current
    db.set_meta(_graph_key(graph.graph_id), graph.to_json())
    return {"status": "completed", "graph_id": graph.graph_id, "source": graph.source, "dispatched": dispatched, "skipped": skipped}


def _record_recovery_action(db: SessionDB, identity: str, action: RecoveryAction) -> bool:
    key = _recovery_action_key(identity)
    if db.get_meta(key):
        return False
    db.set_meta(key, _json_dumps(action.to_dict()))
    try:
        from hermes_cli.learning_bus import publish_learning_event_safely

        publish_learning_event_safely(
            db,
            topic="runtime.recovery_action",
            tenant_id=None,
            repo_id=None,
            task_id=action.task_id,
            payload={"source": "self_healing_workflow", **action.to_dict()},
            event_key=identity,
        )
    except Exception:
        pass
    return True


def list_recovery_actions(db: SessionDB, *, limit: int = 100) -> List[RecoveryAction]:
    actions: List[RecoveryAction] = []
    for row in _list_state_meta_prefix(db, "runtime_recovery_action:"):
        try:
            actions.append(RecoveryAction.from_dict(json.loads(row["value"])))
        except Exception:
            continue
    return sorted(actions, key=lambda item: item.created_at, reverse=True)[: max(1, int(limit))]


def _pause_plan(db: SessionDB, allocation_id: str, retry_after_seconds: float) -> Optional[WorkerAllocationPlan]:
    plan = get_allocation_plan_by_id(db, allocation_id)
    if plan is None:
        return None
    plan.status = "paused"
    plan.retry_after_seconds = retry_after_seconds
    save_allocation_plan(db, plan)
    return plan


def _set_node_status_if_needed(db: SessionDB, graph: TaskGraph, node: TaskNode, status: str) -> None:
    if node.status == status:
        return
    try:
        update_task_node(db, graph.graph_id, node.task_id, status=status)
    except ValueError:
        pass


def _detect_repeated_attempts(db: SessionDB, allocation_id: str) -> Tuple[bool, List[str]]:
    attempts = list_worker_attempts(db, allocation_id)
    bad = [attempt for attempt in attempts if attempt.status in {"timed_out", "empty_output"}]
    if len(bad) < 2:
        return False, []
    signatures = [attempt.error_signature or attempt.status for attempt in bad[-3:]]
    return True, signatures


def run_health_check_once(
    db: SessionDB,
    *,
    now: Optional[float] = None,
    heartbeat_timeout_seconds: float = 600.0,
    scan_limit: int = 100,
    max_actions: int = 20,
    foreground_blocking_callback: Optional[Callable[[], Any]] = None,
) -> Dict[str, Any]:
    current = _now() if now is None else float(now)
    run = {
        "run_id": _new_id("health"),
        "status": "completed",
        "started_at": current,
        "finished_at": current,
        "tasks_scanned": 0,
        "allocations_scanned": 0,
        "workers_scanned": 0,
        "stale_leases": 0,
        "no_progress": 0,
        "cooldowns_set": 0,
        "recovery_candidates": 0,
        "errors": [],
        "actions": [],
    }
    actions_left = max(0, int(max_actions))
    graphs = list_task_graphs(db, status="active", limit=scan_limit)
    run["workers_scanned"] = len(list_worker_health_records(db))

    for graph in graphs:
        if actions_left <= 0:
            break
        for node in sorted(graph.nodes.values(), key=lambda item: item.task_id):
            if actions_left <= 0:
                break
            if node.status not in ACTIVE_NODE_STATUSES:
                continue
            run["tasks_scanned"] += 1
            reasons: List[str] = []
            try:
                entry = get_task_ledger_entry(db, node.task_id)
                if entry is not None:
                    assessment = assess_task_convergence(
                        db,
                        task_id=node.task_id,
                        config={"supervisor": {"control_plane": {"heartbeat_timeout_seconds": heartbeat_timeout_seconds}}},
                        now=current,
                    )
                    reasons.extend(assessment.reasons)
            except Exception as exc:
                run["errors"].append(str(exc))
            if not node.allocation_id:
                reasons.append("missing_allocation")
            elif get_allocation_plan_by_id(db, node.allocation_id) is not None:
                run["allocations_scanned"] += 1
                repeated, signatures = _detect_repeated_attempts(db, node.allocation_id)
                if repeated:
                    reasons.append("repeated_timeout_empty_output")
                    if node.assigned_worker:
                        health = load_worker_health(db, node.assigned_worker) or WorkerHealth(worker_id=node.assigned_worker)
                        health.cooldown_until = max(health.cooldown_until, current + 120)
                        health.last_error_signature = ",".join(signatures)[-200:]
                        save_worker_health(db, health)
                        identity = f"{graph.graph_id}:{node.task_id}:set_worker_cooldown"
                        action = RecoveryAction(
                            action_id=_new_id("recovery_action"),
                            graph_id=graph.graph_id,
                            task_id=node.task_id,
                            action="set_worker_cooldown",
                            reason="repeated_timeout_empty_output",
                            allocation_id=node.allocation_id,
                            worker_id=node.assigned_worker,
                            retry_after_seconds=120,
                            created_at=current,
                        )
                        if _record_recovery_action(db, identity, action):
                            run["actions"].append(action.to_dict())
                            run["cooldowns_set"] += 1
                            actions_left -= 1
                if any(reason in reasons for reason in {"repeated_timeout_empty_output", "quota_exhausted", "auth_failed", "network_degraded"}):
                    _pause_plan(db, node.allocation_id, 120)
                    identity = f"{graph.graph_id}:{node.task_id}:pause_allocation"
                    action = RecoveryAction(
                        action_id=_new_id("recovery_action"),
                        graph_id=graph.graph_id,
                        task_id=node.task_id,
                        action="pause_allocation",
                        reason="degraded_worker_or_platform",
                        allocation_id=node.allocation_id,
                        worker_id=node.assigned_worker,
                        retry_after_seconds=120,
                        created_at=current,
                    )
                    if actions_left > 0 and _record_recovery_action(db, identity, action):
                        run["actions"].append(action.to_dict())
                        actions_left -= 1

            if "lease_expired" in reasons:
                run["stale_leases"] += 1
            if "missing_heartbeat" in reasons or "heartbeat_stale" in reasons:
                reasons.append("missing_or_stale_heartbeat")
            if "no_progress_loop" in reasons:
                run["no_progress"] += 1
            if reasons:
                _set_node_status_if_needed(db, graph, node, "needs_status" if "missing_or_stale_heartbeat" in reasons else "blocked")
                for action_name in ("request_status", "request_reassignment", "mark_node_blocked", "emit_recovery_packet"):
                    if actions_left <= 0:
                        break
                    identity = f"{graph.graph_id}:{node.task_id}:{action_name}:{','.join(sorted(set(reasons)))}"
                    recovery_packet_id = None
                    if action_name == "emit_recovery_packet" and get_task_ledger_entry(db, node.task_id):
                        try:
                            recovery_packet_id = create_recovery_packet(db, task_id=node.task_id, reason=",".join(sorted(set(reasons)))).id
                        except Exception:
                            recovery_packet_id = None
                    action = RecoveryAction(
                        action_id=_new_id("recovery_action"),
                        graph_id=graph.graph_id,
                        task_id=node.task_id,
                        action=action_name,
                        reason=",".join(sorted(set(reasons))),
                        allocation_id=node.allocation_id,
                        worker_id=node.assigned_worker,
                        recovery_packet_id=recovery_packet_id,
                        artifact_refs=list(node.artifact_refs),
                        created_at=current,
                    )
                    if _record_recovery_action(db, identity, action):
                        run["actions"].append(action.to_dict())
                        run["recovery_candidates"] += 1
                        actions_left -= 1
    run["finished_at"] = current
    db.set_meta("runtime_health_last_run", _json_dumps(run))
    return run


def _deterministic_progress_summary(events: List[Dict[str, Any]], max_chars: int) -> str:
    if not events:
        return "No worker progress events recorded."
    counts: Dict[str, int] = {}
    refs: List[str] = []
    statuses: List[str] = []
    for event in events:
        event_type = str(event.get("event_type") or "unknown")
        counts[event_type] = counts.get(event_type, 0) + 1
        status = str(event.get("status") or "").strip()
        if status:
            statuses.append(status)
        for ref in event.get("artifact_refs") or []:
            if ref not in refs:
                refs.append(str(ref))
    pieces = [f"{sum(counts.values())} progress events"]
    pieces.extend(f"{key}={counts[key]}" for key in sorted(counts))
    if statuses:
        pieces.append(f"latest_status={statuses[-1]}")
    if refs:
        pieces.append(f"refs={', '.join(refs[:3])}")
    return _bounded_text("; ".join(pieces), max_chars)


def run_progress_summarizer_sidecar(
    db: SessionDB,
    *,
    task_id: str,
    allocation_id: Optional[str] = None,
    low_cost_summarizer: Optional[Callable[[List[Dict[str, Any]], Dict[str, Any]], str]] = None,
    foreground_blocking_callback: Optional[Callable[[], Any]] = None,
    max_chars: int = 2000,
    max_events: int = 50,
    timeout_seconds: float = 2.0,
    budget_tokens: int = 512,
    now: Optional[float] = None,
) -> Dict[str, Any]:
    del foreground_blocking_callback  # Sidecar work never calls foreground callbacks.
    current = _now() if now is None else float(now)
    events = list_worker_progress_events(db, task_id=task_id, allocation_id=allocation_id, limit=max_events)
    budget = {
        "tier": "low_cost_reasoning",
        "max_chars": max(1, int(max_chars)),
        "max_events": max(1, int(max_events)),
        "timeout_seconds": float(timeout_seconds),
        "budget_tokens": int(budget_tokens),
    }
    status = "completed"
    fallback = None
    try:
        if low_cost_summarizer is None:
            raise RuntimeError("low-cost summarizer unavailable")
        started = _now()
        summary = _bounded_text(low_cost_summarizer(events, budget), budget["max_chars"])
        if _now() - started > float(timeout_seconds):
            raise TimeoutError("low-cost summarizer exceeded timeout")
        if not summary:
            raise RuntimeError("low-cost summarizer returned empty output")
    except Exception:
        status = "degraded"
        fallback = "deterministic"
        summary = _deterministic_progress_summary(events, budget["max_chars"])
    artifact_refs: List[str] = []
    evidence_refs: List[str] = []
    for event in events:
        if event.get("event_type") == "worker_stream_ref":
            continue
        for ref in event.get("artifact_refs") or []:
            if ref not in artifact_refs:
                artifact_refs.append(str(ref))
        evidence_refs.append(f"event://{event.get('event_id')}")
    packet = {
        "packet_type": "worker_checkpoint",
        "task_id": task_id,
        "allocation_id": allocation_id,
        "summary": summary,
        "status": "in_progress",
        "decision_needed": None,
        "evidence_refs": evidence_refs[:12],
        "artifact_refs": artifact_refs[:12],
        "created_at": current,
        "metadata": {
            "tier": "low_cost_reasoning",
            "timeout_seconds": float(timeout_seconds),
            "budget_tokens": int(budget_tokens),
            "fallback": fallback,
        },
    }
    gate_result = SupervisorContextGate(max_chars=budget["max_chars"], max_evidence_refs=12).admit(packet)
    run = {
        "run_id": _new_id("progress_sidecar"),
        "status": status,
        "fallback": fallback,
        "tier": "low_cost_reasoning",
        "timeout_seconds": float(timeout_seconds),
        "budget_tokens": int(budget_tokens),
        "events_scanned": len(events),
        "packet": packet,
        "supervisor_context": gate_result.to_dict(),
        "authorities": {
            "complete_tasks": False,
            "approve_memory": False,
            "enforce_policy": False,
            "mutate_routing": False,
            "change_config": False,
        },
        "created_at": current,
    }
    db.set_meta(_sidecar_checkpoint_key(run["run_id"]), _json_dumps(run))
    return run


def project_worker_progress_for_delivery(
    db: SessionDB,
    *,
    task_id: Optional[str] = None,
    allocation_id: Optional[str] = None,
    worker_id: Optional[str] = None,
    channel: str = "api",
    limit: int = 100,
) -> Dict[str, Any]:
    events = list_worker_progress_events(db, task_id=task_id, allocation_id=allocation_id, worker_id=worker_id, limit=limit)
    gate = SupervisorContextGate()
    context_packets: List[Dict[str, Any]] = []
    for event in events:
        event_type = event.get("event_type")
        if event_type == "worker_progress_checkpoint":
            packet_type = "worker_checkpoint"
        elif event_type in {"worker_blocked", "worker_validation", "worker_final"}:
            packet_type = str(event_type).replace("worker_", "worker_", 1)
        else:
            continue
        candidate = {
            "packet_type": packet_type,
            "task_id": event.get("task_id"),
            "allocation_id": event.get("allocation_id"),
            "attempt_id": event.get("attempt_id"),
            "worker_id": event.get("worker_id"),
            "repo_id": event.get("repo_id"),
            "branch": event.get("branch"),
            "summary": event.get("summary"),
            "status": event.get("status"),
            "evidence_refs": [f"event://{event.get('event_id')}"] + list(event.get("evidence_refs") or []),
            "artifact_refs": event.get("artifact_refs") or [],
            "created_at": event.get("created_at"),
        }
        result = gate.admit(candidate)
        if result.accepted and result.context_packet:
            context_packets.append(result.context_packet)
    return {
        "source": "worker_progress_events",
        "channel": channel,
        "task_id": task_id,
        "allocation_id": allocation_id,
        "worker_id": worker_id,
        "events": events,
        "supervisor_context_appended": False,
        "supervisor_context_packets": context_packets,
    }


def record_runtime_lease(db: SessionDB, *, lease_id: str, owner: str, expires_at: float, status: str = "active") -> Dict[str, Any]:
    payload = {"lease_id": lease_id, "owner": owner, "expires_at": float(expires_at), "status": status, "updated_at": _now()}
    db.set_meta(f"runtime_lease:{lease_id}", _json_dumps(payload))
    return payload


def _list_runtime_leases(db: SessionDB) -> List[Dict[str, Any]]:
    leases: List[Dict[str, Any]] = []
    for row in _list_state_meta_prefix(db, "runtime_lease:"):
        payload = _json_loads(row["value"], {})
        if isinstance(payload, dict):
            leases.append(payload)
    return leases


def _list_active_goals(db: SessionDB) -> List[Dict[str, Any]]:
    goals: List[Dict[str, Any]] = []
    for row in _list_state_meta_prefix(db, "goal:"):
        payload = _json_loads(row["value"], {})
        if isinstance(payload, dict) and payload.get("status") in {"active", "running"}:
            session_id = row["key"].split(":", 1)[1]
            goals.append({"session_id": session_id, "key": row["key"], "goal": payload.get("goal"), "status": payload.get("status")})
    return goals


def _approved_hot_memory(db: SessionDB) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    for row in _list_state_meta_prefix(db, "runtime_hot_memory:"):
        payload = _json_loads(row["value"], {})
        if isinstance(payload, dict) and payload.get("status") == "approved":
            records.append({"key": row["key"], "memory_packet_id": payload.get("memory_packet_id")})
    return records


def _approved_lessons(db: SessionDB) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    for row in _list_state_meta_prefix(db, "runtime_approved_lesson:"):
        payload = _json_loads(row["value"], {})
        if isinstance(payload, dict) and payload.get("status") == "approved":
            records.append({"key": row["key"], "lesson_id": payload.get("lesson_id")})
    return records


def recovery_status(db: SessionDB, *, now: Optional[float] = None) -> Dict[str, Any]:
    current = _now() if now is None else float(now)
    active_graphs = [graph for graph in list_task_graphs(db) if graph.status == "active"]
    active_allocations = [plan for plan in list_allocation_plans(db) if plan.status == "active"]
    workers = list_worker_health_records(db)
    stale_leases = [lease for lease in _list_runtime_leases(db) if lease.get("status") == "active" and float(lease.get("expires_at") or 0) <= current]
    return {
        "status": "completed",
        "active_goals": _list_active_goals(db),
        "task_ledger": [entry.to_dict() for entry in list_task_ledger_entries(db, limit=100)],
        "active_task_graphs": [
            {
                "graph_id": graph.graph_id,
                "session_id": graph.session_id,
                "source": graph.source,
                "status": graph.status,
                "active_nodes": [node.task_id for node in graph.nodes.values() if node.status in ACTIVE_NODE_STATUSES],
            }
            for graph in active_graphs
        ],
        "active_allocations": [plan.to_dict() for plan in active_allocations],
        "unhealthy_workers": [worker.to_dict() for worker in workers if not worker.is_available(current)],
        "paused_tasks": [
            {"graph_id": graph.graph_id, "task_id": node.task_id, "status": node.status}
            for graph in active_graphs
            for node in graph.nodes.values()
            if node.status in {"blocked", "needs_status"}
        ],
        "safe_to_resume_tasks": [],
        "blocked_tasks": [],
        "retry_after_timestamps": {
            worker.worker_id: worker.unavailable_until()
            for worker in workers
            if not worker.is_available(current)
        },
        "stale_sidecar_leases": stale_leases,
    }


def run_restart_recovery(
    db: SessionDB,
    *,
    now: Optional[float] = None,
    expensive_sidecar: Optional[Callable[[], Any]] = None,
    allow_expensive_sidecars: bool = False,
) -> Dict[str, Any]:
    current = _now() if now is None else float(now)
    if allow_expensive_sidecars and expensive_sidecar is not None:
        expensive_sidecar()
    status = recovery_status(db, now=current)
    decisions: List[Dict[str, Any]] = []
    healthy_workers = {worker.worker_id: worker for worker in list_worker_health_records(db) if worker.is_available(current)}
    unhealthy_ids = {worker.worker_id for worker in list_worker_health_records(db) if not worker.is_available(current)}
    allocations_by_id = {plan.allocation_id: plan for plan in list_allocation_plans(db)}

    for graph in list_task_graphs(db, status="active"):
        for node in sorted(graph.nodes.values(), key=lambda item: item.task_id):
            if node.status not in {"ready", "assigned", "running", "blocked", "needs_status"}:
                continue
            plan = allocations_by_id.get(node.allocation_id or "")
            decision = "pause"
            safe = False
            reason = "not ready"
            blocked_by: List[str] = []
            if node.status == "running" and plan is not None and not list_worker_attempts(db, plan.allocation_id):
                decision = "request_status"
                reason = "unknown in-flight attempt"
                blocked_by.append("unknown_in_flight_attempt")
                if node.assigned_worker in unhealthy_ids:
                    blocked_by.append(f"worker:{node.assigned_worker}")
            elif node.assigned_worker in unhealthy_ids:
                decision = "pause"
                reason = "worker cooling down or unhealthy"
                blocked_by.append(f"worker:{node.assigned_worker}")
            elif node.status in {"ready", "assigned"} and plan is not None:
                decision = "resume"
                safe = True
                reason = "worker healthy and dependencies satisfied"
                if node.assigned_worker and node.assigned_worker not in healthy_workers and healthy_workers:
                    reason = "healthy fallback available"
            else:
                decision = "block" if node.status in {"blocked", "needs_status"} else "pause"
                reason = f"node status is {node.status}"
            decisions.append(
                {
                    "decision_id": _new_id("recovery"),
                    "session_id": graph.session_id,
                    "task_id": node.task_id,
                    "allocation_id": node.allocation_id,
                    "decision": decision,
                    "reason": reason,
                    "safe_to_dispatch": safe,
                    "blocked_by": blocked_by,
                    "retry_after_seconds": 0,
                    "memory_packet_id": node.memory_packet_id,
                    "created_at": current,
                }
            )

    for lease in status["stale_sidecar_leases"]:
        if lease.get("status") == "active":
            lease["status"] = "reclaimed"
            db.set_meta(f"runtime_lease:{lease.get('lease_id')}", _json_dumps(lease))

    status["decisions"] = decisions
    status["hot_memory"] = _approved_hot_memory(db)
    status["approved_lessons"] = _approved_lessons(db)
    status["safe_to_resume_tasks"] = [item for item in decisions if item["safe_to_dispatch"]]
    status["blocked_tasks"] = [item for item in decisions if item["decision"] in {"block", "request_status", "pause"}]
    db.set_meta("runtime_recovery_last_run", _json_dumps(status))
    return status
