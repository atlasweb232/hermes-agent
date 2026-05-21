"""Deterministic platform hardening helpers.

The helpers in this module are local control-plane primitives. They do not
start sidecars, call live providers, mutate deployments, or enable policy
enforcement by default.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
import copy
import hashlib
import json
import re
from typing import Any, Mapping


SECRET_RE = re.compile(
    r"(?i)(sk-[a-z0-9_-]{8,}|api[_-]?key|secret|password|token|raw[_-]?(stdout|stderr|log|transcript))"
)
RAW_STREAM_FIELDS = {
    "raw_stdout",
    "raw_stderr",
    "raw_logs",
    "watch_tail",
    "log_tail",
    "terminal_tail",
    "stdout_tail",
    "stderr_tail",
}
REQUIRED_WORKER_FAMILIES = ("claude", "codex", "deepseek", "browser_tinyfish", "generic")


def _stable_hash(value: Any) -> str:
    if isinstance(value, str):
        raw = value
    else:
        raw = json.dumps(value, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _redact(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(k): _redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact(item) for item in value)
    if isinstance(value, str):
        if SECRET_RE.search(value):
            return "[REDACTED]"
        return value[:512]
    return value


def _copy_mapping(value: Mapping[str, Any] | None) -> dict[str, Any]:
    return copy.deepcopy(dict(value or {}))


@dataclass(frozen=True)
class ApprovalRecord:
    approval_id: str
    actor_id: str
    actor_role: str
    tenant_id: str
    scope: str
    action: str
    target_ref_hash: str
    target_hash: str
    created_at: float
    expires_at: float
    approval_channel: str
    audit_refs: tuple[str, ...]
    single_use: bool = True
    consumed_at: float | None = None
    consumed_audit_ref: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "approval_id": self.approval_id,
            "actor_id": self.actor_id,
            "actor_role": self.actor_role,
            "tenant_id": self.tenant_id,
            "scope": self.scope,
            "action": self.action,
            "target_ref_hash": self.target_ref_hash,
            "target_hash": self.target_hash,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "approval_channel": self.approval_channel,
            "audit_refs": list(self.audit_refs),
            "single_use": self.single_use,
            "consumed_at": self.consumed_at,
            "consumed_audit_ref": self.consumed_audit_ref,
            "immutable": True,
        }


@dataclass(frozen=True)
class ApprovalConsumeResult:
    allowed: bool
    reason: str
    approval_ref: str | None = None
    audit_ref: str | None = None
    fail_closed: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ApprovalLedger:
    """In-memory immutable approval ledger for local tests and JSON inspection."""

    def __init__(self) -> None:
        self._records: dict[str, ApprovalRecord] = {}
        self._audit_events: list[dict[str, Any]] = []

    def record(
        self,
        *,
        actor_id: str,
        actor_role: str,
        tenant_id: str,
        scope: str,
        action: str,
        target_ref: str,
        target_hash: str,
        approval_channel: str,
        audit_refs: list[str] | tuple[str, ...],
        created_at: float,
        expires_at: float,
        single_use: bool = True,
    ) -> ApprovalRecord:
        approval_id = "approval_" + _stable_hash(
            {
                "actor_id": actor_id,
                "actor_role": actor_role,
                "tenant_id": tenant_id,
                "scope": scope,
                "action": action,
                "target_ref": target_ref,
                "target_hash": target_hash,
                "created_at": created_at,
                "expires_at": expires_at,
            }
        )[:20]
        record = ApprovalRecord(
            approval_id=approval_id,
            actor_id=actor_id,
            actor_role=actor_role,
            tenant_id=tenant_id,
            scope=scope,
            action=action,
            target_ref_hash=_stable_hash(target_ref),
            target_hash=target_hash,
            created_at=float(created_at),
            expires_at=float(expires_at),
            approval_channel=approval_channel,
            audit_refs=tuple(str(ref) for ref in audit_refs),
            single_use=single_use,
        )
        self._records[approval_id] = record
        self._audit_events.append(
            {"event": "recorded", "approval_id": approval_id, "audit_ref": f"audit://approval/{approval_id}/record"}
        )
        return record

    def consume(
        self,
        approval_id: str,
        *,
        actor_id: str,
        actor_role: str,
        tenant_id: str,
        action: str,
        target_hash: str,
        now: float,
    ) -> ApprovalConsumeResult:
        record = self._records.get(approval_id)
        if record is None:
            return ApprovalConsumeResult(False, "approval_not_found")
        checks = (
            ("actor_id_mismatch", record.actor_id == actor_id),
            ("actor_role_mismatch", record.actor_role == actor_role),
            ("tenant_id_mismatch", record.tenant_id == tenant_id),
            ("action_mismatch", record.action == action),
            ("target_hash_mismatch", record.target_hash == target_hash),
            ("approval_expired", float(now) <= record.expires_at),
            ("approval_already_consumed", not (record.single_use and record.consumed_at is not None)),
        )
        for reason, passed in checks:
            if not passed:
                self._audit_events.append({"event": "denied", "approval_id": approval_id, "reason": reason})
                return ApprovalConsumeResult(False, reason)
        audit_ref = f"audit://approval/{approval_id}/consume"
        self._records[approval_id] = replace(record, consumed_at=float(now), consumed_audit_ref=audit_ref)
        self._audit_events.append({"event": "consumed", "approval_id": approval_id, "audit_ref": audit_ref})
        return ApprovalConsumeResult(True, "approved", approval_ref=f"approval://{approval_id}", audit_ref=audit_ref)

    def inspect_json(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "records": [_redact(record.to_dict()) for record in self._records.values()],
            "audit_events": list(self._audit_events),
        }


@dataclass(frozen=True)
class EffectiveRuntimeProfile:
    tenant_id: str
    repo_id: str
    feature_toggles: dict[str, Any]
    sidecar_tiers: dict[str, Any]
    tenant_policy: dict[str, Any]
    repo_policy: dict[str, Any]
    toolset_profile: dict[str, Any]
    deployment_profile: dict[str, Any]
    worker_health: dict[str, Any]
    budgets: dict[str, Any]
    memory_retrieval_mode: str
    decisions: dict[str, Any]
    read_only: bool = True

    def to_dict(self) -> dict[str, Any]:
        return _redact(asdict(self))

    def with_update(self, **_: Any) -> "EffectiveRuntimeProfile":
        return self


def resolve_effective_runtime_profile(
    *,
    tenant_id: str,
    repo_id: str,
    feature_toggles: Mapping[str, Any] | None = None,
    sidecar_tiers: Mapping[str, Any] | None = None,
    tenant_policy: Mapping[str, Any] | None = None,
    repo_policy: Mapping[str, Any] | None = None,
    toolset_profile: Mapping[str, Any] | None = None,
    deployment_profile: Mapping[str, Any] | None = None,
    worker_health: Mapping[str, Any] | None = None,
    budgets: Mapping[str, Any] | None = None,
    memory_retrieval_mode: str = "approved_only",
) -> EffectiveRuntimeProfile:
    features = _copy_mapping(feature_toggles)
    tiers = _copy_mapping(sidecar_tiers)
    tenant = _copy_mapping(tenant_policy)
    repo = _copy_mapping(repo_policy)
    toolset = _copy_mapping(toolset_profile)
    deployment = _copy_mapping(deployment_profile)
    health = _copy_mapping(worker_health)
    budget_state = _copy_mapping(budgets)
    deployment_allowed = bool(tenant.get("deployment_allowed", True)) and bool(repo.get("deployment_allowed", True))
    decisions: dict[str, Any] = {
        "deployment_allowed": {
            "enabled": deployment_allowed,
            "explanation": "tenant_policy and repo_policy allow deployment"
            if deployment_allowed
            else "tenant_policy or repo_policy blocks deployment",
        },
        "memory_retrieval": {
            "enabled": memory_retrieval_mode != "disabled",
            "explanation": f"memory_retrieval_mode={memory_retrieval_mode}",
        },
    }
    for feature_id, enabled in features.items():
        decisions[f"feature.{feature_id}"] = {
            "enabled": bool(enabled),
            "explanation": "runtime feature toggle enabled" if enabled else "runtime feature toggle disabled",
        }
    for role, tier in tiers.items():
        decisions[f"sidecar.{role}"] = {
            "enabled": str(tier) != "disabled",
            "explanation": f"sidecar tier resolved to {tier}",
        }
    return EffectiveRuntimeProfile(
        tenant_id=tenant_id,
        repo_id=repo_id,
        feature_toggles=features,
        sidecar_tiers=tiers,
        tenant_policy=tenant,
        repo_policy=repo,
        toolset_profile=toolset,
        deployment_profile=deployment,
        worker_health=health,
        budgets=budget_state,
        memory_retrieval_mode=memory_retrieval_mode,
        decisions=decisions,
    )


@dataclass(frozen=True)
class CanonicalBusEnvelope:
    event_id: str
    event_type: str
    tenant_id: str
    repo_id: str
    source_subsystem: str
    idempotency_key: str
    partition_key: str
    created_at: float
    schema_version: int
    redaction_state: str
    payload_ref: str | None = None
    bounded_payload: dict[str, Any] = field(default_factory=dict)
    replay_attempt: int = 0
    dead_letter_reason: str | None = None
    adapter: str = "sqlite"

    def to_dict(self) -> dict[str, Any]:
        return _redact(asdict(self))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CanonicalBusEnvelope":
        return cls(
            event_id=str(data["event_id"]),
            event_type=str(data["event_type"]),
            tenant_id=str(data["tenant_id"]),
            repo_id=str(data["repo_id"]),
            source_subsystem=str(data["source_subsystem"]),
            idempotency_key=str(data["idempotency_key"]),
            partition_key=str(data["partition_key"]),
            created_at=float(data["created_at"]),
            schema_version=int(data.get("schema_version", 1)),
            redaction_state=str(data.get("redaction_state", "redacted")),
            payload_ref=data.get("payload_ref"),
            bounded_payload=_copy_mapping(data.get("bounded_payload")),
            replay_attempt=int(data.get("replay_attempt", 0)),
            dead_letter_reason=data.get("dead_letter_reason"),
            adapter=str(data.get("adapter", "sqlite")),
        )

    def consumer_key(self, consumer_id: str) -> str:
        return f"{consumer_id}:{self.event_id}:{self.idempotency_key}"


def create_bus_envelope(
    *,
    event_type: str,
    tenant_id: str,
    repo_id: str,
    source_subsystem: str,
    idempotency_key: str,
    partition_key: str,
    created_at: float,
    adapter: str,
    payload: Mapping[str, Any] | None = None,
    payload_ref: str | None = None,
) -> CanonicalBusEnvelope:
    if payload_ref is None and payload is None:
        raise ValueError("payload or payload_ref is required")
    event_id = "evt_" + _stable_hash(
        {
            "event_type": event_type,
            "tenant_id": tenant_id,
            "repo_id": repo_id,
            "source_subsystem": source_subsystem,
            "idempotency_key": idempotency_key,
            "partition_key": partition_key,
            "created_at": created_at,
            "adapter": adapter,
        }
    )[:24]
    return CanonicalBusEnvelope(
        event_id=event_id,
        event_type=event_type,
        tenant_id=tenant_id,
        repo_id=repo_id,
        source_subsystem=source_subsystem,
        idempotency_key=idempotency_key,
        partition_key=partition_key,
        created_at=float(created_at),
        schema_version=1,
        redaction_state="redacted",
        payload_ref=payload_ref,
        bounded_payload=_copy_mapping(payload) if payload_ref is None else {},
        adapter=adapter,
    )


def redrive_event(event: CanonicalBusEnvelope, *, reason: str) -> CanonicalBusEnvelope:
    return replace(event, replay_attempt=event.replay_attempt + 1, dead_letter_reason=None)


def dead_letter_event(event: CanonicalBusEnvelope, *, reason: str) -> CanonicalBusEnvelope:
    return replace(event, dead_letter_reason=str(reason)[:160])


@dataclass(frozen=True)
class BudgetLimit:
    tenant_cost: float
    task_cost: float
    daily_cost: float
    tenant_tokens: int
    task_tokens: int


@dataclass(frozen=True)
class BudgetUsage:
    tenant_cost: float = 0
    task_cost: float = 0
    daily_cost: float = 0
    tenant_tokens: int = 0
    task_tokens: int = 0


@dataclass(frozen=True)
class SidecarBudgetRequest:
    tenant_id: str
    task_id: str
    sidecar_role: str
    llm_backed: bool
    estimated_tokens: int
    estimated_cost: float
    escalation_reason: str
    exact_memory_hit: bool = False
    degrade_tier: str | None = None


@dataclass(frozen=True)
class SidecarBudgetDecision:
    allowed: bool
    status: str
    reasons: list[str]
    degraded_to: str | None = None
    foreground_blocking: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_sidecar_budget(
    request: SidecarBudgetRequest,
    *,
    limits: BudgetLimit,
    usage: BudgetUsage,
) -> SidecarBudgetDecision:
    if request.exact_memory_hit and not request.llm_backed:
        return SidecarBudgetDecision(True, "allowed_programmatic", [])
    reasons: list[str] = []
    if usage.tenant_cost + request.estimated_cost > limits.tenant_cost:
        reasons.append("tenant_cost")
    if usage.task_cost + request.estimated_cost > limits.task_cost:
        reasons.append("task_cost")
    if usage.daily_cost + request.estimated_cost > limits.daily_cost:
        reasons.append("daily_cost")
    if usage.tenant_tokens + request.estimated_tokens > limits.tenant_tokens:
        reasons.append("tenant_tokens")
    if usage.task_tokens + request.estimated_tokens > limits.task_tokens:
        reasons.append("task_tokens")
    if not reasons:
        return SidecarBudgetDecision(True, "allowed", [])
    if request.degrade_tier:
        return SidecarBudgetDecision(False, "degraded", reasons, degraded_to=request.degrade_tier)
    return SidecarBudgetDecision(False, "skipped", reasons)


@dataclass(frozen=True)
class WorkerContextGatePolicy:
    required_families: tuple[str, ...] = REQUIRED_WORKER_FAMILIES
    forbidden_stream_fields: tuple[str, ...] = tuple(sorted(RAW_STREAM_FIELDS))

    @classmethod
    def default(cls) -> "WorkerContextGatePolicy":
        return cls()


@dataclass(frozen=True)
class WorkerContextGateReport:
    compliant: bool
    fail_closed: bool
    checked_families: list[str]
    violations: list[dict[str, str]]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def inspect_worker_context_gates(
    wrappers: Mapping[str, Mapping[str, Any]],
    *,
    policy: WorkerContextGatePolicy,
) -> WorkerContextGateReport:
    violations: list[dict[str, str]] = []
    checked: list[str] = []
    for family in policy.required_families:
        cfg = wrappers.get(family)
        if cfg is None:
            violations.append({"family": family, "field": "wrapper", "reason": "missing"})
            continue
        checked.append(family)
        if cfg.get("typed_events") is not True:
            violations.append({"family": family, "field": "typed_events", "reason": "required"})
        if cfg.get("final_packet") is not True:
            violations.append({"family": family, "field": "final_packet", "reason": "required"})
        for field_name in policy.forbidden_stream_fields:
            if cfg.get(field_name) is True:
                violations.append({"family": family, "field": field_name, "reason": "raw_stream_forbidden"})
    return WorkerContextGateReport(not violations, True, checked, violations)


@dataclass(frozen=True)
class MemoryQualityRecord:
    memory_id: str
    tenant_id: str
    repo_id: str
    scope: str
    confidence: float
    updated_at: float
    audit_history: list[str]
    feedback: list[str] = field(default_factory=list)
    suppressed: bool = False
    retired: bool = False
    compacted: bool = False

    def to_dict(self) -> dict[str, Any]:
        return _redact(asdict(self))


@dataclass(frozen=True)
class MemoryQualityLifecycleResult:
    records: dict[str, MemoryQualityRecord]
    compacted_count: int
    retired_count: int
    suppressed_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "records": {key: record.to_dict() for key, record in self.records.items()},
            "compacted_count": self.compacted_count,
            "retired_count": self.retired_count,
            "suppressed_count": self.suppressed_count,
        }


def compact_memory_quality_records(
    records: list[MemoryQualityRecord],
    *,
    now: float,
    stale_after_seconds: float,
    retire_below: float,
) -> MemoryQualityLifecycleResult:
    processed: dict[str, MemoryQualityRecord] = {}
    compacted = retired = suppressed = 0
    for record in records:
        confidence = float(record.confidence)
        audit = list(record.audit_history)
        if "helpful" in record.feedback:
            confidence = min(1.0, confidence + 0.05)
            audit.append(f"audit://memory/{record.memory_id}/confidence_increase")
        if "ignored" in record.feedback:
            confidence -= 0.15
            audit.append(f"audit://memory/{record.memory_id}/ignored_demotion")
        if "harmful" in record.feedback:
            confidence -= 0.2
            audit.append(f"audit://memory/{record.memory_id}/harmful_demotion")
        is_stale = float(now) - float(record.updated_at) > float(stale_after_seconds)
        is_suppressed = record.suppressed or is_stale
        if is_suppressed and not record.suppressed:
            suppressed += 1
            audit.append(f"audit://memory/{record.memory_id}/stale_suppression")
        is_retired = record.retired or confidence < retire_below
        if is_retired and not record.retired:
            retired += 1
            audit.append(f"audit://memory/{record.memory_id}/retired")
        is_compacted = is_suppressed or is_retired
        if is_compacted:
            compacted += 1
            audit.append(f"audit://memory/{record.memory_id}/compacted")
        processed[record.memory_id] = replace(
            record,
            confidence=max(0.0, confidence),
            audit_history=audit,
            suppressed=is_suppressed,
            retired=is_retired,
            compacted=is_compacted,
        )
    return MemoryQualityLifecycleResult(processed, compacted, retired, suppressed)


@dataclass(frozen=True)
class DreamingBacklogPolicy:
    tenant_quota: int
    proposal_type_quota: dict[str, int]
    risk_quota: dict[str, int]
    max_age_seconds: float


@dataclass(frozen=True)
class DreamingBacklogSummary:
    visible_count: int
    archived_count: int
    duplicate_count: int
    quota_blocked_count: int
    by_tenant: dict[str, dict[str, int]]
    operator_summary: dict[str, Any]
    visible: list[dict[str, Any]] = field(default_factory=list)
    archived: list[dict[str, Any]] = field(default_factory=list)
    blocked: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return _redact(asdict(self))


def summarize_dreaming_backlog(
    proposals: list[Mapping[str, Any]],
    *,
    policy: DreamingBacklogPolicy,
    now: float,
) -> DreamingBacklogSummary:
    seen_signatures: set[str] = set()
    tenant_counts: dict[str, int] = {}
    type_counts: dict[str, int] = {}
    risk_counts: dict[str, int] = {}
    by_tenant: dict[str, dict[str, int]] = {}
    visible: list[dict[str, Any]] = []
    archived: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    duplicates = 0
    quota_blocked = 0

    for proposal in proposals:
        item = _redact(dict(proposal))
        tenant = str(proposal.get("tenant_id") or "_unknown")
        proposal_type = str(proposal.get("proposal_type") or "_unknown")
        risk = str(proposal.get("risk") or "medium")
        signature = str(proposal.get("signature") or proposal.get("proposal_id") or _stable_hash(proposal))
        tenant_bucket = by_tenant.setdefault(tenant, {"visible": 0, "archived": 0, "blocked": 0, "duplicates": 0})

        if float(now) - float(proposal.get("created_at") or 0) > policy.max_age_seconds:
            tenant_bucket["archived"] += 1
            archived.append({**item, "status": "archived", "reason": "max_age"})
            continue
        if signature in seen_signatures:
            duplicates += 1
            tenant_bucket["duplicates"] += 1
            blocked.append({**item, "status": "blocked", "reason": "duplicate"})
            continue
        seen_signatures.add(signature)
        quota_reason = None
        if tenant_counts.get(tenant, 0) >= policy.tenant_quota:
            quota_reason = "tenant_quota"
        elif type_counts.get(proposal_type, 0) >= policy.proposal_type_quota.get(proposal_type, policy.tenant_quota):
            quota_reason = "proposal_type_quota"
        elif risk_counts.get(risk, 0) >= policy.risk_quota.get(risk, policy.tenant_quota):
            quota_reason = "risk_quota"
        if quota_reason:
            quota_blocked += 1
            tenant_bucket["blocked"] += 1
            blocked.append({**item, "status": "blocked", "reason": quota_reason})
            continue
        tenant_counts[tenant] = tenant_counts.get(tenant, 0) + 1
        type_counts[proposal_type] = type_counts.get(proposal_type, 0) + 1
        risk_counts[risk] = risk_counts.get(risk, 0) + 1
        tenant_bucket["visible"] += 1
        visible.append({**item, "status": "visible"})

    return DreamingBacklogSummary(
        visible_count=len(visible),
        archived_count=len(archived),
        duplicate_count=duplicates,
        quota_blocked_count=quota_blocked,
        by_tenant=by_tenant,
        operator_summary={
            "visible": len(visible),
            "archived": len(archived),
            "blocked": len(blocked),
            "fail_closed": True,
        },
        visible=visible,
        archived=archived,
        blocked=blocked,
    )


AZURE_HARDENING_FIELDS = (
    "managed_identity",
    "rbac",
    "private_endpoints",
    "vnet_integration",
    "diagnostics",
    "storage_lifecycle_policy",
    "key_vault_access",
    "rollback_artifacts",
    "explicit_approval",
)


@dataclass(frozen=True)
class AzureProductionHardeningResult:
    allowed: bool
    fail_closed: bool
    blockers: list[str]
    checks: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return _redact(asdict(self))


def evaluate_azure_production_hardening(evidence: Mapping[str, Any] | None) -> AzureProductionHardeningResult:
    data = _copy_mapping(evidence)
    if isinstance(data.get("checks"), Mapping):
        data = _copy_mapping(data.get("checks"))
    blockers: list[str] = []
    for field_name in AZURE_HARDENING_FIELDS:
        if data.get(field_name) is not True:
            blockers.append(field_name)
    if str(data.get("ingress") or "") not in {"frontdoor_private", "app_gateway_private", "private"}:
        blockers.append("ingress")
    return AzureProductionHardeningResult(
        allowed=not blockers,
        fail_closed=True,
        blockers=blockers,
        checks=_redact(data),
    )


def platform_hardening_snapshot(**sections: Any) -> dict[str, Any]:
    """Return a bounded JSON-ready inspection surface for operators/API callers."""

    return {
        "schema_version": 1,
        "read_only": True,
        "sections": _redact(sections),
    }


def run_platform_hardening_e2e_fixture() -> dict[str, Any]:
    """Exercise fail-closed hardening gates without blocking foreground work."""

    ledger = ApprovalLedger()
    approval = ledger.record(
        actor_id="operator",
        actor_role="tenant-admin",
        tenant_id="tenant-fixture",
        scope="production",
        action="deployment.apply",
        target_ref="deployment://fixture",
        target_hash="hash-fixture",
        approval_channel="fixture",
        audit_refs=["audit://fixture"],
        created_at=1.0,
        expires_at=2.0,
    )
    expired_approval = ledger.consume(
        approval.approval_id,
        actor_id="operator",
        actor_role="tenant-admin",
        tenant_id="tenant-fixture",
        action="deployment.apply",
        target_hash="hash-fixture",
        now=3.0,
    )
    budget = evaluate_sidecar_budget(
        SidecarBudgetRequest(
            tenant_id="tenant-fixture",
            task_id="task-fixture",
            sidecar_role="judge",
            llm_backed=True,
            estimated_tokens=100,
            estimated_cost=10.0,
            escalation_reason="fixture",
        ),
        limits=BudgetLimit(tenant_cost=1, task_cost=1, daily_cost=1, tenant_tokens=10, task_tokens=10),
        usage=BudgetUsage(),
    )
    context = inspect_worker_context_gates(
        {"codex": {"typed_events": True, "final_packet": True, "raw_stdout": True}},
        policy=WorkerContextGatePolicy.default(),
    )
    memory = compact_memory_quality_records(
        [
            MemoryQualityRecord(
                memory_id="fixture",
                tenant_id="tenant-fixture",
                repo_id="repo-fixture",
                scope="tenant",
                confidence=0.3,
                updated_at=1.0,
                audit_history=["audit://memory/fixture/created"],
                feedback=["harmful"],
            )
        ],
        now=100.0,
        stale_after_seconds=10.0,
        retire_below=0.35,
    )
    dreaming = summarize_dreaming_backlog(
        [
            {
                "proposal_id": "dream-fixture",
                "tenant_id": "tenant-fixture",
                "proposal_type": "ci_cd_hardening",
                "risk": "high",
                "signature": "fixture",
                "created_at": 1.0,
            }
        ],
        policy=DreamingBacklogPolicy(
            tenant_quota=0,
            proposal_type_quota={"ci_cd_hardening": 0},
            risk_quota={"high": 0},
            max_age_seconds=1000.0,
        ),
        now=10.0,
    )
    azure = evaluate_azure_production_hardening({})
    foreground = {"blocked": False, "sidecars_non_blocking": True}
    return platform_hardening_snapshot(
        approval=expired_approval.to_dict(),
        budget=budget.to_dict(),
        context_gate=context.to_dict(),
        memory=memory.to_dict(),
        dreaming=dreaming.to_dict(),
        azure=azure.to_dict(),
        foreground=foreground,
    )
