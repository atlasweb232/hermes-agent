"""Tenant-scoped observability helpers for learning jobs and task evidence."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import re
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from hermes_cli.learning_jobs import (
    LearningJobRecord,
    get_learning_job,
    list_learning_jobs,
)
from hermes_state import SessionDB


SECRET_PATTERNS = [
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\b\d{8,12}:[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"(?i)(api[_-]?key|secret|token|password)\s*[:=]\s*\S+"),
]

SENSITIVE_KEY_PARTS = (
    "api_key",
    "apikey",
    "secret",
    "token",
    "password",
    "credential",
    "authorization",
    "cookie",
)
RAW_TEXT_KEY_PARTS = (
    "raw_transcript",
    "transcript",
    "raw_log",
    "raw_logs",
    "provider_log",
    "provider_logs",
    "messages",
    "conversation",
    "worker_stream",
)


def _now() -> float:
    return time.time()


def _safe_text(value: Any, *, max_chars: int = 500) -> str:
    text = str(value or "")
    for pattern in SECRET_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_chars]


def _secret_safe(value: Any) -> bool:
    text = json.dumps(value, sort_keys=True, ensure_ascii=False) if not isinstance(value, str) else value
    return not any(pattern.search(text) for pattern in SECRET_PATTERNS)


@dataclass
class ObservabilityFilters:
    tenant_id: Optional[str] = None
    repo_id: Optional[str] = None
    task_id: Optional[str] = None
    worker_id: Optional[str] = None
    worker_status: Optional[str] = None
    status: Optional[str] = None
    completion_status: Optional[str] = None
    item_type: Optional[str] = None
    job_type: Optional[str] = None
    candidate_kind: Optional[str] = None
    blocker: Optional[str] = None
    date_from: Optional[float] = None
    date_to: Optional[float] = None
    limit: int = 100

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ObservabilityLineItem:
    id: str
    tenant_id: Optional[str]
    repo_id: Optional[str]
    item_type: str
    item_id: str
    task_id: Optional[str]
    worker_id: Optional[str]
    title: str
    status: str
    blocker: Optional[str]
    completion_state: str
    validation_state: str
    started_at: Optional[float]
    updated_at: Optional[float]
    summary_json: Dict[str, Any] = field(default_factory=dict)
    worker_kind: Optional[str] = None
    worker_status: Optional[str] = None
    blocker_status: str = "none"
    completion_status: Optional[str] = None
    model: Optional[str] = None
    provider: Optional[str] = None
    route: Optional[str] = None
    speckit_refs: List[str] = field(default_factory=list)
    architecture_refs: List[str] = field(default_factory=list)
    task_list_refs: List[str] = field(default_factory=list)
    memory_refs: List[Dict[str, Any]] = field(default_factory=list)
    cost_summary: Dict[str, Any] = field(default_factory=dict)
    latency_summary: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ObservabilityEvidenceBundle:
    id: str
    tenant_id: Optional[str]
    repo_id: Optional[str]
    task_id: Optional[str]
    line_item_id: str
    task_description: str
    supervisor_packet_ref: Optional[str] = None
    initial_assignment: Dict[str, Any] = field(default_factory=dict)
    agent_refs: List[Dict[str, Any]] = field(default_factory=list)
    speckit_refs: List[str] = field(default_factory=list)
    branch_refs: List[str] = field(default_factory=list)
    validation_refs: List[Dict[str, Any]] = field(default_factory=list)
    memory_refs: List[Dict[str, Any]] = field(default_factory=list)
    event_refs: List[Dict[str, Any]] = field(default_factory=list)
    artifact_refs: List[Dict[str, Any]] = field(default_factory=list)
    raw_transcript_included: bool = False
    secret_safe: bool = True
    created_at: float = field(default_factory=_now)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ScopedAnalysisResult:
    id: str
    tenant_id: Optional[str]
    repo_id: Optional[str]
    task_id: Optional[str]
    line_item_id: str
    question: str
    evidence_bundle_id: str
    repo_query_allowed: bool
    repo_query_mode: str
    answer: str
    citations: List[str]
    llm_calls: List[Dict[str, Any]] = field(default_factory=list)
    mutation_allowed: bool = False
    created_at: float = field(default_factory=_now)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class RuntimeObservabilityDetail:
    line_item: Dict[str, Any]
    evidence_bundle: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        data = {"line_item": self.line_item, "evidence_bundle": self.evidence_bundle}
        data.update(self.evidence_bundle)
        return data


def _job_to_line_item(job: LearningJobRecord) -> ObservabilityLineItem:
    metrics = job.metrics_json if isinstance(job.metrics_json, dict) else {}
    error = job.error_json if isinstance(job.error_json, dict) else {}
    blocker = error.get("message") or metrics.get("blocker") or metrics.get("blocker_reason")
    validation_state = str(metrics.get("validation_state") or "unknown")
    completion_status = str(metrics.get("completion_status") or metrics.get("completion_state") or "")
    if job.status == "completed":
        completion_state = "completed"
    elif job.status in {"failed", "dead"}:
        completion_state = "failed"
    elif job.status == "blocked":
        completion_state = "blocked"
    elif job.status in {"running", "queued"}:
        completion_state = "running"
    else:
        completion_state = "not_started"
    if not completion_status:
        completion_status = completion_state
    title = _safe_text(metrics.get("title") or metrics.get("summary") or f"{job.job_type} job {job.id}")
    started_at = job.started_at or job.created_at
    return ObservabilityLineItem(
        id=f"obs_job_{job.id}",
        tenant_id=job.tenant_id,
        repo_id=job.repo_id,
        item_type="job",
        item_id=job.id,
        task_id=job.task_id,
        worker_id=job.owner,
        title=title,
        status=job.status,
        blocker=_safe_text(blocker, max_chars=240) if blocker else None,
        completion_state=completion_state,
        validation_state=validation_state,
        started_at=started_at,
        updated_at=job.updated_at,
        summary_json={
            "job_type": job.job_type,
            "metrics": _redacted_json(metrics),
            "error": _redacted_json(error),
        },
        worker_kind=_safe_text(metrics.get("worker_kind"), max_chars=120) or None,
        worker_status=_safe_text(metrics.get("worker_status") or metrics.get("worker_state") or job.status, max_chars=120),
        blocker_status=_safe_text(metrics.get("blocker_status") or ("blocked" if blocker or job.status == "blocked" else "none"), max_chars=120),
        completion_status=completion_status,
        model=_safe_text(metrics.get("model") or metrics.get("worker_model"), max_chars=160) or None,
        provider=_safe_text(metrics.get("provider") or metrics.get("worker_provider"), max_chars=160) or None,
        route=_safe_text(metrics.get("route") or metrics.get("model_route"), max_chars=160) or None,
        speckit_refs=_as_str_list(metrics.get("speckit_refs") or metrics.get("spec_kit_refs")),
        architecture_refs=_as_str_list(metrics.get("architecture_refs") or metrics.get("arch_refs")),
        task_list_refs=_as_str_list(metrics.get("task_list_refs") or metrics.get("tasks_refs")),
        memory_refs=_as_list_of_dicts(metrics.get("memory_refs")),
        cost_summary=_cost_summary(metrics),
        latency_summary=_latency_summary(
            metrics,
            started_at=started_at,
            updated_at=job.updated_at,
            finished_at=job.finished_at,
        ),
    )


def _redacted_json(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: Dict[str, Any] = {}
        for k, v in value.items():
            key = str(k)
            lowered = key.casefold()
            if lowered in {"raw_transcript_included", "secret_safe"}:
                redacted[key] = _redacted_json(v)
                continue
            if any(part in lowered for part in RAW_TEXT_KEY_PARTS):
                continue
            if any(part in lowered for part in SENSITIVE_KEY_PARTS):
                redacted[key] = "[REDACTED]"
            else:
                redacted[key] = _redacted_json(v)
        return redacted
    if isinstance(value, list):
        return [_redacted_json(v) for v in value]
    if isinstance(value, str):
        return _safe_text(value, max_chars=1000)
    return value


def _cost_summary(metrics: Dict[str, Any]) -> Dict[str, Any]:
    source = metrics.get("cost_summary") if isinstance(metrics.get("cost_summary"), dict) else {}
    token_source = metrics.get("token_estimate") if isinstance(metrics.get("token_estimate"), dict) else {}

    def _num(*keys: str, default: Any = 0) -> Any:
        for key in keys:
            if key in source:
                return source.get(key)
            if key in token_source:
                return token_source.get(key)
            if key in metrics:
                return metrics.get(key)
        return default

    return {
        "token_estimate": _num("token_estimate", "estimated_tokens", default=0),
        "input_tokens": _num("input_tokens", "prompt_tokens", default=0),
        "output_tokens": _num("output_tokens", "completion_tokens", default=0),
        "total_tokens": _num("total_tokens", "tokens", default=0),
        "cost_usd": _num("cost_usd", "usd", default=0),
        "estimated": bool(source.get("estimated") or token_source.get("estimated") or metrics.get("estimated_tokens")),
    }


def _latency_summary(
    metrics: Dict[str, Any],
    *,
    started_at: Optional[float],
    updated_at: Optional[float],
    finished_at: Optional[float],
) -> Dict[str, Any]:
    source = metrics.get("latency_summary") if isinstance(metrics.get("latency_summary"), dict) else {}
    duration_seconds = None
    if started_at is not None and finished_at is not None:
        duration_seconds = max(0.0, float(finished_at) - float(started_at))
    return {
        "wall_time_ms": source.get("wall_time_ms", metrics.get("wall_time_ms")),
        "latency_ms": source.get("latency_ms", metrics.get("latency_ms")),
        "duration_ms": source.get("duration_ms", metrics.get("duration_ms")),
        "duration_seconds": source.get("duration_seconds", metrics.get("duration_seconds", duration_seconds)),
        "started_at": source.get("started_at", started_at),
        "updated_at": source.get("updated_at", updated_at),
        "finished_at": source.get("finished_at", finished_at),
    }


def list_observability_items(db: SessionDB, filters: ObservabilityFilters) -> List[ObservabilityLineItem]:
    items: List[ObservabilityLineItem] = []
    if filters.item_type in {None, "", "job"}:
        jobs = list_learning_jobs(
            db,
            tenant_id=filters.tenant_id,
            repo_id=filters.repo_id,
            task_id=filters.task_id,
            job_type=filters.job_type,
            status=filters.status,
            owner=filters.worker_id,
            started_after=filters.date_from,
            started_before=filters.date_to,
            blocker=filters.blocker,
            limit=filters.limit,
        )
        items.extend(_job_to_line_item(job) for job in jobs)
    if filters.item_type in {None, "", "supervisor_task"} and not filters.job_type and not filters.candidate_kind:
        try:
            from hermes_cli.supervisor_control_plane import list_task_ledger_entries

            tasks = list_task_ledger_entries(
                db,
                tenant_id=filters.tenant_id,
                repo_id=filters.repo_id,
                state=filters.status,
                limit=filters.limit,
            )
        except Exception:
            tasks = []
        for task in tasks:
            if filters.task_id and task.task_id != filters.task_id:
                continue
            if filters.worker_id and task.worker_id != filters.worker_id:
                continue
            item = _supervisor_task_to_line_item(task)
            if _within_date_window(item.updated_at, filters.date_from, filters.date_to):
                items.append(item)
    if filters.item_type in {None, "", "candidate"} and not filters.task_id and not filters.worker_id and not filters.job_type:
        try:
            candidates = db.list_meta_candidates(
                tenant_id=filters.tenant_id,
                repo_id=filters.repo_id,
                kind=filters.candidate_kind,
                status=filters.status,
                limit=filters.limit,
            )
        except Exception:
            candidates = []
        for candidate in candidates:
            item = _candidate_to_line_item(candidate)
            if _within_date_window(item.updated_at, filters.date_from, filters.date_to):
                items.append(item)
    if filters.blocker:
        needle = filters.blocker.casefold()
        items = [
            item
            for item in items
            if needle in (item.blocker or "").casefold()
            or needle in json.dumps(item.summary_json, sort_keys=True, ensure_ascii=False).casefold()
        ]
    if filters.worker_status:
        needle = str(filters.worker_status).casefold()
        items = [item for item in items if needle == str(item.worker_status or "").casefold()]
    if filters.completion_status:
        needle = str(filters.completion_status).casefold()
        items = [
            item
            for item in items
            if needle in {str(item.completion_status or "").casefold(), str(item.completion_state or "").casefold()}
        ]
    items.sort(key=lambda item: item.updated_at or item.started_at or 0, reverse=True)
    return items[: max(1, int(filters.limit or 100))]


def _candidate_to_line_item(candidate: Dict[str, Any]) -> ObservabilityLineItem:
    evidence = candidate.get("evidence_json") if isinstance(candidate.get("evidence_json"), dict) else {}
    status = str(candidate.get("status") or "unknown")
    kind = str(candidate.get("kind") or "candidate")
    task_id = evidence.get("task_id") or evidence.get("source_task_id")
    title = _safe_text(candidate.get("claim") or f"{kind} {candidate.get('id')}")
    validation = evidence.get("validation") if isinstance(evidence.get("validation"), dict) else {}
    validation_state = str(validation.get("status") or "unknown")
    return ObservabilityLineItem(
        id=f"obs_candidate_{candidate.get('id')}",
        tenant_id=candidate.get("tenant_id"),
        repo_id=candidate.get("repo_id"),
        item_type="candidate",
        item_id=str(candidate.get("id")),
        task_id=str(task_id) if task_id else None,
        worker_id=None,
        title=title,
        status=status,
        blocker=_safe_text(evidence.get("blocker") or evidence.get("reason"), max_chars=240) if evidence else None,
        completion_state="completed" if status in {"approved", "applied"} else "pending",
        validation_state=validation_state,
        started_at=candidate.get("created_at"),
        updated_at=candidate.get("updated_at") or candidate.get("created_at"),
        summary_json={
            "candidate_kind": kind,
            "score": candidate.get("score"),
            "evidence": _redacted_json(evidence),
        },
        worker_status=status,
        blocker_status="blocked" if evidence.get("blocker") else "none",
        completion_status="completed" if status in {"approved", "applied"} else "pending",
    )


def _supervisor_task_to_line_item(task: Any) -> ObservabilityLineItem:
    blocker = None
    if task.state in {"blocked", "reclaimed", "validation_failed", "needs_operator"}:
        blocker = task.state
    metadata = task.metadata_json if isinstance(task.metadata_json, dict) else {}
    return ObservabilityLineItem(
        id=f"obs_supervisor_task_{task.task_id}",
        tenant_id=task.tenant_id,
        repo_id=task.repo_id,
        item_type="supervisor_task",
        item_id=task.task_id,
        task_id=task.task_id,
        worker_id=task.worker_id,
        title=_safe_text(task.task_description or f"Supervisor task {task.task_id}"),
        status=task.state,
        blocker=blocker,
        completion_state="completed" if task.state == "completed" else ("failed" if task.state in {"abandoned", "validation_failed"} else task.state),
        validation_state="unknown",
        started_at=task.created_at,
        updated_at=task.updated_at,
        summary_json={
            "worker_kind": task.worker_kind,
            "lease_owner": task.lease_owner,
            "lease_expires_at": task.lease_expires_at,
            "heartbeat_at": task.heartbeat_at,
            "retry_budget": task.retry_budget,
            "retry_count": task.retry_count,
            "goal": {
                "status": task.goal_json.get("status"),
                "turns_used": task.goal_json.get("turns_used"),
                "max_turns": task.goal_json.get("max_turns"),
                "last_verdict": task.goal_json.get("last_verdict"),
                "last_reason": task.goal_json.get("last_reason"),
            } if task.goal_json else {},
            "metadata": _redacted_json(task.metadata_json),
        },
        worker_kind=task.worker_kind,
        worker_status=task.state,
        blocker_status=_safe_text(metadata.get("blocker_status") or (blocker or "none"), max_chars=120),
        completion_status=_safe_text(metadata.get("completion_status") or ("completed" if task.state == "completed" else ("failed" if task.state in {"abandoned", "validation_failed"} else task.state)), max_chars=120),
        model=_safe_text(metadata.get("model") or metadata.get("worker_model"), max_chars=160) or None,
        provider=_safe_text(metadata.get("provider") or metadata.get("worker_provider"), max_chars=160) or None,
        route=_safe_text(metadata.get("route") or metadata.get("model_route"), max_chars=160) or None,
        speckit_refs=task.spec_kit_refs,
        architecture_refs=_as_str_list(metadata.get("architecture_refs") or metadata.get("arch_refs")),
        task_list_refs=_as_str_list(metadata.get("task_list_refs") or metadata.get("tasks_refs")),
        memory_refs=_as_list_of_dicts(metadata.get("memory_refs")),
        cost_summary=_cost_summary(metadata),
        latency_summary=_latency_summary(metadata, started_at=task.created_at, updated_at=task.updated_at, finished_at=None),
    )


def _within_date_window(value: Optional[float], date_from: Optional[float], date_to: Optional[float]) -> bool:
    if value is None:
        return True
    if date_from is not None and value < date_from:
        return False
    if date_to is not None and value > date_to:
        return False
    return True


def _parse_line_item_id(line_item_id: str) -> tuple[str, str]:
    if line_item_id.startswith("obs_job_"):
        return "job", line_item_id[len("obs_job_") :]
    if line_item_id.startswith("obs_candidate_"):
        return "candidate", line_item_id[len("obs_candidate_") :]
    if line_item_id.startswith("obs_supervisor_task_"):
        return "supervisor_task", line_item_id[len("obs_supervisor_task_") :]
    raise ValueError(f"unsupported observability line item id: {line_item_id}")


def build_evidence_bundle(
    db: SessionDB,
    *,
    line_item_id: str,
    tenant_id: Optional[str] = None,
    repo_id: Optional[str] = None,
) -> ObservabilityEvidenceBundle:
    item_type, source_id = _parse_line_item_id(line_item_id)
    if item_type == "candidate":
        return _candidate_evidence_bundle(
            db,
            source_id=source_id,
            line_item_id=line_item_id,
            tenant_id=tenant_id,
            repo_id=repo_id,
        )
    if item_type == "supervisor_task":
        return _supervisor_task_evidence_bundle(
            db,
            source_id=source_id,
            line_item_id=line_item_id,
            tenant_id=tenant_id,
            repo_id=repo_id,
        )
    if item_type != "job":
        raise ValueError(f"unsupported observability item type: {item_type}")
    job = get_learning_job(db, source_id)
    if job is None:
        raise ValueError(f"unknown learning job: {source_id}")
    _assert_scope(job.tenant_id, job.repo_id, tenant_id=tenant_id, repo_id=repo_id)
    metrics = job.metrics_json if isinstance(job.metrics_json, dict) else {}
    error = job.error_json if isinstance(job.error_json, dict) else {}
    evidence = _collect_related_evidence(db, job)
    task_description = _safe_text(metrics.get("task_description") or metrics.get("title") or metrics.get("summary") or f"{job.job_type} job {job.id}")
    memory_refs = evidence["memory_refs"] + _as_list_of_dicts(metrics.get("memory_refs"))
    bundle = ObservabilityEvidenceBundle(
        id=f"obs_bundle_{uuid.uuid4().hex[:16]}",
        tenant_id=job.tenant_id,
        repo_id=job.repo_id,
        task_id=job.task_id,
        line_item_id=line_item_id,
        task_description=task_description,
        supervisor_packet_ref=_safe_text(metrics.get("supervisor_packet_ref"), max_chars=400) or None,
        initial_assignment=_redacted_json(metrics.get("initial_assignment") or {}),
        agent_refs=_as_list_of_dicts(metrics.get("agent_refs")),
        speckit_refs=_as_str_list(metrics.get("speckit_refs") or metrics.get("spec_kit_refs")),
        branch_refs=_as_str_list(metrics.get("branch_refs")),
        validation_refs=_as_list_of_dicts(metrics.get("validation_refs")),
        memory_refs=memory_refs,
        event_refs=evidence["event_refs"],
        artifact_refs=_as_list_of_dicts(metrics.get("artifact_refs")) + _artifact_refs_from_job(job, error),
        raw_transcript_included=False,
    )
    bundle.secret_safe = _secret_safe(bundle.to_dict())
    return bundle


def _supervisor_task_evidence_bundle(
    db: SessionDB,
    *,
    source_id: str,
    line_item_id: str,
    tenant_id: Optional[str],
    repo_id: Optional[str],
) -> ObservabilityEvidenceBundle:
    from hermes_cli.supervisor_control_plane import (
        assess_task_convergence,
        get_task_ledger_entry,
        list_worker_heartbeats,
    )

    task = get_task_ledger_entry(db, source_id)
    if task is None:
        raise ValueError(f"unknown supervisor task: {source_id}")
    _assert_scope(task.tenant_id, task.repo_id, tenant_id=tenant_id, repo_id=repo_id)
    heartbeats = list_worker_heartbeats(db, task_id=source_id, limit=10)
    try:
        assessment = assess_task_convergence(db, task_id=source_id).to_dict()
    except Exception as exc:
        assessment = {"status": "error", "error": str(exc)}
    memory_refs = _as_list_of_dicts(task.metadata_json.get("memory_refs"))
    for hb in heartbeats:
        if hb.metadata_json.get("memory_packet_id"):
            memory_refs.append({"kind": "memory_packet", "id": _safe_text(hb.metadata_json.get("memory_packet_id"), max_chars=240)})
    bundle = ObservabilityEvidenceBundle(
        id=f"obs_bundle_{uuid.uuid4().hex[:16]}",
        tenant_id=task.tenant_id,
        repo_id=task.repo_id,
        task_id=task.task_id,
        line_item_id=line_item_id,
        task_description=_safe_text(task.task_description or f"supervisor task {source_id}"),
        supervisor_packet_ref=_safe_text(task.metadata_json.get("supervisor_packet_ref"), max_chars=400) or None,
        initial_assignment={
            "worker_id": task.worker_id,
            "worker_kind": task.worker_kind,
            "lease_owner": task.lease_owner,
            "lease_expires_at": task.lease_expires_at,
        },
        agent_refs=[
            {
                "kind": "worker",
                "id": task.worker_id,
                "worker_kind": task.worker_kind,
                "heartbeat_at": task.heartbeat_at,
            }
        ] if task.worker_id else [],
        speckit_refs=task.spec_kit_refs,
        branch_refs=task.git_refs,
        validation_refs=([
            {
                "kind": "task_goal",
                "id": f"goal:{task.task_id}",
                "status": task.goal_json.get("status"),
                "last_verdict": task.goal_json.get("last_verdict"),
                "last_reason": task.goal_json.get("last_reason"),
                "turns_used": task.goal_json.get("turns_used"),
                "max_turns": task.goal_json.get("max_turns"),
            }
        ] if task.goal_json else []) + [
            {
                "kind": "convergence_assessment",
                "id": f"assessment:{task.task_id}",
                "status": assessment.get("status"),
                "reasons": assessment.get("reasons", []),
                "recommended_action": assessment.get("recommended_action"),
            }
        ],
        memory_refs=memory_refs,
        event_refs=[
            {
                "kind": "worker_heartbeat",
                "id": hb.id,
                "status": hb.status,
                "worker_id": hb.worker_id,
                "progress_signature": hb.progress_signature,
                "command_signature": hb.command_signature,
                "error_signature": hb.error_signature,
                "created_at": hb.created_at,
            }
            for hb in heartbeats
        ],
        artifact_refs=[],
        raw_transcript_included=False,
    )
    bundle.secret_safe = _secret_safe(bundle.to_dict())
    return bundle


def _candidate_evidence_bundle(
    db: SessionDB,
    *,
    source_id: str,
    line_item_id: str,
    tenant_id: Optional[str],
    repo_id: Optional[str],
) -> ObservabilityEvidenceBundle:
    candidate = db.get_meta_candidate(source_id)
    if candidate is None:
        raise ValueError(f"unknown memory candidate: {source_id}")
    _assert_scope(candidate.get("tenant_id"), candidate.get("repo_id"), tenant_id=tenant_id, repo_id=repo_id)
    evidence = candidate.get("evidence_json") if isinstance(candidate.get("evidence_json"), dict) else {}
    task_id = evidence.get("task_id") or evidence.get("source_task_id")
    refs: List[Dict[str, Any]] = [
        {
            "kind": "candidate",
            "id": candidate.get("id"),
            "status": candidate.get("status"),
            "claim": _safe_text(candidate.get("claim"), max_chars=400),
            "score": candidate.get("score"),
        }
    ]
    source_ref = evidence.get("source_record_id") or evidence.get("record_id") or evidence.get("evidence_uri")
    event_refs = [{"kind": "candidate_evidence", "id": str(source_ref)}] if source_ref else []
    bundle = ObservabilityEvidenceBundle(
        id=f"obs_bundle_{uuid.uuid4().hex[:16]}",
        tenant_id=candidate.get("tenant_id"),
        repo_id=candidate.get("repo_id"),
        task_id=str(task_id) if task_id else None,
        line_item_id=line_item_id,
        task_description=_safe_text(candidate.get("claim") or f"candidate {source_id}"),
        supervisor_packet_ref=_safe_text(evidence.get("packet_id") or evidence.get("memory_packet_id"), max_chars=400) or None,
        initial_assignment=_redacted_json(evidence.get("initial_assignment") or {}),
        agent_refs=_as_list_of_dicts(evidence.get("agent_refs")),
        speckit_refs=_as_str_list(evidence.get("speckit_refs")),
        branch_refs=_as_str_list(evidence.get("branch_refs")),
        validation_refs=_as_list_of_dicts(evidence.get("validation")),
        memory_refs=refs,
        event_refs=event_refs,
        artifact_refs=_as_list_of_dicts(evidence.get("artifact_refs")),
        raw_transcript_included=False,
    )
    bundle.secret_safe = _secret_safe(bundle.to_dict())
    return bundle


def _assert_scope(
    item_tenant: Optional[str],
    item_repo: Optional[str],
    *,
    tenant_id: Optional[str],
    repo_id: Optional[str],
) -> None:
    if tenant_id is not None and item_tenant != tenant_id:
        raise PermissionError("line item is outside requested tenant scope")
    if repo_id is not None and item_repo != repo_id:
        raise PermissionError("line item is outside requested repo scope")


def _as_str_list(value: Any) -> List[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [_safe_text(v, max_chars=400) for v in value if v]
    return [_safe_text(value, max_chars=400)]


def _as_list_of_dicts(value: Any) -> List[Dict[str, Any]]:
    if not value:
        return []
    if isinstance(value, list):
        return [_redacted_json(v) for v in value if isinstance(v, dict)]
    if isinstance(value, dict):
        return [_redacted_json(value)]
    return []


def _artifact_refs_from_job(job: LearningJobRecord, error: Dict[str, Any]) -> List[Dict[str, Any]]:
    refs: List[Dict[str, Any]] = []
    if error:
        refs.append({"kind": "job_error", "job_id": job.id, "summary": _safe_text(error)})
    return refs


def _collect_related_evidence(db: SessionDB, job: LearningJobRecord) -> Dict[str, List[Dict[str, Any]]]:
    memory_refs: List[Dict[str, Any]] = []
    event_refs: List[Dict[str, Any]] = []
    try:
        from hermes_cli.learning_bus import list_learning_events

        for event in list_learning_events(
            db,
            tenant_id=job.tenant_id,
            repo_id=job.repo_id,
            limit=25,
        ):
            if job.task_id is not None and event.task_id not in {None, job.task_id}:
                continue
            event_refs.append(
                {
                    "kind": "learning_event",
                    "id": event.id,
                    "topic": event.topic,
                    "status": event.status,
                    "task_id": event.task_id,
                    "created_at": event.created_at,
                }
            )
    except Exception:
        pass
    try:
        for candidate in db.list_meta_candidates(tenant_id=job.tenant_id, repo_id=job.repo_id, limit=25):
            memory_refs.append(
                {
                    "kind": "candidate",
                    "id": candidate.get("id"),
                    "status": candidate.get("status"),
                    "claim": _safe_text(candidate.get("claim"), max_chars=240),
                }
            )
    except Exception:
        pass
    try:
        from hermes_cli.memory_wiki import list_memory_wiki_claims

        for claim in list_memory_wiki_claims(db, tenant_id=job.tenant_id, repo_id=job.repo_id, limit=25):
            memory_refs.append(
                {
                    "kind": "wiki_claim",
                    "id": claim.id,
                    "status": claim.status,
                    "claim": _safe_text(claim.claim, max_chars=240),
                }
            )
    except Exception:
        pass
    try:
        from hermes_cli.memory_dreaming import list_dreaming_proposals

        for proposal in list_dreaming_proposals(db, tenant_id=job.tenant_id, repo_id=job.repo_id, limit=25):
            memory_refs.append(
                {
                    "kind": "dreaming_proposal",
                    "id": proposal.id,
                    "status": proposal.status,
                    "summary": _safe_text(proposal.summary, max_chars=240),
                }
            )
    except Exception:
        pass
    return {"memory_refs": memory_refs, "event_refs": event_refs}


def _line_item_to_runtime_dict(item: ObservabilityLineItem) -> Dict[str, Any]:
    task_description = item.summary_json.get("metrics", {}).get("task_description") if isinstance(item.summary_json.get("metrics"), dict) else None
    return {
        "id": item.id,
        "line_item_id": item.id,
        "item_type": item.item_type,
        "item_id": item.item_id,
        "job_id": item.item_id if item.item_type == "job" else None,
        "task_id": item.task_id,
        "tenant_id": item.tenant_id,
        "repo_id": item.repo_id,
        "title": item.title,
        "task_description": _safe_text(task_description or item.title, max_chars=500),
        "status": item.status,
        "worker_id": item.worker_id,
        "worker": {
            "id": item.worker_id,
            "kind": item.worker_kind,
            "status": item.worker_status or item.status,
        },
        "model": {
            "provider": item.provider,
            "model": item.model,
            "route": item.route,
        },
        "spec_kit_refs": item.speckit_refs,
        "architecture_refs": item.architecture_refs,
        "task_list_refs": item.task_list_refs,
        "blocker": item.blocker,
        "blocker_status": item.blocker_status,
        "completion_state": item.completion_state,
        "completion_status": item.completion_status or item.completion_state,
        "validation_state": item.validation_state,
        "evidence_bundle_id": f"obs_bundle_for_{item.id}",
        "memory_refs": item.memory_refs,
        "cost_summary": item.cost_summary or _cost_summary({}),
        "latency_summary": item.latency_summary or _latency_summary({}, started_at=item.started_at, updated_at=item.updated_at, finished_at=None),
        "started_at": item.started_at,
        "updated_at": item.updated_at,
        "summary_json": _redacted_json(item.summary_json),
    }


def list_runtime_observability_snapshot(db: SessionDB, filters: ObservabilityFilters) -> Dict[str, Any]:
    rows = list_observability_items(db, filters)
    items = [_line_item_to_runtime_dict(row) for row in rows]
    return {
        "filters": filters.to_dict(),
        "items": items,
        "count": len(items),
        "active_count": sum(1 for item in items if item["status"] in {"queued", "running", "ready"}),
        "historical_count": sum(1 for item in items if item["status"] in {"completed", "failed", "blocked", "dead", "abandoned", "validation_failed"}),
        "raw_transcripts_included": False,
    }


def resolve_observability_line_item_id(
    db: SessionDB,
    *,
    line_item_id: Optional[str] = None,
    job_id: Optional[str] = None,
    task_id: Optional[str] = None,
) -> str:
    if line_item_id:
        return line_item_id
    if job_id:
        if get_learning_job(db, job_id) is None:
            raise ValueError(f"unknown learning job: {job_id}")
        return f"obs_job_{job_id}"
    if task_id:
        try:
            from hermes_cli.supervisor_control_plane import get_task_ledger_entry

            if get_task_ledger_entry(db, task_id) is not None:
                return f"obs_supervisor_task_{task_id}"
        except Exception:
            pass
        jobs = list_learning_jobs(db, task_id=task_id, limit=1)
        if jobs:
            return f"obs_job_{jobs[0].id}"
        raise ValueError(f"unknown observability task: {task_id}")
    raise ValueError("line_item_id, job_id, or task_id is required")


def _line_item_for_id(db: SessionDB, line_item_id: str) -> ObservabilityLineItem:
    item_type, source_id = _parse_line_item_id(line_item_id)
    if item_type == "job":
        job = get_learning_job(db, source_id)
        if job is None:
            raise ValueError(f"unknown learning job: {source_id}")
        return _job_to_line_item(job)
    if item_type == "supervisor_task":
        from hermes_cli.supervisor_control_plane import get_task_ledger_entry

        task = get_task_ledger_entry(db, source_id)
        if task is None:
            raise ValueError(f"unknown supervisor task: {source_id}")
        return _supervisor_task_to_line_item(task)
    if item_type == "candidate":
        candidate = db.get_meta_candidate(source_id)
        if candidate is None:
            raise ValueError(f"unknown memory candidate: {source_id}")
        return _candidate_to_line_item(candidate)
    raise ValueError(f"unsupported observability item type: {item_type}")


def build_observability_detail(
    db: SessionDB,
    *,
    line_item_id: Optional[str] = None,
    job_id: Optional[str] = None,
    task_id: Optional[str] = None,
    tenant_id: Optional[str] = None,
    repo_id: Optional[str] = None,
) -> RuntimeObservabilityDetail:
    resolved_id = resolve_observability_line_item_id(db, line_item_id=line_item_id, job_id=job_id, task_id=task_id)
    bundle = build_evidence_bundle(db, line_item_id=resolved_id, tenant_id=tenant_id, repo_id=repo_id)
    item = _line_item_for_id(db, resolved_id)
    _assert_scope(item.tenant_id, item.repo_id, tenant_id=tenant_id, repo_id=repo_id)
    return RuntimeObservabilityDetail(
        line_item=_line_item_to_runtime_dict(item),
        evidence_bundle=_redacted_json(bundle.to_dict()),
    )


def scoped_analysis(
    db: SessionDB,
    *,
    line_item_id: Optional[str] = None,
    job_id: Optional[str] = None,
    task_id: Optional[str] = None,
    question: str = "",
    tenant_id: Optional[str] = None,
    repo_id: Optional[str] = None,
    repo_query_allowed: bool = False,
    repo_path: Optional[str] = None,
    model_call: Optional[Callable[[str, ObservabilityEvidenceBundle], str]] = None,
) -> ScopedAnalysisResult:
    resolved_id = resolve_observability_line_item_id(db, line_item_id=line_item_id, job_id=job_id, task_id=task_id)
    bundle = build_evidence_bundle(
        db,
        line_item_id=resolved_id,
        tenant_id=tenant_id,
        repo_id=repo_id,
    )
    repo_context = _read_only_repo_context(repo_path) if repo_query_allowed and repo_path else {}
    prompt = _build_analysis_prompt(question, bundle, repo_context)
    if model_call is not None:
        answer = model_call(prompt, bundle)
    else:
        answer = _deterministic_analysis_answer(question, bundle, repo_context, _line_item_for_id(db, resolved_id))
    citations = _bundle_citations(bundle)
    return ScopedAnalysisResult(
        id=f"analysis_{uuid.uuid4().hex[:16]}",
        tenant_id=bundle.tenant_id,
        repo_id=bundle.repo_id,
        task_id=bundle.task_id,
        line_item_id=resolved_id,
        question=_safe_text(question, max_chars=1000),
        evidence_bundle_id=bundle.id,
        repo_query_allowed=bool(repo_query_allowed),
        repo_query_mode="read_only" if repo_query_allowed else "none",
        answer=_safe_text(answer, max_chars=4000),
        citations=citations,
        mutation_allowed=False,
    )


def _build_analysis_prompt(question: str, bundle: ObservabilityEvidenceBundle, repo_context: Dict[str, Any]) -> str:
    evidence = bundle.to_dict()
    return (
        "You are a read-only Hermes observability analyst. Answer the operator question "
        "using only the evidence bundle and optional read-only repo context. Cite evidence ids. "
        "Do not mutate repo, task state, memory, config, wiki, candidates, proposals, or policy.\n\n"
        f"Question: {_safe_text(question, max_chars=1000)}\n"
        f"Evidence JSON:\n{json.dumps(evidence, indent=2, ensure_ascii=False)}\n"
        f"Repo context JSON:\n{json.dumps(repo_context, indent=2, ensure_ascii=False)}\n"
    )


def _deterministic_analysis_answer(
    question: str,
    bundle: ObservabilityEvidenceBundle,
    repo_context: Dict[str, Any],
    line_item: Optional[ObservabilityLineItem] = None,
) -> str:
    parts = [
        f"Task/job summary: {bundle.task_description}.",
        f"Scope: tenant={bundle.tenant_id or 'global'} repo={bundle.repo_id or 'global'} task={bundle.task_id or 'unknown'}.",
    ]
    if bundle.validation_refs:
        parts.append(f"Validation refs available: {len(bundle.validation_refs)}.")
    if bundle.memory_refs:
        memory_ids = [str(ref.get("id")) for ref in bundle.memory_refs if isinstance(ref, dict) and ref.get("id")]
        parts.append(f"Memory/candidate refs available: {len(bundle.memory_refs)} ({', '.join(memory_ids[:5])}).")
    if bundle.event_refs:
        parts.append(f"Event refs available: {len(bundle.event_refs)}.")
    if line_item is not None:
        parts.append(f"Status: blocker={line_item.blocker or 'none'} completion={line_item.completion_status or line_item.completion_state}.")
        cost = line_item.cost_summary or {}
        if cost:
            parts.append(
                "Cost summary: "
                f"total_tokens={cost.get('total_tokens', 0)} "
                f"input_tokens={cost.get('input_tokens', 0)} "
                f"output_tokens={cost.get('output_tokens', 0)} "
                f"cost_usd={cost.get('cost_usd', 0)}."
            )
        latency = line_item.latency_summary or {}
        if latency:
            parts.append(
                "Latency summary: "
                f"wall_time_ms={latency.get('wall_time_ms')} "
                f"latency_ms={latency.get('latency_ms')} "
                f"duration_ms={latency.get('duration_ms')}."
            )
    if repo_context:
        parts.append(f"Read-only repo context included: {', '.join(repo_context.keys())}.")
    parts.append("Mutation authority: disabled.")
    return " ".join(parts)


def _bundle_citations(bundle: ObservabilityEvidenceBundle) -> List[str]:
    citations = [bundle.line_item_id]
    for collection in (bundle.validation_refs, bundle.memory_refs, bundle.event_refs, bundle.artifact_refs):
        for item in collection:
            ref = item.get("id") or item.get("job_id") or item.get("uri")
            if ref:
                citations.append(str(ref))
    for ref in bundle.speckit_refs + bundle.branch_refs:
        citations.append(str(ref))
    return sorted(set(citations))


def _read_only_repo_context(repo_path: Optional[str]) -> Dict[str, Any]:
    if not repo_path:
        return {}
    path = Path(repo_path).expanduser()
    if not path.exists() or not path.is_dir():
        return {"repo_path": str(path), "status": "missing"}
    refs: Dict[str, Any] = {"repo_path": str(path), "status": "read_only"}
    for name in ("specs", ".git"):
        refs[f"has_{name}"] = (path / name).exists()
    try:
        refs["top_level_files"] = sorted(p.name for p in path.iterdir())[:25]
    except Exception:
        refs["top_level_files"] = []
    return refs
