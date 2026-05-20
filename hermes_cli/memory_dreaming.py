"""Proposal-only offline dreaming for Hermes memory."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
import re
import time
from typing import Any, Callable, Dict, Iterable, List, Optional

from hermes_cli.config import load_config
from hermes_state import SessionDB


LEGACY_PROPOSAL_TYPES = {"playbook", "test", "routing", "policy", "cleanup", "architecture", "training"}
PHASE18_PROPOSAL_TYPES = {
    "skill_candidate",
    "skill_repair",
    "test_gap",
    "ci_cd_hardening",
    "memory_wiki_update",
    "routing_improvement",
    "allocator_policy_candidate",
    "observability_gap",
    "tenant_onboarding_improvement",
    "toolset_recommendation",
    "cost_optimization",
    "training_corpus_candidate",
    "architecture_review_item",
}
PROPOSAL_TYPES = LEGACY_PROPOSAL_TYPES | PHASE18_PROPOSAL_TYPES
RISK_LEVELS = {"low", "medium", "high"}
TRIGGERS = {"manual", "sidecar_interval", "service_start"}
PROPOSAL_SCHEMA_KEYS = {
    "proposal_type",
    "summary",
    "rationale",
    "evidence_refs",
    "scope",
    "risk",
    "trigger",
    "requested_action",
    "runtime_effect",
}
PHASE18_PROPOSAL_SCHEMA_KEYS = PROPOSAL_SCHEMA_KEYS | {
    "affected_feature_ids",
    "conversion_target",
    "expected_benefit",
    "forbidden_direct_actions",
    "suggested_validation",
    "role_metadata",
    "evidence_packets",
    "judge_state",
    "operator_state",
}
SECRET_PATTERNS = [
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\b\d{8,12}:[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"(?i)(api[_-]?key|secret|token|password)\s*[:=]\s*\S+"),
]
DESTRUCTIVE_PATTERNS = [
    re.compile(r"\brm\s+-rf\b"),
    re.compile(r"\bgit\s+reset\s+--hard\b"),
    re.compile(r"\bgit\s+checkout\s+--\b"),
    re.compile(r"\bdrop\s+database\b", re.I),
]
FORBIDDEN_DIRECT_EFFECT_PATTERNS = [
    re.compile(r"\b(write|update|modify)\s+(the\s+)?wiki\b", re.I),
    re.compile(r"\bexport\s+training\b", re.I),
    re.compile(r"\bqueue\s+(a\s+)?goal\b", re.I),
    re.compile(r"\binject\s+(into\s+)?prompt\b", re.I),
    re.compile(r"\bapply\s+config\b", re.I),
    re.compile(r"\benforce\b", re.I),
    re.compile(r"\bpublish\s+skills?\b", re.I),
    re.compile(r"\bupdate\s+wiki\b", re.I),
    re.compile(r"\bchange\s+config\b", re.I),
    re.compile(r"\bedit\s+repos?\b", re.I),
    re.compile(r"\bdeploy\s+code\b", re.I),
]
RAW_OR_UNBOUNDED_PATTERNS = [
    re.compile(r"\braw\s+transcript\b", re.I),
    re.compile(r"\bfull\s+transcript\b", re.I),
    re.compile(r"\bunbounded\s+logs?\b", re.I),
]
FORBIDDEN_DIRECT_ACTIONS = {
    "inject_prompts",
    "publish_skill",
    "publish_skills",
    "update_wiki",
    "change_config",
    "queue_goal",
    "enforce_policy",
    "edit_repo",
    "deploy_code",
    "export_training_data",
}
DIRECT_MUTATION_ERROR_CODES = {
    "inject_prompts": "direct_prompt_injection_rejected",
    "publish_skill": "direct_skill_publish_rejected",
    "publish_skills": "direct_skill_publish_rejected",
    "update_wiki": "direct_wiki_update_rejected",
    "change_config": "direct_config_change_rejected",
    "queue_goal": "direct_goal_queue_rejected",
    "enforce_policy": "direct_policy_enforcement_rejected",
    "edit_repo": "direct_repo_edit_rejected",
    "deploy_code": "direct_deploy_rejected",
    "export_training_data": "direct_training_export_rejected",
}
CONVERSION_TARGETS = {
    "memory_candidate",
    "memory_wiki_update",
    "global_memory_wiki",
    "skill_candidate",
    "test_backlog_item",
    "spec_task",
    "ci_cd_task",
    "policy_candidate",
    "allocator_policy_candidate",
    "routing_advisory",
    "observability_task",
    "tenant_onboarding_task",
    "toolset_recommendation",
    "cost_review_item",
    "training_corpus_candidate",
    "architecture_review_item",
}


class DreamingParseError(ValueError):
    """Raised when model output is not a strict proposal JSON object."""


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


def _list_loads(value: Any) -> List[Any]:
    if not value:
        return []
    if isinstance(value, list):
        return value
    try:
        parsed = json.loads(value)
    except Exception:
        return []
    return parsed if isinstance(parsed, list) else []


def _stable_id(prefix: str, *parts: Any) -> str:
    raw = "|".join(str(part or "").strip().casefold() for part in parts)
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}_{digest}"


def _contains_secret(value: Any) -> bool:
    text = json.dumps(value, sort_keys=True, ensure_ascii=False) if not isinstance(value, str) else value
    return any(pattern.search(text) for pattern in SECRET_PATTERNS)


def _matches_any(patterns: Iterable[re.Pattern[str]], *parts: Any) -> bool:
    text = " ".join(str(part or "") for part in parts)
    return any(pattern.search(text) for pattern in patterns)


@dataclass
class DreamingConfig:
    enabled: bool = False
    provider: str = "codex"
    model: str = "codex"
    base_url: str = ""
    allow_llm: bool = True
    allow_cross_tenant: bool = False
    allow_policy_proposals: bool = True
    require_judge: bool = True
    require_operator_approval: bool = True
    max_proposals_per_run: int = 10
    evidence_window: int = 100
    timeout_seconds: float = 300.0
    run_on_start: bool = False
    interval_seconds: float = 3600.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DreamingEvidencePacket:
    packet_id: str
    source_ref: str
    content_summary: str = ""
    tenant_id: Optional[str] = None
    repo_id: Optional[str] = None
    scope: str = "local"
    approved: bool = False
    redacted: bool = False
    shareable: bool = False
    kind: str = "memory"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DreamingInputPacket:
    role_metadata: Dict[str, Any]
    evidence_packets: List[DreamingEvidencePacket]
    skipped: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "role_metadata": self.role_metadata,
            "evidence_packets": [packet.to_dict() for packet in self.evidence_packets],
            "skipped": self.skipped,
        }


@dataclass
class DreamingValidatorOutput:
    accepted: bool
    proposal_id: str
    proposal_type: str
    error_codes: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    conversion_target: Optional[str] = None
    required_gates: List[str] = field(default_factory=lambda: ["deterministic_validator", "judge", "operator"])

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DreamingProposal:
    id: str
    proposal_type: str
    summary: str
    rationale: str
    evidence_refs: List[str]
    scope: Dict[str, Any]
    risk: str
    trigger: str
    requested_action: str
    runtime_effect: bool = False
    affected_feature_ids: List[str] = field(default_factory=list)
    conversion_target: str = "memory_candidate"
    expected_benefit: str = ""
    forbidden_direct_actions: List[str] = field(default_factory=list)
    suggested_validation: List[str] = field(default_factory=list)
    role_metadata: Dict[str, Any] = field(default_factory=dict)
    evidence_packets: List[Dict[str, Any]] = field(default_factory=list)
    judge_state: Dict[str, Any] = field(default_factory=lambda: {"status": "pending"})
    operator_state: Dict[str, Any] = field(default_factory=lambda: {"status": "pending"})
    status: str = "proposed"
    tenant_id: Optional[str] = None
    repo_id: Optional[str] = None
    interval_due_at: Optional[float] = None
    job_id: Optional[str] = None
    validator_errors: List[str] = field(default_factory=list)
    judge_decision: Dict[str, Any] = field(default_factory=dict)
    operator_decision: Dict[str, Any] = field(default_factory=dict)
    converted_candidate_id: Optional[str] = None
    created_at: float = field(default_factory=_now)
    updated_at: float = field(default_factory=_now)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DreamingRunResult:
    status: str
    trigger: str
    scanned: int
    proposals_created: int
    proposals_updated: int
    proposals: List[DreamingProposal] = field(default_factory=list)
    rejected: List[Dict[str, Any]] = field(default_factory=list)
    skipped: List[Dict[str, Any]] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    config: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            **asdict(self),
            "proposals": [proposal.to_dict() for proposal in self.proposals],
        }


@dataclass
class DreamingActionResult:
    proposal_id: str
    status: str
    converted_candidate_id: Optional[str] = None
    proposal: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def load_dreaming_config(config: Optional[Dict[str, Any]] = None) -> DreamingConfig:
    supervisor = (config or {}).get("supervisor", {})
    raw = supervisor.get("dreaming", {}) if isinstance(supervisor, dict) else {}
    if not isinstance(raw, dict):
        raw = {}
    return DreamingConfig(
        enabled=bool(raw.get("enabled", False)),
        provider=str(raw.get("provider", "codex") or "codex"),
        model=str(raw.get("model", "codex") or "codex"),
        base_url=str(raw.get("base_url", "") or ""),
        allow_llm=bool(raw.get("allow_llm", True)),
        allow_cross_tenant=bool(raw.get("allow_cross_tenant", False)),
        allow_policy_proposals=bool(raw.get("allow_policy_proposals", True)),
        require_judge=bool(raw.get("require_judge", True)),
        require_operator_approval=bool(raw.get("require_operator_approval", True)),
        max_proposals_per_run=int(raw.get("max_proposals_per_run", 10) or 10),
        evidence_window=int(raw.get("evidence_window", 100) or 100),
        timeout_seconds=float(raw.get("timeout_seconds", 300) or 300),
        run_on_start=bool(raw.get("run_on_start", False)),
        interval_seconds=float(raw.get("interval_seconds", 3600) or 3600),
    )


def ensure_dreaming_schema(db: SessionDB) -> None:
    def _do(conn):
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS hermes_dreaming_proposals (
                id TEXT PRIMARY KEY,
                tenant_id TEXT,
                repo_id TEXT,
                proposal_type TEXT NOT NULL,
                summary TEXT NOT NULL,
                rationale TEXT NOT NULL,
                evidence_refs_json TEXT,
                scope_json TEXT,
                risk TEXT NOT NULL,
                trigger TEXT NOT NULL,
                requested_action TEXT NOT NULL,
                runtime_effect INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL,
                interval_due_at REAL,
                job_id TEXT,
                validator_errors_json TEXT,
                judge_decision_json TEXT,
                operator_decision_json TEXT,
                converted_candidate_id TEXT,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )
            """
        )
        existing_columns = {row[1] for row in conn.execute("PRAGMA table_info(hermes_dreaming_proposals)").fetchall()}
        additive_columns = {
            "affected_feature_ids_json": "TEXT",
            "conversion_target": "TEXT",
            "expected_benefit": "TEXT",
            "forbidden_direct_actions_json": "TEXT",
            "suggested_validation_json": "TEXT",
            "role_metadata_json": "TEXT",
            "evidence_packets_json": "TEXT",
            "judge_state_json": "TEXT",
            "operator_state_json": "TEXT",
        }
        for column, column_type in additive_columns.items():
            if column not in existing_columns:
                conn.execute(f"ALTER TABLE hermes_dreaming_proposals ADD COLUMN {column} {column_type}")
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_hermes_dreaming_proposals_scope
                ON hermes_dreaming_proposals(tenant_id, repo_id, status, proposal_type, updated_at DESC)
            """
        )

    db._execute_write(_do)


def resolve_dreaming_role(
    *,
    mode: str,
    tenant_id: Optional[str] = None,
    repo_id: Optional[str] = None,
) -> Dict[str, Any]:
    normalized = str(mode or "").strip().lower()
    if normalized == "local":
        if not tenant_id or not repo_id:
            raise ValueError("local dreaming requires tenant_id and repo_id")
        return {
            "role": "local_dreaming",
            "mode": "local",
            "tenant_id": tenant_id,
            "repo_id": repo_id,
            "visibility": "tenant_repo",
            "can_publish_global": False,
            "input_policy": "tenant_repo_approved_evidence_only",
        }
    if normalized == "global":
        return {
            "role": "global_dreaming",
            "mode": "global",
            "tenant_id": None,
            "repo_id": None,
            "visibility": "global",
            "can_publish_global": False,
            "input_policy": "redacted_approved_shareable_global_only",
        }
    raise ValueError(f"invalid dreaming role mode: {mode}")


def _record_bool(record: Dict[str, Any], *keys: str) -> bool:
    return any(bool(record.get(key)) for key in keys)


def _record_scope(record: Dict[str, Any]) -> str:
    scope = record.get("scope")
    if isinstance(scope, dict):
        return str(scope.get("visibility") or scope.get("scope") or "").strip().lower()
    return str(scope or record.get("visibility") or "").strip().lower()


def _packet_from_record(record: Dict[str, Any], *, default_scope: str) -> DreamingEvidencePacket:
    packet_id = str(record.get("packet_id") or record.get("id") or record.get("record_id") or record.get("source_ref") or "")
    return DreamingEvidencePacket(
        packet_id=packet_id,
        source_ref=str(record.get("source_ref") or record.get("evidence_uri") or packet_id),
        content_summary=str(record.get("content_summary") or record.get("summary") or record.get("content") or "")[:2000],
        tenant_id=record.get("tenant_id"),
        repo_id=record.get("repo_id"),
        scope=_record_scope(record) or default_scope,
        approved=_record_bool(record, "approved", "is_approved") or record.get("status") == "approved",
        redacted=_record_bool(record, "redacted", "is_redacted"),
        shareable=_record_bool(record, "shareable", "global_shareable", "is_shareable"),
        kind=str(record.get("kind") or record.get("source_type") or "memory"),
    )


def build_dreaming_input_packet(role_metadata: Dict[str, Any], records: Iterable[Dict[str, Any]]) -> DreamingInputPacket:
    role = str(role_metadata.get("role") or "")
    packets: List[DreamingEvidencePacket] = []
    skipped: List[Dict[str, Any]] = []
    for record in records:
        if not isinstance(record, dict):
            skipped.append({"reason": "invalid_record"})
            continue
        packet = _packet_from_record(record, default_scope="global" if role == "global_dreaming" else "local")
        if not packet.packet_id:
            skipped.append({"reason": "missing_packet_id"})
            continue
        if _contains_secret(packet.to_dict()) or _matches_any(RAW_OR_UNBOUNDED_PATTERNS, packet.content_summary):
            skipped.append({"packet_id": packet.packet_id, "reason": "unsafe_content"})
            continue
        if role == "local_dreaming":
            if packet.tenant_id != role_metadata.get("tenant_id") or packet.repo_id != role_metadata.get("repo_id"):
                skipped.append({"packet_id": packet.packet_id, "reason": "outside_local_scope"})
                continue
            packets.append(packet)
            continue
        if role == "global_dreaming":
            if packet.scope != "global" or not (packet.approved and packet.redacted and packet.shareable):
                skipped.append({"packet_id": packet.packet_id, "reason": "not_redacted_approved_shareable_global"})
                continue
            packet.tenant_id = None
            packet.repo_id = None
            packets.append(packet)
            continue
        skipped.append({"packet_id": packet.packet_id, "reason": "unknown_role"})
    return DreamingInputPacket(role_metadata=dict(role_metadata), evidence_packets=packets, skipped=skipped)


def _row_to_proposal(row: Any) -> DreamingProposal:
    scope = _json_loads(row["scope_json"])
    def _row_value(key: str, default: Any = None) -> Any:
        try:
            return row[key]
        except Exception:
            return default

    return DreamingProposal(
        id=row["id"],
        tenant_id=row["tenant_id"],
        repo_id=row["repo_id"],
        proposal_type=row["proposal_type"],
        summary=row["summary"],
        rationale=row["rationale"],
        evidence_refs=[str(item) for item in _list_loads(row["evidence_refs_json"])],
        scope=scope,
        risk=row["risk"],
        trigger=row["trigger"],
        requested_action=row["requested_action"],
        runtime_effect=bool(row["runtime_effect"]),
        affected_feature_ids=[str(item) for item in _list_loads(_row_value("affected_feature_ids_json"))],
        conversion_target=str(_row_value("conversion_target") or scope.get("conversion_target") or "memory_candidate"),
        expected_benefit=str(_row_value("expected_benefit") or ""),
        forbidden_direct_actions=[str(item) for item in _list_loads(_row_value("forbidden_direct_actions_json"))],
        suggested_validation=[str(item) for item in _list_loads(_row_value("suggested_validation_json"))],
        role_metadata=_json_loads(_row_value("role_metadata_json")) or scope.get("role_metadata", {}),
        evidence_packets=[
            item for item in _list_loads(_row_value("evidence_packets_json")) if isinstance(item, dict)
        ],
        judge_state=_json_loads(_row_value("judge_state_json")) or {"status": "pending"},
        operator_state=_json_loads(_row_value("operator_state_json")) or {"status": "pending"},
        status=row["status"],
        interval_due_at=row["interval_due_at"],
        job_id=row["job_id"],
        validator_errors=[str(item) for item in _list_loads(row["validator_errors_json"])],
        judge_decision=_json_loads(row["judge_decision_json"]),
        operator_decision=_json_loads(row["operator_decision_json"]),
        converted_candidate_id=row["converted_candidate_id"],
        created_at=float(row["created_at"] or 0.0),
        updated_at=float(row["updated_at"] or 0.0),
    )


def parse_dreaming_proposal_output(raw: str, *, trigger: Optional[str] = None) -> DreamingProposal:
    text = str(raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            raise DreamingParseError("dreaming output did not contain a JSON object")
        try:
            payload = json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            raise DreamingParseError(f"dreaming output was not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise DreamingParseError("dreaming output must be a JSON object")
    has_phase18_fields = bool(set(payload) & (PHASE18_PROPOSAL_SCHEMA_KEYS - PROPOSAL_SCHEMA_KEYS))
    allowed_keys = PHASE18_PROPOSAL_SCHEMA_KEYS if has_phase18_fields else PROPOSAL_SCHEMA_KEYS
    extra = set(payload) - allowed_keys
    missing = PROPOSAL_SCHEMA_KEYS - set(payload)
    if extra:
        raise DreamingParseError(f"unexpected proposal fields: {sorted(extra)}")
    if missing:
        raise DreamingParseError(f"missing proposal fields: {sorted(missing)}")

    proposal_type = str(payload["proposal_type"] or "").strip()
    risk = str(payload["risk"] or "").strip()
    proposal_trigger = str(trigger or payload["trigger"] or "").strip()
    if proposal_type not in PROPOSAL_TYPES:
        raise DreamingParseError(f"invalid proposal_type: {proposal_type}")
    if risk not in RISK_LEVELS:
        raise DreamingParseError(f"invalid risk: {risk}")
    if proposal_trigger not in TRIGGERS:
        raise DreamingParseError(f"invalid trigger: {proposal_trigger}")
    evidence_refs = payload["evidence_refs"]
    if not isinstance(evidence_refs, list) or not all(isinstance(item, str) for item in evidence_refs):
        raise DreamingParseError("evidence_refs must be a list of strings")
    scope = payload["scope"]
    if not isinstance(scope, dict):
        raise DreamingParseError("scope must be an object")
    runtime_effect = payload["runtime_effect"]
    if not isinstance(runtime_effect, bool):
        raise DreamingParseError("runtime_effect must be boolean")
    summary = str(payload["summary"] or "").strip()
    rationale = str(payload["rationale"] or "").strip()
    requested_action = str(payload["requested_action"] or "").strip()
    if not summary or not rationale or not requested_action:
        raise DreamingParseError("summary, rationale, and requested_action are required")
    affected_feature_ids = payload.get("affected_feature_ids", [])
    forbidden_direct_actions = payload.get("forbidden_direct_actions", [])
    suggested_validation = payload.get("suggested_validation", [])
    evidence_packets = payload.get("evidence_packets", [])
    for field_name, value in (
        ("affected_feature_ids", affected_feature_ids),
        ("forbidden_direct_actions", forbidden_direct_actions),
        ("suggested_validation", suggested_validation),
        ("evidence_packets", evidence_packets),
    ):
        if not isinstance(value, list):
            raise DreamingParseError(f"{field_name} must be a list")
    role_metadata = payload.get("role_metadata", {})
    judge_state = payload.get("judge_state", {"status": "pending"})
    operator_state = payload.get("operator_state", {"status": "pending"})
    for field_name, value in (("role_metadata", role_metadata), ("judge_state", judge_state), ("operator_state", operator_state)):
        if not isinstance(value, dict):
            raise DreamingParseError(f"{field_name} must be an object")
    conversion_target = str(payload.get("conversion_target") or _default_conversion_target(proposal_type)).strip()
    expected_benefit = str(payload.get("expected_benefit") or "").strip()
    proposal_id = _stable_id(
        "dream",
        proposal_type,
        summary,
        json.dumps(scope, sort_keys=True),
        requested_action,
    )
    return DreamingProposal(
        id=proposal_id,
        tenant_id=scope.get("tenant_id"),
        repo_id=scope.get("repo_id"),
        proposal_type=proposal_type,
        summary=summary,
        rationale=rationale,
        evidence_refs=[item for item in evidence_refs if item.strip()],
        scope=scope,
        risk=risk,
        trigger=proposal_trigger,
        requested_action=requested_action,
        runtime_effect=runtime_effect,
        affected_feature_ids=[str(item) for item in affected_feature_ids if str(item).strip()],
        conversion_target=conversion_target,
        expected_benefit=expected_benefit,
        forbidden_direct_actions=[str(item) for item in forbidden_direct_actions if str(item).strip()],
        suggested_validation=[str(item) for item in suggested_validation if str(item).strip()],
        role_metadata=role_metadata,
        evidence_packets=[item for item in evidence_packets if isinstance(item, dict)],
        judge_state=judge_state,
        operator_state=operator_state,
    )


def _default_conversion_target(proposal_type: str) -> str:
    return {
        "playbook": "memory_candidate",
        "test": "test_backlog_item",
        "routing": "routing_advisory",
        "policy": "policy_candidate",
        "cleanup": "memory_candidate",
        "architecture": "architecture_review_item",
        "training": "training_corpus_candidate",
        "skill_candidate": "skill_candidate",
        "skill_repair": "skill_candidate",
        "test_gap": "test_backlog_item",
        "ci_cd_hardening": "ci_cd_task",
        "memory_wiki_update": "memory_wiki_update",
        "routing_improvement": "routing_advisory",
        "allocator_policy_candidate": "allocator_policy_candidate",
        "observability_gap": "observability_task",
        "tenant_onboarding_improvement": "tenant_onboarding_task",
        "toolset_recommendation": "toolset_recommendation",
        "cost_optimization": "cost_review_item",
        "training_corpus_candidate": "training_corpus_candidate",
        "architecture_review_item": "architecture_review_item",
    }.get(proposal_type, "memory_candidate")


def validate_dreaming_proposal(
    proposal: DreamingProposal,
    *,
    config: Optional[DreamingConfig] = None,
    known_evidence_refs: Optional[Iterable[str]] = None,
) -> List[str]:
    return validate_dreaming_proposal_details(
        proposal,
        config=config,
        known_evidence_refs=known_evidence_refs,
    ).error_codes


def validate_dreaming_proposal_details(
    proposal: DreamingProposal,
    *,
    config: Optional[DreamingConfig] = None,
    known_evidence_refs: Optional[Iterable[str]] = None,
) -> DreamingValidatorOutput:
    cfg = config or DreamingConfig()
    errors: List[str] = []
    if not proposal.evidence_refs:
        errors.append("missing_evidence_refs")
    known = {str(item) for item in (known_evidence_refs or []) if str(item)}
    if known:
        missing = [ref for ref in proposal.evidence_refs if ref not in known]
        if missing:
            errors.append("unknown_evidence_refs")
    if proposal.runtime_effect:
        errors.append("runtime_effect_not_allowed")
    if proposal.proposal_type == "policy" and not cfg.allow_policy_proposals:
        errors.append("policy_proposals_disabled")
    if proposal.proposal_type == "allocator_policy_candidate" and not cfg.allow_policy_proposals:
        errors.append("policy_proposals_disabled")
    if proposal.scope.get("cross_tenant_shareable") and not cfg.allow_cross_tenant:
        errors.append("cross_tenant_sharing_disabled")
    role = proposal.role_metadata or {}
    if role.get("role") == "local_dreaming":
        if proposal.scope.get("tenant_id") and proposal.scope.get("tenant_id") != role.get("tenant_id"):
            errors.append("tenant_scope_mismatch")
        if proposal.scope.get("repo_id") and proposal.scope.get("repo_id") != role.get("repo_id"):
            errors.append("repo_scope_mismatch")
        if proposal.scope.get("visibility") == "global" or proposal.conversion_target == "global_memory_wiki":
            errors.append("local_cannot_publish_global")
    if role.get("role") == "global_dreaming":
        for packet in proposal.evidence_packets:
            if packet.get("tenant_id") or packet.get("repo_id"):
                errors.append("global_evidence_contains_private_scope")
            if packet.get("scope") != "global":
                errors.append("global_evidence_not_global")
            if not (packet.get("approved") and packet.get("redacted") and packet.get("shareable")):
                errors.append("global_evidence_not_redacted_approved_shareable")
    if proposal.conversion_target and proposal.conversion_target not in CONVERSION_TARGETS:
        errors.append("unsupported_conversion_target")
    forbidden_actions = {str(item).strip().lower() for item in proposal.forbidden_direct_actions}
    if forbidden_actions & FORBIDDEN_DIRECT_ACTIONS:
        # Listing forbidden actions is expected. Requesting them is caught by text patterns below.
        pass
    if _contains_secret(proposal.to_dict()):
        errors.append("secret_pattern_detected")
    if _matches_any(DESTRUCTIVE_PATTERNS, proposal.summary, proposal.requested_action, proposal.rationale):
        errors.append("destructive_command_detected")
    if _matches_any(FORBIDDEN_DIRECT_EFFECT_PATTERNS, proposal.summary, proposal.requested_action, proposal.rationale):
        errors.append("forbidden_direct_runtime_effect")
    if _matches_any(RAW_OR_UNBOUNDED_PATTERNS, proposal.summary, proposal.requested_action, proposal.rationale, proposal.to_dict()):
        errors.append("raw_transcript_or_unbounded_log_detected")
    if proposal.proposal_type in PHASE18_PROPOSAL_TYPES:
        if not proposal.conversion_target:
            errors.append("missing_conversion_target")
        if not proposal.expected_benefit:
            errors.append("missing_expected_benefit")
        if not proposal.suggested_validation:
            errors.append("missing_suggested_validation")
    unique_errors = sorted(set(errors))
    return DreamingValidatorOutput(
        accepted=not unique_errors,
        proposal_id=proposal.id,
        proposal_type=proposal.proposal_type,
        error_codes=unique_errors,
        conversion_target=proposal.conversion_target,
    )


def evaluate_dreaming_direct_mutation_request(
    requested_action: str,
    *,
    proposal_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Classify direct runtime mutation requests as rejected no-ops."""
    normalized = str(requested_action or "").strip().lower().replace("-", " ")
    action_aliases = {
        "inject_prompts": ("inject prompt", "inject prompts", "prompt injection"),
        "publish_skill": ("publish skill", "publish skills"),
        "update_wiki": ("update wiki", "write wiki", "modify wiki"),
        "change_config": ("change config", "apply config", "modify config"),
        "queue_goal": ("queue goal", "queue goals"),
        "enforce_policy": ("enforce policy", "policy enforcement"),
        "edit_repo": ("edit repo", "edit repos", "repo edit", "repository edit"),
        "deploy_code": ("deploy code", "deployment", "deploy"),
        "export_training_data": ("export training data", "training export"),
    }
    error_codes = [
        DIRECT_MUTATION_ERROR_CODES[action]
        for action, aliases in action_aliases.items()
        if any(alias in normalized for alias in aliases)
    ]
    if not error_codes and _matches_any(FORBIDDEN_DIRECT_EFFECT_PATTERNS, requested_action):
        error_codes.append("direct_runtime_mutation_rejected")
    if not error_codes:
        return {
            "proposal_id": proposal_id,
            "status": "noop",
            "effect": "noop",
            "error_codes": [],
        }
    return {
        "proposal_id": proposal_id,
        "status": "rejected",
        "effect": "noop",
        "error_codes": sorted(set(error_codes)),
    }


def _proposal_from_wiki_claim(claim: Any, *, trigger: str, interval_due_at: Optional[float]) -> DreamingProposal:
    scope = {
        "tenant_id": claim.tenant_id,
        "repo_id": claim.repo_id,
        "tool": claim.scope_json.get("tool"),
        "task_type": claim.kind,
        "cross_tenant_shareable": False,
    }
    summary = f"Create a reusable validation playbook from wiki claim: {claim.title}"
    requested_action = "Draft a proposal-only playbook or validation checklist for operator review."
    proposal = DreamingProposal(
        id=_stable_id("dream", "playbook", summary, claim.id),
        tenant_id=claim.tenant_id,
        repo_id=claim.repo_id,
        proposal_type="playbook",
        summary=summary,
        rationale="The wiki claim is approved durable memory and may be reusable as a bounded playbook.",
        evidence_refs=[claim.id],
        scope=scope,
        risk="low",
        trigger=trigger,
        requested_action=requested_action,
        runtime_effect=False,
        interval_due_at=interval_due_at,
    )
    return proposal


def _proposal_from_candidate(candidate: Dict[str, Any], *, trigger: str, interval_due_at: Optional[float]) -> DreamingProposal:
    evidence = candidate.get("evidence_json") if isinstance(candidate.get("evidence_json"), dict) else {}
    scope = {
        "tenant_id": candidate.get("tenant_id"),
        "repo_id": candidate.get("repo_id"),
        "task_type": candidate.get("kind"),
        "cross_tenant_shareable": False,
    }
    evidence_ref = str(candidate.get("id") or evidence.get("record_id") or "")
    claim = str(candidate.get("claim") or "candidate").strip()
    summary = f"Review repeated learning candidate for cleanup or recovery: {claim[:120]}"
    return DreamingProposal(
        id=_stable_id("dream", "cleanup", summary, evidence_ref),
        tenant_id=candidate.get("tenant_id"),
        repo_id=candidate.get("repo_id"),
        proposal_type="cleanup",
        summary=summary,
        rationale="A proposed or blocked candidate may indicate stale/noisy memory or a missing recovery playbook.",
        evidence_refs=[evidence_ref] if evidence_ref else [],
        scope=scope,
        risk="low",
        trigger=trigger,
        requested_action="Propose cleanup, recovery, or validation follow-up for operator review only.",
        runtime_effect=False,
        interval_due_at=interval_due_at,
    )


def _collect_known_evidence_refs(db: SessionDB, *, tenant_id: Optional[str], repo_id: Optional[str]) -> set[str]:
    refs: set[str] = set()
    try:
        from hermes_cli.memory_wiki import list_memory_wiki_claims

        refs.update(claim.id for claim in list_memory_wiki_claims(db, tenant_id=tenant_id, repo_id=repo_id, limit=500))
    except Exception:
        pass
    for candidate in db.list_meta_candidates(tenant_id=tenant_id, repo_id=repo_id, limit=500):
        if candidate.get("id"):
            refs.add(str(candidate["id"]))
        evidence = candidate.get("evidence_json") if isinstance(candidate.get("evidence_json"), dict) else {}
        for key in ("record_id", "evidence_uri", "packet_id"):
            if evidence.get(key):
                refs.add(str(evidence[key]))
    try:
        from hermes_cli.learning_jobs import list_learning_jobs

        refs.update(job.id for job in list_learning_jobs(db, tenant_id=tenant_id, repo_id=repo_id, limit=500))
    except Exception:
        pass
    return refs


def _generate_deterministic_proposals(
    db: SessionDB,
    *,
    tenant_id: Optional[str],
    repo_id: Optional[str],
    trigger: str,
    interval_due_at: Optional[float],
    limit: int,
) -> List[DreamingProposal]:
    proposals: List[DreamingProposal] = []
    try:
        from hermes_cli.memory_wiki import list_memory_wiki_claims

        for claim in list_memory_wiki_claims(db, tenant_id=tenant_id, repo_id=repo_id, status="active", limit=limit):
            proposals.append(_proposal_from_wiki_claim(claim, trigger=trigger, interval_due_at=interval_due_at))
            if len(proposals) >= limit:
                return proposals
    except Exception:
        pass
    for candidate in db.list_meta_candidates(tenant_id=tenant_id, repo_id=repo_id, status="proposed", limit=limit):
        proposals.append(_proposal_from_candidate(candidate, trigger=trigger, interval_due_at=interval_due_at))
        if len(proposals) >= limit:
            return proposals
    return proposals


def upsert_dreaming_proposal(db: SessionDB, proposal: DreamingProposal) -> DreamingProposal:
    ensure_dreaming_schema(db)
    now = _now()

    def _do(conn):
        conn.execute(
            """
            INSERT INTO hermes_dreaming_proposals (
                id, tenant_id, repo_id, proposal_type, summary, rationale,
                evidence_refs_json, scope_json, risk, trigger, requested_action,
                runtime_effect, status, interval_due_at, job_id,
                validator_errors_json, judge_decision_json, operator_decision_json,
                converted_candidate_id, created_at, updated_at,
                affected_feature_ids_json, conversion_target, expected_benefit,
                forbidden_direct_actions_json, suggested_validation_json,
                role_metadata_json, evidence_packets_json, judge_state_json,
                operator_state_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                tenant_id = excluded.tenant_id,
                repo_id = excluded.repo_id,
                proposal_type = excluded.proposal_type,
                summary = excluded.summary,
                rationale = excluded.rationale,
                evidence_refs_json = excluded.evidence_refs_json,
                scope_json = excluded.scope_json,
                risk = excluded.risk,
                trigger = excluded.trigger,
                requested_action = excluded.requested_action,
                runtime_effect = excluded.runtime_effect,
                status = CASE
                    WHEN hermes_dreaming_proposals.status IN ('rejected', 'converted', 'archived')
                    THEN hermes_dreaming_proposals.status
                    WHEN excluded.status = 'converted'
                    THEN excluded.status
                    WHEN hermes_dreaming_proposals.status = 'approved'
                    THEN hermes_dreaming_proposals.status
                    ELSE excluded.status
                END,
                interval_due_at = excluded.interval_due_at,
                job_id = excluded.job_id,
                validator_errors_json = excluded.validator_errors_json,
                judge_decision_json = excluded.judge_decision_json,
                operator_decision_json = excluded.operator_decision_json,
                converted_candidate_id = COALESCE(hermes_dreaming_proposals.converted_candidate_id, excluded.converted_candidate_id),
                affected_feature_ids_json = excluded.affected_feature_ids_json,
                conversion_target = excluded.conversion_target,
                expected_benefit = excluded.expected_benefit,
                forbidden_direct_actions_json = excluded.forbidden_direct_actions_json,
                suggested_validation_json = excluded.suggested_validation_json,
                role_metadata_json = excluded.role_metadata_json,
                evidence_packets_json = excluded.evidence_packets_json,
                judge_state_json = excluded.judge_state_json,
                operator_state_json = excluded.operator_state_json,
                updated_at = excluded.updated_at
            """
            ,
            (
                proposal.id,
                proposal.tenant_id,
                proposal.repo_id,
                proposal.proposal_type,
                proposal.summary,
                proposal.rationale,
                json.dumps(proposal.evidence_refs, sort_keys=True),
                _json_dumps(proposal.scope),
                proposal.risk,
                proposal.trigger,
                proposal.requested_action,
                1 if proposal.runtime_effect else 0,
                proposal.status,
                proposal.interval_due_at,
                proposal.job_id,
                json.dumps(proposal.validator_errors, sort_keys=True),
                _json_dumps(proposal.judge_decision),
                _json_dumps(proposal.operator_decision),
                proposal.converted_candidate_id,
                now,
                now,
                json.dumps(proposal.affected_feature_ids, sort_keys=True),
                proposal.conversion_target,
                proposal.expected_benefit,
                json.dumps(proposal.forbidden_direct_actions, sort_keys=True),
                json.dumps(proposal.suggested_validation, sort_keys=True),
                _json_dumps(proposal.role_metadata),
                json.dumps(proposal.evidence_packets, sort_keys=True),
                _json_dumps(proposal.judge_state),
                _json_dumps(proposal.operator_state),
            ),
        )

    db._execute_write(_do)
    row = db._conn.execute("SELECT * FROM hermes_dreaming_proposals WHERE id = ?", (proposal.id,)).fetchone()
    return _row_to_proposal(row)


def run_dreaming(
    db: SessionDB,
    *,
    tenant_id: Optional[str] = None,
    repo_id: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
    trigger: str = "manual",
    force: bool = False,
    interval_due_at: Optional[float] = None,
    model_call: Optional[Callable[[DreamingConfig, str], str]] = None,
) -> DreamingRunResult:
    ensure_dreaming_schema(db)
    if config is None:
        config = load_config()
    cfg = load_dreaming_config(config)
    if trigger not in TRIGGERS:
        raise ValueError(f"invalid dreaming trigger: {trigger}")
    if not cfg.enabled and not force:
        return DreamingRunResult(
            status="skipped",
            trigger=trigger,
            scanned=0,
            proposals_created=0,
            proposals_updated=0,
            skipped=[{"reason": "skipped_by_toggle", "toggle": "supervisor.dreaming.enabled"}],
            config=cfg.to_dict(),
        )
    known_refs = _collect_known_evidence_refs(db, tenant_id=tenant_id, repo_id=repo_id)
    limit = max(1, int(cfg.max_proposals_per_run or 10))
    proposals = _generate_deterministic_proposals(
        db,
        tenant_id=tenant_id,
        repo_id=repo_id,
        trigger=trigger,
        interval_due_at=interval_due_at,
        limit=limit,
    )
    if cfg.allow_llm and model_call is not None and len(proposals) < limit:
        prompt = build_dreaming_prompt(db, tenant_id=tenant_id, repo_id=repo_id, known_refs=sorted(known_refs))
        raw = model_call(cfg, prompt)
        proposals.append(parse_dreaming_proposal_output(raw, trigger=trigger))

    created = 0
    updated = 0
    accepted: List[DreamingProposal] = []
    rejected: List[Dict[str, Any]] = []
    job_id = None
    try:
        from hermes_cli.learning_jobs import record_learning_job

        job = record_learning_job(
            db,
            job_type="dreaming",
            status="running",
            tenant_id=tenant_id,
            repo_id=repo_id,
            metrics={"trigger": trigger},
        )
        job_id = job.id
    except Exception:
        job_id = None

    for proposal in proposals[:limit]:
        proposal.job_id = job_id
        proposal.interval_due_at = interval_due_at
        errors = validate_dreaming_proposal(proposal, config=cfg, known_evidence_refs=known_refs)
        proposal.validator_errors = errors
        if errors:
            proposal.status = "rejected"
            rejected.append({"proposal_id": proposal.id, "errors": errors})
            upsert_dreaming_proposal(db, proposal)
            continue
        existing = get_dreaming_proposal(db, proposal.id)
        if existing is None:
            created += 1
        else:
            updated += 1
        accepted.append(upsert_dreaming_proposal(db, proposal))

    try:
        from hermes_cli.learning_bus import publish_learning_event_safely
        from hermes_cli.learning_jobs import update_learning_job

        metrics = {
            "trigger": trigger,
            "scanned": len(proposals),
            "created": created,
            "updated": updated,
            "rejected": len(rejected),
        }
        if job_id:
            update_learning_job(db, job_id, status="completed", metrics=metrics)
        publish_learning_event_safely(
            db,
            topic="learning.dreaming.completed",
            payload=metrics,
            tenant_id=tenant_id,
            repo_id=repo_id,
            event_key=f"dreaming:{tenant_id or ''}:{repo_id or ''}:{trigger}:{int(_now())}",
        )
    except Exception:
        pass
    return DreamingRunResult(
        status="completed" if not rejected else "completed_with_rejections",
        trigger=trigger,
        scanned=len(proposals),
        proposals_created=created,
        proposals_updated=updated,
        proposals=accepted,
        rejected=rejected,
        config=cfg.to_dict(),
    )


def build_dreaming_prompt(
    db: SessionDB,
    *,
    tenant_id: Optional[str] = None,
    repo_id: Optional[str] = None,
    known_refs: Optional[List[str]] = None,
) -> str:
    evidence: Dict[str, Any] = {"known_evidence_refs": known_refs or []}
    try:
        from hermes_cli.memory_wiki import list_memory_wiki_claims

        evidence["wiki_claims"] = [
            claim.to_dict()
            for claim in list_memory_wiki_claims(db, tenant_id=tenant_id, repo_id=repo_id, status="active", limit=20)
        ]
    except Exception:
        evidence["wiki_claims"] = []
    evidence["candidates"] = db.list_meta_candidates(tenant_id=tenant_id, repo_id=repo_id, status="proposed", limit=20)
    return (
        "You are the Hermes dreaming sidecar. Propose exactly one offline, proposal-only improvement.\n"
        "Return only strict JSON with these fields: proposal_type, summary, rationale, "
        "evidence_refs, scope, risk, trigger, requested_action, runtime_effect, affected_feature_ids, "
        "conversion_target, expected_benefit, forbidden_direct_actions, suggested_validation, "
        "role_metadata, evidence_packets, judge_state, operator_state.\n"
        "Rules: use only evidence_refs from known_evidence_refs; runtime_effect must be false; "
        "do not request direct skill publication, wiki writes, training exports, goal queueing, "
        "config changes, prompt injection, policy enforcement, repo edits, or deployments.\n\n"
        f"Evidence JSON:\n{json.dumps(evidence, indent=2, ensure_ascii=False)}\n"
    )


def build_dreaming_dashboard_dto(proposal: DreamingProposal) -> Dict[str, Any]:
    operator_history: List[Dict[str, Any]] = []
    if proposal.operator_decision:
        operator_history.append(dict(proposal.operator_decision))
    if proposal.operator_state and proposal.operator_state != proposal.operator_decision:
        state = dict(proposal.operator_state)
        if state not in operator_history:
            operator_history.append(state)
    return {
        "id": proposal.id,
        "tenant_id": proposal.tenant_id,
        "repo_id": proposal.repo_id,
        "proposal_type": proposal.proposal_type,
        "risk": proposal.risk,
        "status": proposal.status,
        "summary": proposal.summary,
        "evidence_refs": proposal.evidence_refs,
        "expected_benefit": proposal.expected_benefit,
        "affected_feature_ids": proposal.affected_feature_ids,
        "conversion_target": proposal.conversion_target,
        "forbidden_direct_actions": proposal.forbidden_direct_actions,
        "suggested_validation": proposal.suggested_validation,
        "role_metadata": proposal.role_metadata,
        "judge_state": proposal.judge_state or {"status": "pending"},
        "operator_state": proposal.operator_state or {"status": "pending"},
        "judge_decision": proposal.judge_decision,
        "operator_decision": proposal.operator_decision,
        "operator_action_history": operator_history,
        "validator_errors": proposal.validator_errors,
        "created_at": proposal.created_at,
        "updated_at": proposal.updated_at,
    }


def build_dreaming_observability_summary(
    db: SessionDB,
    *,
    tenant_id: Optional[str] = None,
    repo_id: Optional[str] = None,
    status: Optional[str] = None,
    proposal_type: Optional[str] = None,
    risk: Optional[str] = None,
) -> Dict[str, Any]:
    rows = list_dreaming_proposals(
        db,
        tenant_id=tenant_id,
        repo_id=repo_id,
        status=status,
        proposal_type=proposal_type,
        risk=risk,
        limit=1000,
    )

    def _counts(attr: str) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for row in rows:
            key = str(getattr(row, attr) or "unknown")
            counts[key] = counts.get(key, 0) + 1
        return dict(sorted(counts.items()))

    return {
        "tenant_id": tenant_id,
        "repo_id": repo_id,
        "total": len(rows),
        "by_status": _counts("status"),
        "by_proposal_type": _counts("proposal_type"),
        "by_risk": _counts("risk"),
        "pending_review": sum(1 for row in rows if row.status in {"proposed", "judged", "needs_human"}),
        "converted": sum(1 for row in rows if row.status == "converted"),
    }


def list_dreaming_proposals(
    db: SessionDB,
    *,
    tenant_id: Optional[str] = None,
    repo_id: Optional[str] = None,
    status: Optional[str] = None,
    proposal_type: Optional[str] = None,
    risk: Optional[str] = None,
    limit: int = 50,
) -> List[DreamingProposal]:
    ensure_dreaming_schema(db)
    clauses: List[str] = []
    params: List[Any] = []
    for key, value in (
        ("tenant_id", tenant_id),
        ("repo_id", repo_id),
        ("status", status),
        ("proposal_type", proposal_type),
        ("risk", risk),
    ):
        if value is not None:
            clauses.append(f"{key} = ?")
            params.append(value)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = db._conn.execute(
        f"""
        SELECT * FROM hermes_dreaming_proposals
        {where}
        ORDER BY updated_at DESC
        LIMIT ?
        """,
        (*params, max(1, int(limit))),
    ).fetchall()
    return [_row_to_proposal(row) for row in rows]


def get_dreaming_proposal(db: SessionDB, proposal_id: str) -> Optional[DreamingProposal]:
    ensure_dreaming_schema(db)
    row = db._conn.execute("SELECT * FROM hermes_dreaming_proposals WHERE id = ?", (proposal_id,)).fetchone()
    return _row_to_proposal(row) if row is not None else None


def judge_dreaming_proposal(
    db: SessionDB,
    *,
    proposal_id: str,
    decision: str,
    confidence: float = 1.0,
    rationale: str = "",
) -> DreamingActionResult:
    proposal = get_dreaming_proposal(db, proposal_id)
    if proposal is None:
        raise ValueError(f"unknown dreaming proposal: {proposal_id}")
    if decision not in {"approve", "reject", "needs_human"}:
        raise ValueError(f"invalid judge decision: {decision}")
    proposal.judge_decision = {
        "decision": decision,
        "confidence": float(confidence),
        "rationale": rationale or f"judge decision: {decision}",
        "created_at": _now(),
    }
    proposal.judge_state = {
        "status": "approved" if decision == "approve" else decision,
        "decision": decision,
        "confidence": float(confidence),
        "rationale": rationale or f"judge decision: {decision}",
        "created_at": proposal.judge_decision["created_at"],
    }
    proposal.status = "judged" if decision == "approve" else ("rejected" if decision == "reject" else "needs_human")
    saved = upsert_dreaming_proposal(db, proposal)
    return DreamingActionResult(proposal_id=proposal_id, status=saved.status, proposal=saved.to_dict())


def approve_dreaming_proposal(
    db: SessionDB,
    *,
    proposal_id: str,
    operator: str = "operator",
    approver_role: str = "operator",
    convert_candidate: bool = False,
) -> DreamingActionResult:
    proposal = get_dreaming_proposal(db, proposal_id)
    if proposal is None:
        raise ValueError(f"unknown dreaming proposal: {proposal_id}")
    judge = proposal.judge_decision or {}
    if judge.get("decision") != "approve":
        raise ValueError("dreaming proposal requires judge approval before operator approval")
    proposal.operator_decision = {
        "decision": "approve",
        "operator": operator,
        "role": approver_role,
        "created_at": _now(),
    }
    proposal.operator_state = {
        "status": "approved",
        "decision": "approve",
        "operator": operator,
        "role": approver_role,
        "created_at": proposal.operator_decision["created_at"],
    }
    proposal.status = "approved"
    converted_id = None
    if convert_candidate:
        converted_id = convert_dreaming_proposal_to_candidate(db, proposal)
        proposal.converted_candidate_id = converted_id
        proposal.status = "converted"
    saved = upsert_dreaming_proposal(db, proposal)
    return DreamingActionResult(
        proposal_id=proposal_id,
        status=saved.status,
        converted_candidate_id=converted_id,
        proposal=saved.to_dict(),
    )


def reject_dreaming_proposal(
    db: SessionDB,
    *,
    proposal_id: str,
    reason: str = "operator rejected",
) -> DreamingActionResult:
    proposal = get_dreaming_proposal(db, proposal_id)
    if proposal is None:
        raise ValueError(f"unknown dreaming proposal: {proposal_id}")
    proposal.operator_decision = {
        "decision": "reject",
        "reason": reason,
        "created_at": _now(),
    }
    proposal.operator_state = {
        "status": "rejected",
        "decision": "reject",
        "reason": reason,
        "created_at": proposal.operator_decision["created_at"],
    }
    proposal.status = "rejected"
    saved = upsert_dreaming_proposal(db, proposal)
    return DreamingActionResult(proposal_id=proposal_id, status=saved.status, proposal=saved.to_dict())


def _validate_conversion_gates(proposal: DreamingProposal) -> None:
    if proposal.validator_errors:
        raise ValueError("deterministic validator acceptance required before conversion")
    validation = validate_dreaming_proposal_details(proposal, known_evidence_refs=proposal.evidence_refs)
    if not validation.accepted:
        raise ValueError("deterministic validator acceptance required before conversion")
    if proposal.judge_decision.get("decision") != "approve":
        raise ValueError("judge approval required before conversion")
    if proposal.operator_decision.get("decision") != "approve":
        raise ValueError("operator approval required before conversion")
    role = str(proposal.operator_decision.get("role") or "operator").strip().lower()
    if role not in {"operator", "tenant-admin"}:
        raise ValueError("operator or tenant-admin approval required before conversion")


def convert_dreaming_proposal(
    db: SessionDB,
    *,
    proposal_id: str,
) -> DreamingActionResult:
    proposal = get_dreaming_proposal(db, proposal_id)
    if proposal is None:
        raise ValueError(f"unknown dreaming proposal: {proposal_id}")
    _validate_conversion_gates(proposal)
    converted_id = convert_dreaming_proposal_to_candidate(db, proposal)
    proposal.converted_candidate_id = converted_id
    proposal.status = "converted"
    proposal.operator_state = {
        **(proposal.operator_state or {}),
        "status": "converted",
        "converted_candidate_id": converted_id,
        "converted_at": _now(),
    }
    saved = upsert_dreaming_proposal(db, proposal)
    return DreamingActionResult(
        proposal_id=proposal_id,
        status=saved.status,
        converted_candidate_id=converted_id,
        proposal=saved.to_dict(),
    )


def convert_dreaming_proposal_to_candidate(db: SessionDB, proposal: DreamingProposal) -> str:
    _validate_conversion_gates(proposal)
    candidate_id = _stable_id("dreamcand", proposal.id, proposal.proposal_type)
    db.upsert_meta_candidate(
        candidate_id=candidate_id,
        kind=f"dreaming_{proposal.proposal_type}",
        claim=proposal.summary,
        evidence_json={
            "source": "dreaming",
            "proposal_id": proposal.id,
            "evidence_refs": proposal.evidence_refs,
            "rationale": proposal.rationale,
            "requested_action": proposal.requested_action,
            "scope": proposal.scope,
            "risk": proposal.risk,
            "judge_decision": proposal.judge_decision,
            "operator_decision": proposal.operator_decision,
            "runtime_effect": False,
            "affected_feature_ids": proposal.affected_feature_ids,
            "conversion_target": proposal.conversion_target,
            "expected_benefit": proposal.expected_benefit,
            "forbidden_direct_actions": proposal.forbidden_direct_actions,
            "suggested_validation": proposal.suggested_validation,
            "role_metadata": proposal.role_metadata,
            "evidence_packets": proposal.evidence_packets,
        },
        score=0.7 if proposal.risk == "low" else 0.5,
        status="proposed",
        tenant_id=proposal.tenant_id,
        repo_id=proposal.repo_id,
    )
    return candidate_id
