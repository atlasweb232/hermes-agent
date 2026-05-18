"""Goal-aware worker allocation primitives.

The allocator is deliberately workflow-agnostic. A `/goal` turn, dashboard task,
API task, or manual supervisor task can all use the same allocation state and
worker health rules.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


PLAN_STATUSES = {"active", "completed", "paused", "blocked", "exhausted", "cancelled"}
ATTEMPT_STATUSES = {
    "success",
    "failed",
    "timed_out",
    "empty_output",
    "quota_exhausted",
    "auth_failed",
    "network_degraded",
    "blocked",
    "cancelled",
}
VALIDATION_STATUSES = {"passed", "failed", "skipped", "not_applicable"}
PAUSE_STATUSES = {"quota_exhausted", "auth_failed", "network_degraded"}
DEGRADED_STATUSES = {
    "failed",
    "timed_out",
    "empty_output",
    "quota_exhausted",
    "auth_failed",
    "network_degraded",
    "blocked",
}


def _now() -> float:
    return time.time()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def _allocation_key(session_id: str, task_id: str) -> str:
    return f"allocation:{session_id}:{task_id}"


def _worker_health_key(worker_id: str) -> str:
    return f"worker_health:{worker_id}"


def _clean_str_list(values: List[str], *, field_name: str) -> List[str]:
    if not isinstance(values, list):
        raise ValueError(f"{field_name} must be a list")
    cleaned = [str(value).strip() for value in values if str(value).strip()]
    return cleaned


@dataclass
class WorkerAllocationPlan:
    task_id: str
    session_id: str
    objective: str
    candidate_workers: List[str]
    primary_worker: str
    fallback_order: List[str] = field(default_factory=list)
    version: str = "2026.05.goal-allocation.v1"
    allocation_id: str = field(default_factory=lambda: _new_id("alloc"))
    goal_key: str = ""
    tenant_id: Optional[str] = None
    repo_id: Optional[str] = None
    memory_packet_id: Optional[str] = None
    latency_budget_seconds: float = 120.0
    per_worker_timeout_seconds: float = 30.0
    max_attempts: int = 3
    retry_same_worker: int = 0
    cooldown_seconds: float = 300.0
    retry_after_seconds: float = 300.0
    validation_required: bool = True
    status: str = "active"
    created_at: float = field(default_factory=_now)
    updated_at: float = field(default_factory=_now)

    def __post_init__(self) -> None:
        self.task_id = str(self.task_id).strip()
        self.session_id = str(self.session_id).strip()
        self.objective = str(self.objective).strip()
        self.candidate_workers = _clean_str_list(self.candidate_workers, field_name="candidate_workers")
        self.fallback_order = _clean_str_list(self.fallback_order, field_name="fallback_order")
        self.primary_worker = str(self.primary_worker).strip()
        if not self.task_id:
            raise ValueError("task_id is required")
        if not self.session_id:
            raise ValueError("session_id is required")
        if not self.objective:
            raise ValueError("objective is required")
        if not self.candidate_workers:
            raise ValueError("candidate_workers must not be empty")
        if not self.primary_worker:
            raise ValueError("primary_worker is required")
        if self.primary_worker not in self.candidate_workers:
            raise ValueError("primary_worker must be in candidate_workers")
        for worker_id in self.fallback_order:
            if worker_id not in self.candidate_workers:
                raise ValueError("fallback_order workers must be in candidate_workers")
        if self.latency_budget_seconds <= 0:
            raise ValueError("latency_budget_seconds must be positive")
        if self.per_worker_timeout_seconds <= 0:
            raise ValueError("per_worker_timeout_seconds must be positive")
        if self.max_attempts <= 0:
            raise ValueError("max_attempts must be positive")
        if self.retry_same_worker < 0:
            raise ValueError("retry_same_worker must be non-negative")
        if self.cooldown_seconds < 0:
            raise ValueError("cooldown_seconds must be non-negative")
        if self.retry_after_seconds < 0:
            raise ValueError("retry_after_seconds must be non-negative")
        if not isinstance(self.validation_required, bool):
            raise ValueError("validation_required must be boolean")
        if self.status not in PLAN_STATUSES:
            raise ValueError(f"invalid allocation status: {self.status}")
        if not self.goal_key:
            self.goal_key = f"goal:{self.session_id}"

    @property
    def worker_order(self) -> List[str]:
        ordered = [self.primary_worker]
        for worker_id in self.fallback_order + self.candidate_workers:
            if worker_id not in ordered:
                ordered.append(worker_id)
        return ordered

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WorkerAllocationPlan":
        return cls(**dict(data))

    @classmethod
    def from_json(cls, raw: str) -> "WorkerAllocationPlan":
        return cls.from_dict(json.loads(raw))


@dataclass
class WorkerAttemptResult:
    allocation_id: str
    worker_id: str
    route: str
    status: str
    attempt_id: str = field(default_factory=lambda: _new_id("attempt"))
    started_at: float = field(default_factory=_now)
    finished_at: float = field(default_factory=_now)
    duration_seconds: float = 0.0
    stdout_excerpt: str = ""
    stderr_excerpt: str = ""
    artifact_refs: List[str] = field(default_factory=list)
    error_signature: str = ""
    validation_status: str = "skipped"
    fallback_allowed: bool = True
    recovery_hint: str = ""

    def __post_init__(self) -> None:
        self.allocation_id = str(self.allocation_id).strip()
        self.worker_id = str(self.worker_id).strip()
        self.route = str(self.route).strip()
        self.status = str(self.status).strip()
        if not self.allocation_id:
            raise ValueError("allocation_id is required")
        if not self.worker_id:
            raise ValueError("worker_id is required")
        if not self.route:
            raise ValueError("route is required")
        if self.status not in ATTEMPT_STATUSES:
            raise ValueError(f"invalid attempt status: {self.status}")
        if self.validation_status not in VALIDATION_STATUSES:
            raise ValueError(f"invalid validation status: {self.validation_status}")
        if self.duration_seconds < 0:
            raise ValueError("duration_seconds must be non-negative")
        if not isinstance(self.fallback_allowed, bool):
            raise ValueError("fallback_allowed must be boolean")
        self.artifact_refs = _clean_str_list(self.artifact_refs, field_name="artifact_refs")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WorkerAttemptResult":
        return cls(**dict(data))

    @classmethod
    def from_json(cls, raw: str) -> "WorkerAttemptResult":
        return cls.from_dict(json.loads(raw))


@dataclass
class WorkerHealth:
    worker_id: str
    provider: str = ""
    last_success_at: float = 0.0
    last_failure_at: float = 0.0
    failure_count: int = 0
    empty_output_count: int = 0
    timeout_count: int = 0
    quota_exhausted_until: float = 0.0
    network_degraded_until: float = 0.0
    auth_failed_until: float = 0.0
    cooldown_until: float = 0.0
    last_error_signature: str = ""
    confidence: float = 1.0
    updated_at: float = field(default_factory=_now)

    def __post_init__(self) -> None:
        self.worker_id = str(self.worker_id).strip()
        if not self.worker_id:
            raise ValueError("worker_id is required")
        if self.failure_count < 0 or self.empty_output_count < 0 or self.timeout_count < 0:
            raise ValueError("health counters must be non-negative")
        if self.confidence < 0 or self.confidence > 1:
            raise ValueError("confidence must be between 0 and 1")

    def is_available(self, now: Optional[float] = None) -> bool:
        timestamp = _now() if now is None else now
        return not any(
            until and until > timestamp
            for until in (
                self.quota_exhausted_until,
                self.network_degraded_until,
                self.auth_failed_until,
                self.cooldown_until,
            )
        )

    def unavailable_until(self) -> float:
        return max(
            self.quota_exhausted_until,
            self.network_degraded_until,
            self.auth_failed_until,
            self.cooldown_until,
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WorkerHealth":
        return cls(**dict(data))

    @classmethod
    def from_json(cls, raw: str) -> "WorkerHealth":
        return cls.from_dict(json.loads(raw))


@dataclass
class AllocationDecision:
    action: str
    worker_id: Optional[str] = None
    reason: str = ""
    retry_after_seconds: float = 0.0
    remaining_latency_budget_seconds: float = 0.0
    attempts_used: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def save_allocation_plan(db: Any, plan: WorkerAllocationPlan) -> None:
    plan.updated_at = _now()
    db.set_meta(_allocation_key(plan.session_id, plan.task_id), plan.to_json())


def load_allocation_plan(db: Any, session_id: str, task_id: str) -> Optional[WorkerAllocationPlan]:
    raw = db.get_meta(_allocation_key(session_id, task_id))
    if not raw:
        return None
    return WorkerAllocationPlan.from_json(raw)


def save_worker_health(db: Any, health: WorkerHealth) -> None:
    health.updated_at = _now()
    db.set_meta(_worker_health_key(health.worker_id), health.to_json())


def load_worker_health(db: Any, worker_id: str) -> Optional[WorkerHealth]:
    raw = db.get_meta(_worker_health_key(worker_id))
    if not raw:
        return None
    return WorkerHealth.from_json(raw)


def update_worker_health_from_attempt(
    health: WorkerHealth,
    attempt: WorkerAttemptResult,
    *,
    cooldown_seconds: float,
    now: Optional[float] = None,
) -> WorkerHealth:
    timestamp = _now() if now is None else now
    health.updated_at = timestamp
    if attempt.status == "success":
        health.last_success_at = timestamp
        health.confidence = min(1.0, health.confidence + 0.05)
        return health

    if attempt.status in DEGRADED_STATUSES:
        health.last_failure_at = timestamp
        health.failure_count += 1
        health.last_error_signature = attempt.error_signature
        health.confidence = max(0.0, health.confidence - 0.1)
        if attempt.status == "empty_output":
            health.empty_output_count += 1
        if attempt.status == "timed_out":
            health.timeout_count += 1
        if attempt.status == "quota_exhausted":
            health.quota_exhausted_until = max(health.quota_exhausted_until, timestamp + cooldown_seconds)
        elif attempt.status == "auth_failed":
            health.auth_failed_until = max(health.auth_failed_until, timestamp + cooldown_seconds)
        elif attempt.status == "network_degraded":
            health.network_degraded_until = max(health.network_degraded_until, timestamp + cooldown_seconds)
        elif attempt.status in {"timed_out", "empty_output", "failed"}:
            health.cooldown_until = max(health.cooldown_until, timestamp + cooldown_seconds)
    return health


def choose_next_worker(
    plan: WorkerAllocationPlan,
    attempts: List[WorkerAttemptResult],
    health_by_worker: Optional[Dict[str, WorkerHealth]] = None,
    *,
    now: Optional[float] = None,
) -> AllocationDecision:
    timestamp = _now() if now is None else now
    health_by_worker = health_by_worker or {}
    attempts_for_plan = [attempt for attempt in attempts if attempt.allocation_id == plan.allocation_id]
    attempts_used = len(attempts_for_plan)
    consumed = sum(max(0.0, attempt.duration_seconds) for attempt in attempts_for_plan)
    remaining = max(0.0, plan.latency_budget_seconds - consumed)

    if plan.status != "active":
        return AllocationDecision(
            action="blocked",
            reason=f"allocation is {plan.status}",
            remaining_latency_budget_seconds=remaining,
            attempts_used=attempts_used,
        )
    if any(attempt.status == "success" for attempt in attempts_for_plan):
        return AllocationDecision(
            action="complete",
            reason="successful worker attempt already recorded",
            remaining_latency_budget_seconds=remaining,
            attempts_used=attempts_used,
        )
    if attempts_used >= plan.max_attempts:
        return AllocationDecision(
            action="pause",
            reason="max attempts exhausted",
            retry_after_seconds=plan.retry_after_seconds,
            remaining_latency_budget_seconds=remaining,
            attempts_used=attempts_used,
        )
    if remaining < plan.per_worker_timeout_seconds:
        return AllocationDecision(
            action="pause",
            reason="latency budget exhausted",
            retry_after_seconds=plan.retry_after_seconds,
            remaining_latency_budget_seconds=remaining,
            attempts_used=attempts_used,
        )

    skipped_until: List[float] = []
    for worker_id in plan.worker_order:
        worker_attempts = [attempt for attempt in attempts_for_plan if attempt.worker_id == worker_id]
        degraded_attempts = [attempt for attempt in worker_attempts if attempt.status in DEGRADED_STATUSES]
        if degraded_attempts and not degraded_attempts[-1].fallback_allowed:
            continue
        if len(degraded_attempts) > plan.retry_same_worker:
            continue

        health = health_by_worker.get(worker_id)
        if health and not health.is_available(timestamp):
            skipped_until.append(health.unavailable_until())
            continue

        return AllocationDecision(
            action="dispatch",
            worker_id=worker_id,
            reason="worker selected",
            remaining_latency_budget_seconds=remaining,
            attempts_used=attempts_used,
        )

    retry_after = plan.retry_after_seconds
    future_skips = [until for until in skipped_until if until > timestamp]
    if future_skips:
        retry_after = max(0.0, min(future_skips) - timestamp)
    return AllocationDecision(
        action="pause",
        reason="no healthy fallback worker available",
        retry_after_seconds=retry_after,
        remaining_latency_budget_seconds=remaining,
        attempts_used=attempts_used,
    )
