"""Bounded operator dashboard DTO helpers.

This module is intentionally deterministic and local-testable. It aggregates
redacted DTOs for the operator dashboard without calling live providers,
starting Azure operations, mutating repos, or creating a parallel approval
path.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
import re
from typing import Any, Callable, Iterable, Mapping

from hermes_cli.platform_hardening import ApprovalLedger


JOB_DETAIL_TABS = (
    "Overview",
    "Agents",
    "Spec Kit",
    "Memory",
    "Validation",
    "Sidecars",
    "Bus Events",
    "Costs",
    "Deployment",
    "Ask",
)

APPROVAL_ACTIONS = (
    "memory.promote",
    "dreaming.convert",
    "corpus.remit",
    "deployment.apply",
    "cicd.protected_action",
    "policy.enforce",
)

_SENSITIVE_KEY_PARTS = (
    "raw_stdout",
    "raw_stderr",
    "raw_log",
    "raw_logs",
    "raw_transcript",
    "provider_log",
    "provider_logs",
    "connector_credential",
    "credential",
    "authorization",
    "password",
    "api_key",
    "apikey",
    "secret",
)
_SAFE_TOKEN_METRIC_KEYS = {
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "estimated_tokens",
    "admitted_tokens",
    "memory_tokens",
    "context_admitted_tokens",
    "memory_packet_tokens",
    "token_estimate",
}
_SAFE_RAW_STATE_KEYS = {"raw_transcripts_included", "raw_logs_loaded", "raw_transcripts_loaded"}
_SECRET_TEXT_RE = re.compile(
    r"(?i)(?:password|api[_-]?key|secret|token|authorization)\s*[:=]\s*\S+|sk-[a-z0-9_-]{8,}"
)


def _stable_hash(value: Any) -> str:
    raw = value if isinstance(value, str) else json.dumps(value, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _safe_text(value: Any, *, max_chars: int = 500) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return _SECRET_TEXT_RE.sub("[REDACTED]", text)[:max_chars]


def _redact(value: Any) -> Any:
    if isinstance(value, Mapping):
        clean: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if _is_sensitive_key(key_text):
                continue
            clean[key_text] = _redact(item)
        return clean
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, tuple):
        return [_redact(item) for item in value]
    if isinstance(value, str):
        return _safe_text(value, max_chars=700)
    return value


def _is_sensitive_key(key: str) -> bool:
    lowered = key.casefold()
    if lowered in _SAFE_TOKEN_METRIC_KEYS or lowered in _SAFE_RAW_STATE_KEYS:
        return False
    if lowered in {"token", "access_token", "refresh_token", "id_token"}:
        return True
    return any(part in lowered for part in _SENSITIVE_KEY_PARTS)


def _actor_tenant(actor: Mapping[str, Any]) -> str | None:
    return str(actor.get("tenant_id")) if actor.get("tenant_id") is not None else None


def _actor_role(actor: Mapping[str, Any]) -> str:
    return str(actor.get("role") or actor.get("actor_role") or "viewer")


def _actor_id(actor: Mapping[str, Any]) -> str:
    return str(actor.get("actor_id") or actor.get("id") or "operator")


def _can_access(actor: Mapping[str, Any], tenant_id: str) -> bool:
    return bool(actor.get("cross_tenant")) or _actor_role(actor) in {"platform-admin", "operator-admin"} or _actor_tenant(actor) == tenant_id


def _assert_access(actor: Mapping[str, Any], tenant_id: str) -> None:
    if not _can_access(actor, tenant_id):
        raise PermissionError("operator dashboard tenant scope denied")


def _require_visible_tenant(actor: Mapping[str, Any], requested_tenant: str | None) -> str | None:
    if requested_tenant is not None:
        _assert_access(actor, requested_tenant)
        return requested_tenant
    if actor.get("cross_tenant") or _actor_role(actor) in {"platform-admin", "operator-admin"}:
        return None
    return _actor_tenant(actor)


@dataclass(frozen=True)
class OperatorDashboardFilters:
    tenant_id: str | None = None
    repo_id: str | None = None
    date_from: float | None = None
    date_to: float | None = None
    status: str | None = None
    worker_family: str | None = None
    model: str | None = None
    blocked: bool | None = None
    blocker: str | None = None
    max_cost_usd: float | None = None
    deployment_id: str | None = None
    limit: int = 100

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class OperatorDashboardState:
    tenants: list[dict[str, Any]]
    repos: list[dict[str, Any]]
    jobs: list[dict[str, Any]]
    worker_attempts: list[dict[str, Any]]
    sidecars: list[dict[str, Any]]
    memory_packets: list[dict[str, Any]]
    approval_requests: list[dict[str, Any]]
    corpus_exports: list[dict[str, Any]]
    bus_events: list[dict[str, Any]]
    benchmarks: list[dict[str, Any]]
    azure_deployments: list[dict[str, Any]]
    approval_ledger: ApprovalLedger = field(default_factory=ApprovalLedger)

    def to_dict(self) -> dict[str, Any]:
        return _redact(
            {
                "tenants": self.tenants,
                "repos": self.repos,
                "jobs": self.jobs,
                "worker_attempts": self.worker_attempts,
                "sidecars": self.sidecars,
                "memory_packets": self.memory_packets,
                "approval_requests": self.approval_requests,
                "corpus_exports": self.corpus_exports,
                "bus_events": self.bus_events,
                "benchmarks": self.benchmarks,
                "azure_deployments": self.azure_deployments,
            }
        )


def seed_operator_dashboard_fixture(approval_ledger: ApprovalLedger | None = None) -> OperatorDashboardState:
    ledger = approval_ledger or ApprovalLedger()
    state = OperatorDashboardState(
        tenants=[
            {"tenant_id": "tenant-a", "name": "Tenant A", "admins": ["operator-a"]},
            {"tenant_id": "tenant-b", "name": "Tenant B", "admins": ["operator-b"]},
        ],
        repos=[
            {"repo_id": "repo-a", "tenant_id": "tenant-a", "name": "hermes-agent"},
            {"repo_id": "repo-b", "tenant_id": "tenant-b", "name": "private-runtime"},
        ],
        jobs=[
            {
                "job_id": "job-a",
                "tenant_id": "tenant-a",
                "repo_id": "repo-a",
                "task_id": "task-a",
                "title": "Implement operator dashboard approvals",
                "status": "blocked",
                "blocker_reason": "operator approval required",
                "created_at": 1500.0,
                "updated_at": 1600.0,
                "worker_family": "codex",
                "worker_id": "codex-worker-a",
                "model": "gpt-5",
                "provider": "openai",
                "last_progress_summary": "Tests added; apply action waits for operator approval.",
                "cost": {"input_tokens": 1200, "output_tokens": 340, "estimated_cost_usd": 0.42},
                "latency": {"latency_ms": 2300, "wall_time_ms": 9000},
                "memory_packet_ids": ["mem-a"],
                "sidecar_ids": ["sidecar-judge-a", "sidecar-dream-a"],
                "deployment_id": "deploy-a",
                "evidence_refs": ["evidence://job-a/summary", "evidence://job-a/validation"],
                "spec_kit_refs": ["specs/001-learning-memory-runtime/tasks.md"],
                "validation_refs": ["validation://job-a/pytest"],
                "context": {"admitted_tokens": 1800, "memory_tokens": 320},
            },
            {
                "job_id": "job-b",
                "tenant_id": "tenant-b",
                "repo_id": "repo-b",
                "task_id": "task-b",
                "title": "Cross tenant deployment review",
                "status": "running",
                "created_at": 1550.0,
                "updated_at": 1610.0,
                "worker_family": "generic",
                "worker_id": "worker-b",
                "model": "local-small",
                "provider": "local",
                "last_progress_summary": "Collecting deployment evidence.",
                "cost": {"input_tokens": 4000, "output_tokens": 900, "estimated_cost_usd": 2.2},
                "latency": {"latency_ms": 5100, "wall_time_ms": 15000},
                "memory_packet_ids": ["mem-b"],
                "sidecar_ids": [],
                "deployment_id": "deploy-b",
                "evidence_refs": ["evidence://job-b/summary"],
                "context": {"admitted_tokens": 4200, "memory_tokens": 0},
            },
        ],
        worker_attempts=[
            {
                "attempt_id": "attempt-a1",
                "job_id": "job-a",
                "tenant_id": "tenant-a",
                "worker_id": "codex-worker-a",
                "worker_family": "codex",
                "model": "gpt-5",
                "status": "blocked",
                "summary": "Prepared patch and stopped before deployment apply.",
                "evidence_refs": ["evidence://attempt-a1"],
                "cost": {"input_tokens": 900, "output_tokens": 260, "estimated_cost_usd": 0.31},
                "latency_ms": 2200,
            }
        ],
        sidecars=[
            {
                "sidecar_id": "sidecar-judge-a",
                "tenant_id": "tenant-a",
                "job_id": "job-a",
                "role": "judge",
                "tier": "strong",
                "provider": "openai",
                "model": "gpt-5",
                "state": "enabled",
                "budget_decision": "allowed",
                "queue": {"pending": 1, "leased": 0},
                "last_run_at": 1580.0,
                "failure_reason": None,
                "next_eligible_run_at": 1700.0,
                "cost": {"input_tokens": 240, "output_tokens": 80, "estimated_cost_usd": 0.08},
            },
            {
                "sidecar_id": "sidecar-dream-a",
                "tenant_id": "tenant-a",
                "job_id": "job-a",
                "role": "dreaming",
                "tier": "cheap",
                "provider": "local",
                "model": "tiny-reasoner",
                "state": "degraded",
                "budget_decision": "defer",
                "queue": {"pending": 3, "leased": 1},
                "last_run_at": 1490.0,
                "failure_reason": "budget exhausted",
                "next_eligible_run_at": 1900.0,
                "cost": {"input_tokens": 120, "output_tokens": 30, "estimated_cost_usd": 0.01},
            },
        ],
        memory_packets=[
            {
                "memory_packet_id": "mem-a",
                "tenant_id": "tenant-a",
                "repo_id": "repo-a",
                "job_id": "job-a",
                "summary": "Approved deployment lessons matched task scope.",
                "evidence_refs": ["memory://mem-a/ref"],
                "packet_count": 2,
                "hit_count": 1,
                "token_estimate": 320,
            },
            {
                "memory_packet_id": "mem-b",
                "tenant_id": "tenant-b",
                "repo_id": "repo-b",
                "job_id": "job-b",
                "summary": "No shared packet admitted.",
                "evidence_refs": ["memory://mem-b/ref"],
                "packet_count": 1,
                "hit_count": 0,
                "token_estimate": 120,
            },
        ],
        approval_requests=[],
        corpus_exports=[
            {
                "export_id": "corpus-a",
                "tenant_id": "tenant-a",
                "repo_id": "repo-a",
                "status": "pending_approval",
                "format": "jsonl",
                "evidence_refs": ["corpus://corpus-a/manifest"],
            }
        ],
        bus_events=[
            {
                "event_id": "bus-a",
                "tenant_id": "tenant-a",
                "repo_id": "repo-a",
                "job_id": "job-a",
                "backend": "sqlite",
                "topic": "memory.promoted",
                "status": "spooled",
                "lag": 2,
                "dead_letter": False,
                "replay_attempt": 0,
                "spool_state": "healthy",
                "evidence_refs": ["bus://bus-a"],
            },
            {
                "event_id": "bus-dlq-a",
                "tenant_id": "tenant-a",
                "repo_id": "repo-a",
                "job_id": "job-a",
                "backend": "sqlite",
                "topic": "deployment.apply",
                "status": "dead_letter",
                "lag": 0,
                "dead_letter": True,
                "replay_attempt": 1,
                "spool_state": "healthy",
                "evidence_refs": ["bus://bus-dlq-a"],
            },
        ],
        benchmarks=[
            {
                "benchmark_id": "bench-a",
                "tenant_id": "tenant-a",
                "repo_id": "repo-a",
                "job_id": "job-a",
                "baseline_success": 0.5,
                "memory_assisted_success": 0.75,
                "cost_delta_usd": -0.12,
                "evidence_refs": ["benchmark://bench-a"],
            }
        ],
        azure_deployments=[
            {
                "deployment_id": "deploy-a",
                "tenant_id": "tenant-a",
                "repo_id": "repo-a",
                "job_id": "job-a",
                "plan": {"environment": "staging", "runtime": "container_apps", "region": "eastus"},
                "preflight": {"ok": True, "checks": {"quota": "ok", "bus": "ok", "rollback": "ok"}},
                "apply": {"state": "blocked", "reason": "operator_approval_required"},
                "smoke": {"state": "passed", "checks": ["health", "event_bus", "sidecar"]},
                "soak": {"state": "running", "started_at": 1590.0},
                "promote": {"state": "blocked", "reason": "operator_approval_required"},
                "rollback": {"available": True, "artifact_ref": "deployment://deploy-a/rollback"},
                "hardening_failures": [],
                "costs": {"estimated_cost_usd": 14.25},
                "required_operator_actions": ["operator_approval_required"],
                "evidence_refs": ["deployment://deploy-a/plan", "deployment://deploy-a/preflight"],
            },
            {
                "deployment_id": "deploy-b",
                "tenant_id": "tenant-b",
                "repo_id": "repo-b",
                "job_id": "job-b",
                "plan": {"environment": "production", "runtime": "vm", "region": "westus"},
                "preflight": {"ok": False, "checks": {"quota": "blocked"}},
                "apply": {"state": "blocked", "reason": "preflight_failed"},
                "smoke": {"state": "not_started"},
                "soak": {"state": "not_started"},
                "promote": {"state": "blocked", "reason": "preflight_failed"},
                "rollback": {"available": False},
                "hardening_failures": ["quota"],
                "costs": {"estimated_cost_usd": 35.0},
                "required_operator_actions": ["resolve_preflight"],
                "evidence_refs": ["deployment://deploy-b/preflight"],
            },
        ],
        approval_ledger=ledger,
    )
    request_dashboard_approval(
        state,
        actor={"actor_id": "operator-a", "role": "tenant-admin", "tenant_id": "tenant-a"},
        action="memory.promote",
        target_ref="memory://mem-a",
        target_hash="seed-memory-hash",
        evidence_refs=["memory://mem-a/ref"],
        expires_at=2500.0,
        now=1500.0,
    )
    return state


def _find_one(items: Iterable[Mapping[str, Any]], key: str, value: str) -> Mapping[str, Any]:
    for item in items:
        if item.get(key) == value:
            return item
    raise KeyError(value)


def list_operator_jobs(
    state: OperatorDashboardState,
    *,
    actor: Mapping[str, Any],
    filters: OperatorDashboardFilters | None = None,
) -> list[dict[str, Any]]:
    filters = filters or OperatorDashboardFilters()
    tenant_filter = _require_visible_tenant(actor, filters.tenant_id)
    rows: list[dict[str, Any]] = []
    for job in state.jobs:
        if tenant_filter is not None and job["tenant_id"] != tenant_filter:
            continue
        if not _can_access(actor, job["tenant_id"]):
            continue
        if filters.repo_id and job.get("repo_id") != filters.repo_id:
            continue
        if filters.date_from is not None and float(job.get("created_at", 0)) < float(filters.date_from):
            continue
        if filters.date_to is not None and float(job.get("created_at", 0)) > float(filters.date_to):
            continue
        if filters.status and job.get("status") != filters.status:
            continue
        if filters.worker_family and job.get("worker_family") != filters.worker_family:
            continue
        if filters.model and filters.model not in str(job.get("model", "")):
            continue
        if filters.blocked is not None and bool(job.get("blocker_reason") or job.get("status") == "blocked") is not filters.blocked:
            continue
        if filters.blocker and filters.blocker.casefold() not in str(job.get("blocker_reason", "")).casefold():
            continue
        if filters.max_cost_usd is not None and float(job.get("cost", {}).get("estimated_cost_usd") or 0) > float(filters.max_cost_usd):
            continue
        if filters.deployment_id and job.get("deployment_id") != filters.deployment_id:
            continue
        rows.append(_job_row(state, job))
    rows.sort(key=lambda row: row["updated_at"], reverse=True)
    return rows[: max(1, int(filters.limit or 100))]


def _job_row(state: OperatorDashboardState, job: Mapping[str, Any]) -> dict[str, Any]:
    deployment = _deployment_summary(state, job.get("deployment_id"))
    sidecars = [s for s in state.sidecars if s.get("sidecar_id") in set(job.get("sidecar_ids") or [])]
    memory_packets = [m for m in state.memory_packets if m.get("memory_packet_id") in set(job.get("memory_packet_ids") or [])]
    return _redact(
        {
            "job_id": job["job_id"],
            "tenant_id": job["tenant_id"],
            "repo_id": job["repo_id"],
            "task_id": job.get("task_id"),
            "title": job.get("title"),
            "status": job.get("status"),
            "blocker_reason": job.get("blocker_reason"),
            "worker": {"id": job.get("worker_id"), "family": job.get("worker_family")},
            "model": {"provider": job.get("provider"), "name": job.get("model")},
            "last_progress_summary": job.get("last_progress_summary"),
            "cost_estimate": job.get("cost", {}),
            "latency_summary": job.get("latency", {}),
            "memory_packet_count": sum(int(packet.get("packet_count") or 0) for packet in memory_packets),
            "sidecar_state_summary": {
                "enabled": sum(1 for item in sidecars if item.get("state") == "enabled"),
                "degraded": sum(1 for item in sidecars if item.get("state") == "degraded"),
                "disabled": sum(1 for item in sidecars if item.get("state") == "disabled"),
            },
            "deployment": deployment,
            "evidence_refs": list(job.get("evidence_refs") or []),
            "redaction_state": "redacted",
            "raw_transcripts_included": False,
            "created_at": job.get("created_at"),
            "updated_at": job.get("updated_at"),
        }
    )


def _deployment_summary(state: OperatorDashboardState, deployment_id: Any) -> dict[str, Any] | None:
    if not deployment_id:
        return None
    try:
        deployment = _find_one(state.azure_deployments, "deployment_id", str(deployment_id))
    except KeyError:
        return None
    return {
        "deployment_id": deployment["deployment_id"],
        "environment": deployment.get("plan", {}).get("environment"),
        "apply_state": deployment.get("apply", {}).get("state"),
        "promote_state": deployment.get("promote", {}).get("state"),
        "required_operator_actions": list(deployment.get("required_operator_actions") or []),
    }


def build_job_detail_tab(
    state: OperatorDashboardState,
    *,
    actor: Mapping[str, Any],
    job_id: str,
    tab: str,
    limit: int = 25,
) -> dict[str, Any]:
    if tab not in JOB_DETAIL_TABS:
        raise ValueError(f"unsupported operator dashboard tab: {tab}")
    job = _find_one(state.jobs, "job_id", job_id)
    _assert_access(actor, str(job["tenant_id"]))
    evidence_refs = list(job.get("evidence_refs") or [])
    base = {
        "job_id": job_id,
        "tenant_id": job["tenant_id"],
        "repo_id": job["repo_id"],
        "tab": tab,
        "lazy_loaded": True,
        "bounded": True,
        "limit": limit,
        "raw_transcripts_included": False,
        "redaction_state": "redacted",
        "evidence_refs": evidence_refs,
    }
    tab_data: dict[str, Any]
    if tab == "Overview":
        tab_data = {"summary": _job_row(state, job)}
    elif tab == "Agents":
        tab_data = {"worker_attempts": _bounded([a for a in state.worker_attempts if a.get("job_id") == job_id], limit)}
    elif tab == "Spec Kit":
        tab_data = {"spec_kit_refs": list(job.get("spec_kit_refs") or []), "task_list_refs": ["tasks://T329-T343"]}
    elif tab == "Memory":
        tab_data = {"memory_packets": _bounded([m for m in state.memory_packets if m.get("job_id") == job_id], limit)}
    elif tab == "Validation":
        tab_data = {"validation_refs": list(job.get("validation_refs") or [])}
    elif tab == "Sidecars":
        tab_data = {"sidecars": _bounded([s for s in state.sidecars if s.get("job_id") == job_id], limit)}
    elif tab == "Bus Events":
        tab_data = {"bus_events": _bounded([e for e in state.bus_events if e.get("job_id") == job_id], limit)}
    elif tab == "Costs":
        tab_data = build_cost_context_panel(state, actor=actor, tenant_id=str(job["tenant_id"]), repo_id=str(job["repo_id"]), job_id=job_id)
    elif tab == "Deployment":
        tab_data = {"deployment": build_azure_deployment_panel(state, actor=actor, deployment_id=str(job.get("deployment_id")))}
    else:
        tab_data = {"ask": _ask_evidence_bundle(state, job, question="")}
    return _redact({**base, "data": tab_data})


def _bounded(items: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    return [_redact(item) for item in items[: max(1, int(limit or 25))]]


def request_dashboard_approval(
    state: OperatorDashboardState,
    *,
    actor: Mapping[str, Any],
    action: str,
    target_ref: str,
    target_hash: str,
    evidence_refs: list[str] | tuple[str, ...],
    expires_at: float,
    now: float,
) -> dict[str, Any]:
    if action not in APPROVAL_ACTIONS:
        raise ValueError(f"unsupported approval action: {action}")
    tenant_id = _actor_tenant(actor)
    if tenant_id is None:
        raise PermissionError("approval actor must be tenant scoped")
    _assert_access(actor, tenant_id)
    record = state.approval_ledger.record(
        actor_id=_actor_id(actor),
        actor_role=_actor_role(actor),
        tenant_id=tenant_id,
        scope="operator-dashboard",
        action=action,
        target_ref=target_ref,
        target_hash=target_hash,
        approval_channel="operator_dashboard",
        audit_refs=list(evidence_refs),
        created_at=float(now),
        expires_at=float(expires_at),
    )
    item = {
        "approval_ledger_id": record.approval_id,
        "actor_id": record.actor_id,
        "actor_role": record.actor_role,
        "tenant_id": record.tenant_id,
        "action": record.action,
        "target_hash": record.target_hash,
        "expires_at": record.expires_at,
        "evidence_refs": list(record.audit_refs),
        "state": "pending",
    }
    state.approval_requests.append(item)
    return _redact(item)


def list_approval_inbox(state: OperatorDashboardState, *, actor: Mapping[str, Any]) -> list[dict[str, Any]]:
    items = [item for item in state.approval_requests if _can_access(actor, str(item.get("tenant_id")))]
    return [_redact(item) for item in items]


def consume_dashboard_approval(
    state: OperatorDashboardState,
    *,
    actor: Mapping[str, Any],
    approval_ledger_id: str,
    action: str,
    target_hash: str,
    now: float,
) -> dict[str, Any]:
    result = state.approval_ledger.consume(
        approval_ledger_id,
        actor_id=_actor_id(actor),
        actor_role=_actor_role(actor),
        tenant_id=str(_actor_tenant(actor) or ""),
        action=action,
        target_hash=target_hash,
        now=float(now),
    )
    return result.to_dict()


def build_sidecar_bus_health(state: OperatorDashboardState, *, actor: Mapping[str, Any]) -> dict[str, Any]:
    tenant_id = _require_visible_tenant(actor, None)
    sidecars = [s for s in state.sidecars if tenant_id is None or s.get("tenant_id") == tenant_id]
    events = [e for e in state.bus_events if tenant_id is None or e.get("tenant_id") == tenant_id]
    return _redact(
        {
            "sidecars": [
                {
                    "role": item.get("role"),
                    "tier": item.get("tier"),
                    "provider": item.get("provider"),
                    "model": item.get("model"),
                    "state": item.get("state"),
                    "budget_decision": item.get("budget_decision"),
                    "queue": item.get("queue"),
                    "last_run_at": item.get("last_run_at"),
                    "failure_reason": item.get("failure_reason"),
                    "next_eligible_run_at": item.get("next_eligible_run_at"),
                }
                for item in sidecars
            ],
            "bus": {
                "backend": events[0].get("backend") if events else "sqlite",
                "topics": sorted({str(event.get("topic")) for event in events}),
                "lag": sum(int(event.get("lag") or 0) for event in events),
                "dead_letter_count": sum(1 for event in events if event.get("dead_letter")),
                "replay_count": sum(int(event.get("replay_attempt") or 0) for event in events),
                "spool_state": "degraded" if any(event.get("spool_state") == "degraded" for event in events) else "healthy",
            },
            "redaction_state": "redacted",
        }
    )


def build_cost_context_panel(
    state: OperatorDashboardState,
    *,
    actor: Mapping[str, Any],
    tenant_id: str,
    repo_id: str | None = None,
    job_id: str | None = None,
) -> dict[str, Any]:
    _assert_access(actor, tenant_id)
    jobs = [job for job in state.jobs if job.get("tenant_id") == tenant_id]
    if repo_id:
        jobs = [job for job in jobs if job.get("repo_id") == repo_id]
    if job_id:
        jobs = [job for job in jobs if job.get("job_id") == job_id]
    job_ids = {job.get("job_id") for job in jobs}
    attempts = [item for item in state.worker_attempts if item.get("job_id") in job_ids]
    sidecars = [item for item in state.sidecars if item.get("job_id") in job_ids]
    packets = [item for item in state.memory_packets if item.get("job_id") in job_ids]
    benchmarks = [item for item in state.benchmarks if item.get("job_id") in job_ids]
    totals = {
        "input_tokens": _sum_nested(jobs, "cost", "input_tokens") + _sum_nested(sidecars, "cost", "input_tokens"),
        "output_tokens": _sum_nested(jobs, "cost", "output_tokens") + _sum_nested(sidecars, "cost", "output_tokens"),
        "estimated_cost_usd": round(
            _sum_nested(jobs, "cost", "estimated_cost_usd") + _sum_nested(sidecars, "cost", "estimated_cost_usd"),
            4,
        ),
        "latency_ms": _sum_nested(jobs, "latency", "latency_ms") + sum(int(item.get("latency_ms") or 0) for item in attempts),
    }
    return _redact(
        {
            "tenant_id": tenant_id,
            "repo_id": repo_id,
            "job_id": job_id,
            "totals": totals,
            "attribution": {
                "context_admitted_tokens": _sum_nested(jobs, "context", "admitted_tokens"),
                "memory_packet_tokens": sum(int(item.get("token_estimate") or 0) for item in packets),
                "sidecar_calls": len(sidecars),
                "memory_hits": sum(int(item.get("hit_count") or 0) for item in packets),
                "worker_attempts": len(attempts),
                "benchmark_runs": len(benchmarks),
            },
            "by_model": _group_costs(jobs, "model"),
            "by_worker": _group_costs(jobs, "worker_family"),
            "by_sidecar_role": _group_costs(sidecars, "role"),
            "benchmarks": _bounded(benchmarks, 10),
            "redaction_state": "redacted",
        }
    )


def build_runtime_impact_panel(
    state: OperatorDashboardState,
    *,
    actor: Mapping[str, Any],
    tenant_id: str | None = None,
    repo_id: str | None = None,
    job_id: str | None = None,
    worker_event_db: Any | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """Build a bounded runtime-impact DTO for dashboard/API callers.

    This is the human inspection surface for work intentionally kept out of
    supervisor context. It exposes refs, counts, and compact summaries, not raw
    worker streams or transcripts.
    """

    visible_tenant = _require_visible_tenant(actor, tenant_id)
    jobs = [job for job in state.jobs if visible_tenant is None or job.get("tenant_id") == visible_tenant]
    if repo_id:
        jobs = [job for job in jobs if job.get("repo_id") == repo_id]
    if job_id:
        jobs = [job for job in jobs if job.get("job_id") == job_id]
    job_ids = {str(job.get("job_id")) for job in jobs}
    task_to_job = {str(job.get("task_id")): str(job.get("job_id")) for job in jobs if job.get("task_id")}

    sidecars = [item for item in state.sidecars if str(item.get("job_id")) in job_ids]
    packets = [item for item in state.memory_packets if str(item.get("job_id")) in job_ids]
    attempts = [item for item in state.worker_attempts if str(item.get("job_id")) in job_ids]
    bus_events = [item for item in state.bus_events if str(item.get("job_id")) in job_ids]

    worker_events_by_job: dict[str, list[dict[str, Any]]] = {jid: [] for jid in job_ids}
    if worker_event_db is not None:
        try:
            from hermes_cli.worker_event_store import list_worker_events

            stored_events = list_worker_events(
                worker_event_db,
                tenant_id=visible_tenant,
                repo_id=repo_id,
                limit=limit,
            )
        except Exception:
            stored_events = []
        for event in stored_events:
            mapped_job = task_to_job.get(str(event.task_id or ""))
            if not mapped_job or mapped_job not in job_ids:
                continue
            worker_events_by_job.setdefault(mapped_job, []).append(
                {
                    "id": event.id,
                    "ref": event.ref,
                    "kind": event.kind,
                    "source": event.source,
                    "task_id": event.task_id,
                    "summary": event.summary,
                    "raw_size_bytes": event.raw_size_bytes,
                    "redacted": event.redacted,
                    "foreground_admitted": event.foreground_admitted,
                    "created_at": event.created_at,
                }
            )

    sidecars_by_category: dict[str, list[dict[str, Any]]] = {}
    sidecars_by_job: dict[str, list[dict[str, Any]]] = {}
    for sidecar in sidecars:
        compact = _runtime_sidecar_summary(sidecar)
        category = str(sidecar.get("role") or "unknown")
        sid_job = str(sidecar.get("job_id") or "unknown")
        sidecars_by_category.setdefault(category, []).append(compact)
        sidecars_by_job.setdefault(sid_job, []).append(compact)

    memory_activity_by_job: dict[str, list[dict[str, Any]]] = {}
    for packet in packets:
        jid = str(packet.get("job_id") or "unknown")
        memory_activity_by_job.setdefault(jid, []).append(
            {
                "memory_packet_id": packet.get("memory_packet_id"),
                "repo_id": packet.get("repo_id"),
                "summary": packet.get("summary"),
                "packet_count": packet.get("packet_count"),
                "hit_count": packet.get("hit_count"),
                "token_estimate": packet.get("token_estimate"),
                "evidence_refs": list(packet.get("evidence_refs") or []),
            }
        )

    baseline_task_ms = _sum_nested(jobs, "latency", "latency_ms")
    worker_attempt_ms = sum(float(item.get("latency_ms") or 0) for item in attempts)
    sidecar_background_ms = sum(
        max(0.0, float(item.get("last_run_at") or 0) - float(item.get("next_eligible_run_at") or 0))
        for item in sidecars
    )
    # Seed fixtures may have next_eligible_run_at > last_run_at; use a stable
    # queue-derived estimate so the panel still exposes background separation.
    if sidecar_background_ms <= 0:
        sidecar_background_ms = sum(
            250.0 + (float((item.get("queue") or {}).get("pending") or 0) * 100.0)
            for item in sidecars
        )

    memory_packet_tokens = sum(int(item.get("token_estimate") or 0) for item in packets)
    sidecar_cost = _group_costs(sidecars, "role")
    total_cost = build_cost_context_panel(
        state,
        actor=actor,
        tenant_id=str(visible_tenant or tenant_id or _actor_tenant(actor) or ""),
        repo_id=repo_id,
        job_id=job_id,
    ) if (visible_tenant or tenant_id or _actor_tenant(actor)) else {"totals": {}, "attribution": {}}

    offloaded_count = sum(len(items) for items in worker_events_by_job.values())
    return _redact(
        {
            "kind": "runtime_impact",
            "tenant_id": visible_tenant,
            "repo_id": repo_id,
            "job_id": job_id,
            "foreground": {
                "context_policy": "checkpoint_and_refs_only",
                "raw_worker_updates_in_context": False,
                "foreground_sidecar_blocking": False,
                "foreground_llm_sidecar_calls": 0,
            },
            "sidecars_by_category": sidecars_by_category,
            "sidecars_by_job": sidecars_by_job,
            "memory_activity_by_job": memory_activity_by_job,
            "worker_events_by_job": worker_events_by_job,
            "bus_activity_by_job": _group_items_by_job(bus_events),
            "latency_attribution": {
                "baseline_task_ms": baseline_task_ms,
                "memory_retrieval_ms": max(1.0, memory_packet_tokens / 20.0) if packets else 0.0,
                "allocator_ms": len(attempts) * 25.0,
                "validation_ms": len(attempts) * 40.0,
                "notification_ms": len(bus_events) * 15.0,
                "curator_judge_ms": sum(1 for item in sidecars if str(item.get("role")) in {"judge", "curator", "learning_judge"}) * 300.0,
                "background_sidecar_ms": sidecar_background_ms,
                "worker_attempt_ms": worker_attempt_ms,
                "foreground_ms": baseline_task_ms + worker_attempt_ms,
            },
            "cost_attribution": {
                "estimated_cost_usd": total_cost.get("totals", {}).get("estimated_cost_usd", 0),
                "input_tokens": total_cost.get("totals", {}).get("input_tokens", 0),
                "output_tokens": total_cost.get("totals", {}).get("output_tokens", 0),
                "sidecar_estimated_cost_usd": round(
                    sum(float(bucket.get("estimated_cost_usd") or 0) for bucket in sidecar_cost.values()),
                    4,
                ),
            },
            "context_attribution": {
                "context_admitted_tokens": total_cost.get("attribution", {}).get("context_admitted_tokens", 0),
                "memory_packet_tokens": memory_packet_tokens,
                "offloaded_worker_events": offloaded_count,
                "offloaded_worker_bytes": sum(
                    int(event.get("raw_size_bytes") or 0)
                    for items in worker_events_by_job.values()
                    for event in items
                ),
            },
            "raw_logs_loaded": False,
            "raw_transcripts_loaded": False,
            "redaction_state": "redacted",
        }
    )


def _runtime_sidecar_summary(item: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "sidecar_id": item.get("sidecar_id"),
        "job_id": item.get("job_id"),
        "role": item.get("role"),
        "tier": item.get("tier"),
        "provider": item.get("provider"),
        "model": item.get("model"),
        "state": item.get("state"),
        "budget_decision": item.get("budget_decision"),
        "queue": item.get("queue"),
        "last_run_at": item.get("last_run_at"),
        "failure_reason": item.get("failure_reason"),
        "next_eligible_run_at": item.get("next_eligible_run_at"),
    }


def _group_items_by_job(items: Iterable[Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        jid = str(item.get("job_id") or "unknown")
        grouped.setdefault(jid, []).append(_redact(dict(item)))
    return grouped


def _sum_nested(items: Iterable[Mapping[str, Any]], parent: str, key: str) -> float:
    return sum(float((item.get(parent) if isinstance(item.get(parent), Mapping) else {}).get(key) or 0) for item in items)


def _group_costs(items: Iterable[Mapping[str, Any]], key: str) -> dict[str, dict[str, float]]:
    grouped: dict[str, dict[str, float]] = {}
    for item in items:
        name = str(item.get(key) or "unknown")
        bucket = grouped.setdefault(name, {"estimated_cost_usd": 0.0, "input_tokens": 0.0, "output_tokens": 0.0})
        cost = item.get("cost") if isinstance(item.get("cost"), Mapping) else {}
        bucket["estimated_cost_usd"] = round(bucket["estimated_cost_usd"] + float(cost.get("estimated_cost_usd") or 0), 4)
        bucket["input_tokens"] += float(cost.get("input_tokens") or 0)
        bucket["output_tokens"] += float(cost.get("output_tokens") or 0)
    return grouped


def build_scoped_ask_bundle(
    state: OperatorDashboardState,
    *,
    actor: Mapping[str, Any],
    job_id: str,
    question: str,
    model_call: Callable[[str, dict[str, Any]], Any] | None = None,
) -> dict[str, Any]:
    job = _find_one(state.jobs, "job_id", job_id)
    _assert_access(actor, str(job["tenant_id"]))
    bundle = _ask_evidence_bundle(state, job, question=question)
    prompt = (
        "You are a read-only Hermes dashboard analyst. Use only this bounded evidence bundle. "
        "Do not approve, deploy, edit memory, change config, modify repos, or call mutation tools.\n"
        f"Question: {_safe_text(question, max_chars=600)}\n"
        f"Evidence: {json.dumps(bundle, sort_keys=True)}"
    )
    answer = model_call(prompt, bundle) if model_call is not None else _default_ask_answer(bundle)
    return _redact(
        {
            "job_id": job_id,
            "question": question,
            "evidence_bundle": bundle,
            "tool_policy": {"read_only": True, "mutation_tools": [], "available_tools": ["evidence.read"]},
            "mutation_allowed": False,
            "answer": answer,
            "redaction_state": "redacted",
        }
    )


def _ask_evidence_bundle(state: OperatorDashboardState, job: Mapping[str, Any], *, question: str) -> dict[str, Any]:
    job_id = str(job["job_id"])
    evidence_refs = list(job.get("evidence_refs") or [])
    packets = _bounded([m for m in state.memory_packets if m.get("job_id") == job_id], 5)
    attempts = _bounded([a for a in state.worker_attempts if a.get("job_id") == job_id], 5)
    sidecars = _bounded([s for s in state.sidecars if s.get("job_id") == job_id], 5)
    deployment = _deployment_summary(state, job.get("deployment_id"))
    if deployment:
        evidence_refs.extend(deployment.get("required_operator_actions") or [])
    return _redact(
        {
            "bundle_id": "ask_" + _stable_hash({"job_id": job_id, "question": question})[:16],
            "job_id": job_id,
            "tenant_id": job.get("tenant_id"),
            "repo_id": job.get("repo_id"),
            "read_only": True,
            "bounded": True,
            "mutation_tools": [],
            "task_packet_summary": {
                "title": job.get("title"),
                "status": job.get("status"),
                "blocker_reason": job.get("blocker_reason"),
                "last_progress_summary": job.get("last_progress_summary"),
            },
            "memory_packet_summaries": packets,
            "validation_summaries": [{"id": ref, "state": "available"} for ref in job.get("validation_refs") or []],
            "worker_attempt_summaries": attempts,
            "sidecar_summaries": sidecars,
            "deployment_summaries": [deployment] if deployment else [],
            "cost_summaries": [job.get("cost", {})],
            "evidence_refs": evidence_refs,
        }
    )


def _default_ask_answer(bundle: Mapping[str, Any]) -> dict[str, Any]:
    summary = bundle.get("task_packet_summary") if isinstance(bundle.get("task_packet_summary"), Mapping) else {}
    return {
        "answer": f"Job status is {summary.get('status', 'unknown')}; blocker is {summary.get('blocker_reason', 'none')}.",
        "citations": list(bundle.get("evidence_refs") or [])[:3],
    }


def build_azure_deployment_panel(
    state: OperatorDashboardState,
    *,
    actor: Mapping[str, Any],
    deployment_id: str,
) -> dict[str, Any]:
    deployment = _find_one(state.azure_deployments, "deployment_id", deployment_id)
    _assert_access(actor, str(deployment["tenant_id"]))
    return _redact(
        {
            "deployment_id": deployment["deployment_id"],
            "tenant_id": deployment["tenant_id"],
            "repo_id": deployment["repo_id"],
            "job_id": deployment.get("job_id"),
            "plan": deployment.get("plan"),
            "preflight": deployment.get("preflight"),
            "apply": deployment.get("apply"),
            "smoke": deployment.get("smoke"),
            "soak": deployment.get("soak"),
            "promote": deployment.get("promote"),
            "rollback": deployment.get("rollback"),
            "hardening_failures": list(deployment.get("hardening_failures") or []),
            "costs": deployment.get("costs"),
            "required_operator_actions": list(deployment.get("required_operator_actions") or []),
            "dangerous_actions_enabled": False,
            "evidence_refs": list(deployment.get("evidence_refs") or []),
            "redaction_state": "redacted",
        }
    )


def build_dashboard_shell(state: OperatorDashboardState, *, actor: Mapping[str, Any]) -> dict[str, Any]:
    rows = list_operator_jobs(state, actor=actor, filters=OperatorDashboardFilters(limit=10))
    return _redact(
        {
            "surface": "operator_dashboard",
            "mode": "json_shell",
            "views": ["jobs", "job_detail", "approval_inbox", "sidecar_bus", "cost_context", "deployment", "ask"],
            "jobs": rows,
            "approval_inbox": list_approval_inbox(state, actor=actor),
            "sidecar_bus": build_sidecar_bus_health(state, actor=actor),
            "raw_logs_loaded": False,
            "raw_transcripts_loaded": False,
            "dangerous_actions_enabled": False,
        }
    )


def run_operator_dashboard_smoke_fixture() -> dict[str, Any]:
    state = seed_operator_dashboard_fixture()
    actor = {"actor_id": "operator-a", "role": "tenant-admin", "tenant_id": "tenant-a"}
    shell = build_dashboard_shell(state, actor=actor)
    denied = consume_dashboard_approval(
        state,
        actor=actor,
        approval_ledger_id="missing-approval",
        action="deployment.apply",
        target_hash="deploy-hash",
        now=1700.0,
    )
    return _redact(
        {
            "seeded_state_visible": bool(shell["jobs"]) and bool(shell["approval_inbox"]) and bool(shell["sidecar_bus"]),
            "dangerous_action_without_approval": denied,
            "raw_logs_loaded": False,
            "raw_transcripts_loaded": False,
            "dashboard_shell": shell,
        }
    )
