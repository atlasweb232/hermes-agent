"""Global Memory Wiki primitives.

This module intentionally implements the local, deterministic substrate first:
config loading, proposal metadata validation, idempotency keys, a bus adapter
interface with SQLite and Kafka-compatible boundaries, and dedupe classification.
Infrastructure deployment remains outside the Hermes package.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
import re
import time
from typing import Any, Dict, Iterable, List, MutableMapping, Optional, Protocol, Sequence

from hermes_state import SessionDB


GLOBAL_TOPICS = {
    "proposed": "proposed",
    "normalized": "normalized",
    "dedupe_requested": "dedupe.requested",
    "dedupe_completed": "dedupe.completed",
    "reconcile_requested": "reconcile.requested",
    "judge_requested": "judge.requested",
    "judge_completed": "judge.completed",
    "canonical_updated": "canonical.updated",
    "index_requested": "index.requested",
    "index_completed": "index.completed",
    "sync_delta": "sync.delta",
    "dead_letter": "dead_letter",
}

REQUIRED_PROPOSAL_FIELDS = {
    "id",
    "source_instance_id",
    "source_session_id",
    "domain",
    "scope",
    "visibility",
    "sensitivity",
    "claim_type",
    "language",
    "normalized_text",
    "evidence_refs",
    "created_at",
}

VALID_SCOPES = {"private", "device", "tenant", "domain", "global"}
VALID_VISIBILITIES = {"private", "shared", "global_candidate"}
VALID_SENSITIVITY = {"public", "internal", "confidential", "secret"}
VALID_DEDUPE_CLASSES = {
    "exact_duplicate",
    "near_duplicate",
    "same_evidence",
    "same_topic",
    "conflict",
    "supersedes",
    "canonical_new",
}


def _now() -> float:
    return time.time()


def _normalize_text(text: str) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip().casefold()
    text = re.sub(r"[^\w\s:/.-]", "", text)
    return text


def stable_hash(value: Any) -> str:
    if isinstance(value, str):
        raw = value
    else:
        raw = json.dumps(value, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def text_hash(text: str) -> str:
    return stable_hash(_normalize_text(text))


def evidence_hash(evidence_refs: Iterable[Any]) -> str:
    refs = sorted(str(ref).strip() for ref in evidence_refs if str(ref).strip())
    return stable_hash(refs)


def simple_simhash(text: str, bits: int = 64) -> str:
    """Small dependency-free simhash for near-duplicate bucketing."""
    tokens = re.findall(r"[\w:/.-]+", _normalize_text(text))
    if not tokens:
        return "0" * (bits // 4)
    weights = [0] * bits
    for token in tokens:
        digest = int(hashlib.sha256(token.encode("utf-8")).hexdigest(), 16)
        for idx in range(bits):
            weights[idx] += 1 if digest & (1 << idx) else -1
    value = 0
    for idx, weight in enumerate(weights):
        if weight >= 0:
            value |= 1 << idx
    return f"{value:0{bits // 4}x}"


def hamming_distance_hex(left: str, right: str) -> int:
    return (int(left or "0", 16) ^ int(right or "0", 16)).bit_count()


@dataclass
class GlobalMemoryProposal:
    id: str
    source_instance_id: str
    source_session_id: str
    domain: str
    scope: str
    visibility: str
    sensitivity: str
    claim_type: str
    language: str
    normalized_text: str
    evidence_refs: List[str]
    created_at: str
    tenant_id: Optional[str] = None
    user_id_hash: Optional[str] = None
    source_event_id: Optional[str] = None
    title: str = ""
    text_hash: str = ""
    simhash: str = ""
    embedding_id: str = ""
    graph_keys: List[str] = field(default_factory=list)
    entities: List[str] = field(default_factory=list)
    citation_refs: List[str] = field(default_factory=list)
    confidence: float = 0.0
    approval_state: str = "proposed"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ValidationResult:
    valid: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DedupeDecision:
    proposal_id: str
    dedupe_class: str
    matched_id: Optional[str] = None
    score: float = 0.0
    reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class GlobalIndexFanoutResult:
    status: str
    claim_id: str
    lexical_indexed: bool = False
    graph_nodes: int = 0
    graph_edges: int = 0
    vector_payload: Dict[str, Any] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DiscussionMemoryRecord:
    id: str
    record_type: str
    title: str
    summary: str
    scope: str
    domain: str
    sensitivity: str
    source_session_id: Optional[str] = None
    tenant_id: Optional[str] = None
    evidence_refs: List[str] = field(default_factory=list)
    citation_refs: List[str] = field(default_factory=list)
    claims: List[str] = field(default_factory=list)
    approval_state: str = "proposed"
    producer_invocation_id: Optional[str] = None
    judge_invocation_id: Optional[str] = None
    operator_approved: bool = False
    created_at: float = field(default_factory=_now)
    updated_at: float = field(default_factory=_now)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DiscussionSidecarDefinition:
    name: str
    mode: str
    llm_role: Optional[str]
    input_topic: str
    output_topic: str
    interval_seconds: int
    timeout_seconds: int
    lease_seconds: int

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DreamingSidecarDefinition:
    name: str
    scope: str
    enabled: bool
    llm_role: str
    input_topic: str
    output_topic: str
    source: str
    interval_seconds: int
    timeout_seconds: int
    lease_seconds: int
    require_judge: bool
    require_operator_approval: bool
    allow_private_raw_logs: bool
    mutates_runtime_state: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class GlobalPreCurationEvent:
    event_id: str
    tenant_id: Optional[str] = None
    repo_id: Optional[str] = None
    task_type: str = ""
    tool: str = ""
    worker_kind: str = ""
    failure_signature: str = ""
    success_signature: str = ""
    scope_signature: str = ""
    evidence_signature: str = ""
    normalized_text: str = ""
    sensitivity: str = "internal"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class GlobalPreCurationDecision:
    action: str
    reason: str
    metric: str
    should_run_expensive_curator: bool
    local_confirmation_required: bool = False
    global_claim_id: Optional[str] = None
    confidence: float = 0.0
    matched_claim: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class GlobalLessonRecord:
    id: str
    approval_state: str
    scope: str
    sensitivity: str
    visibility: str
    claim_type: str
    normalized_text: str
    tenant_id: Optional[str] = None
    repo_id: Optional[str] = None
    tool: str = ""
    task_type: str = ""
    worker_kind: str = ""
    failure_signature: str = ""
    success_signature: str = ""
    scope_signature: str = ""
    evidence_signature: str = ""
    text_hash: str = ""
    simhash: str = ""
    confidence: float = 0.0
    reuse_stats: Dict[str, int] = field(default_factory=dict)
    approval_provenance: Dict[str, Any] = field(default_factory=dict)
    evidence_refs: List[str] = field(default_factory=list)
    citation_refs: List[str] = field(default_factory=list)
    cross_tenant_shareable: bool = False
    created_at: float = field(default_factory=_now)
    updated_at: float = field(default_factory=_now)
    retired_at: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class GlobalLessonRetrievalAudit:
    query_id: str
    event_id: str
    considered: int = 0
    returned: int = 0
    exact_matches: int = 0
    near_matches: int = 0
    rejected: List[Dict[str, Any]] = field(default_factory=list)
    matched: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class GlobalLessonRetrievalResult:
    lessons: List[Dict[str, Any]]
    audit: GlobalLessonRetrievalAudit

    def to_dict(self) -> Dict[str, Any]:
        return {"lessons": self.lessons, "audit": self.audit.to_dict()}


@dataclass
class PersistedPreCurationResult:
    decision: GlobalPreCurationDecision
    retrieval: GlobalLessonRetrievalResult
    metrics: Dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "decision": self.decision.to_dict(),
            "retrieval": self.retrieval.to_dict(),
            "metrics": dict(self.metrics),
        }


@dataclass
class GlobalHotCacheEntry:
    id: str
    global_lesson_id: str
    tenant_id: Optional[str]
    repo_id: Optional[str]
    scope: str
    sensitivity: str
    tool: str
    task_type: str
    worker_kind: str
    failure_signature: str
    success_signature: str
    compact_text: str
    confidence: float
    evidence_refs: List[str] = field(default_factory=list)
    reuse_stats: Dict[str, int] = field(default_factory=dict)
    created_at: float = field(default_factory=_now)
    updated_at: float = field(default_factory=_now)
    last_used_at: Optional[float] = None
    expires_at: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class HydratedMemoryPacket:
    packet_id: str
    event_id: str
    status: str
    hot_cache_hits: List[Dict[str, Any]] = field(default_factory=list)
    global_lessons: List[Dict[str, Any]] = field(default_factory=list)
    local_claims: List[Dict[str, Any]] = field(default_factory=list)
    advisory_items: List[Dict[str, Any]] = field(default_factory=list)
    estimated_tokens: int = 0
    token_budget: int = 800
    retrieval_audit: Dict[str, Any] = field(default_factory=dict)
    materialized: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class GlobalMemoryBus(Protocol):
    def publish(self, topic: str, payload: Dict[str, Any], *, event_key: str) -> Dict[str, Any]:
        ...


def build_global_topic(config: Dict[str, Any], topic: str) -> str:
    bus = ((config or {}).get("supervisor") or {}).get("global_memory_bus") or {}
    prefix = str(bus.get("topic_prefix") or "hermes.memory").strip().rstrip(".")
    suffix = GLOBAL_TOPICS.get(topic, topic).strip(".")
    return f"{prefix}.{suffix}"


def build_idempotency_key(proposal: Dict[str, Any]) -> str:
    evidence_refs = proposal.get("evidence_refs") or []
    parts = [
        proposal.get("source_instance_id") or "",
        proposal.get("source_session_id") or "",
        proposal.get("source_event_id") or "",
        proposal.get("text_hash") or text_hash(str(proposal.get("normalized_text") or "")),
        proposal.get("evidence_hash") or evidence_hash(evidence_refs),
    ]
    return stable_hash("|".join(str(part) for part in parts))


def normalize_proposal(raw: Dict[str, Any]) -> GlobalMemoryProposal:
    data = dict(raw or {})
    normalized_text = _normalize_text(str(data.get("normalized_text") or data.get("claim") or ""))
    evidence_refs = [str(ref) for ref in (data.get("evidence_refs") or []) if str(ref).strip()]
    return GlobalMemoryProposal(
        id=str(data.get("id") or f"gmp_{stable_hash([data.get('source_instance_id'), normalized_text])[:16]}"),
        source_instance_id=str(data.get("source_instance_id") or ""),
        source_session_id=str(data.get("source_session_id") or ""),
        source_event_id=str(data.get("source_event_id") or "") or None,
        tenant_id=str(data.get("tenant_id") or "") or None,
        user_id_hash=str(data.get("user_id_hash") or "") or None,
        domain=str(data.get("domain") or ""),
        scope=str(data.get("scope") or ""),
        visibility=str(data.get("visibility") or ""),
        sensitivity=str(data.get("sensitivity") or ""),
        claim_type=str(data.get("claim_type") or ""),
        language=str(data.get("language") or "en"),
        title=str(data.get("title") or "")[:240],
        normalized_text=normalized_text,
        text_hash=str(data.get("text_hash") or text_hash(normalized_text)),
        simhash=str(data.get("simhash") or simple_simhash(normalized_text)),
        embedding_id=str(data.get("embedding_id") or ""),
        graph_keys=[str(item) for item in (data.get("graph_keys") or []) if str(item).strip()],
        entities=[str(item) for item in (data.get("entities") or []) if str(item).strip()],
        evidence_refs=evidence_refs,
        citation_refs=[str(item) for item in (data.get("citation_refs") or []) if str(item).strip()],
        created_at=str(data.get("created_at") or _now()),
        confidence=float(data.get("confidence") or 0.0),
        approval_state=str(data.get("approval_state") or "proposed"),
    )


def validate_proposal(proposal: Dict[str, Any]) -> ValidationResult:
    errors: List[str] = []
    warnings: List[str] = []
    missing = sorted(field for field in REQUIRED_PROPOSAL_FIELDS if not proposal.get(field))
    if missing:
        errors.append(f"missing required fields: {', '.join(missing)}")
    if proposal.get("scope") not in VALID_SCOPES:
        errors.append(f"invalid scope: {proposal.get('scope')}")
    if proposal.get("visibility") not in VALID_VISIBILITIES:
        errors.append(f"invalid visibility: {proposal.get('visibility')}")
    if proposal.get("sensitivity") not in VALID_SENSITIVITY:
        errors.append(f"invalid sensitivity: {proposal.get('sensitivity')}")
    if proposal.get("scope") == "global" and proposal.get("visibility") != "global_candidate":
        errors.append("global scope requires visibility=global_candidate before approval")
    if proposal.get("sensitivity") == "secret" and proposal.get("visibility") != "private":
        errors.append("secret proposals must remain private")
    if not proposal.get("evidence_refs"):
        errors.append("at least one evidence_ref is required")
    if proposal.get("confidence") is not None:
        try:
            confidence = float(proposal.get("confidence"))
            if confidence < 0 or confidence > 1:
                errors.append("confidence must be between 0 and 1")
        except (TypeError, ValueError):
            errors.append("confidence must be numeric")
    if not proposal.get("citation_refs"):
        warnings.append("no citation_refs supplied")
    return ValidationResult(valid=not errors, errors=errors, warnings=warnings)


class SQLiteGlobalMemoryBus:
    """Global bus adapter backed by the existing local durable learning bus."""

    def __init__(self, db: SessionDB, config: Optional[Dict[str, Any]] = None):
        self.db = db
        self.config = config or {}

    def publish(self, topic: str, payload: Dict[str, Any], *, event_key: str) -> Dict[str, Any]:
        from hermes_cli.learning_bus import publish_learning_event

        event = publish_learning_event(
            self.db,
            topic=build_global_topic(self.config, topic),
            payload=payload,
            tenant_id=payload.get("tenant_id"),
            repo_id=payload.get("repo_id"),
            event_key=event_key,
        )
        return {"backend": "sqlite", "event": event.to_dict()}


class KafkaGlobalMemoryBus:
    """Kafka/Redpanda-compatible adapter boundary.

    The dependency is optional so local Hermes installs do not pull Kafka
    clients. Production deployments can install confluent-kafka or replace this
    adapter behind the same publish contract.
    """

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        try:
            from confluent_kafka import Producer  # type: ignore
        except Exception as exc:  # pragma: no cover - dependency intentionally optional
            raise RuntimeError("Kafka global memory bus requires optional dependency confluent-kafka") from exc
        bus = ((config or {}).get("supervisor") or {}).get("global_memory_bus") or {}
        brokers = bus.get("brokers") or []
        if not brokers:
            raise RuntimeError("Kafka global memory bus requires supervisor.global_memory_bus.brokers")
        self._producer = Producer({"bootstrap.servers": ",".join(brokers)})

    def publish(self, topic: str, payload: Dict[str, Any], *, event_key: str) -> Dict[str, Any]:  # pragma: no cover
        resolved = build_global_topic(self.config, topic)
        self._producer.produce(
            resolved,
            key=event_key.encode("utf-8"),
            value=json.dumps(payload, sort_keys=True).encode("utf-8"),
        )
        self._producer.flush()
        return {"backend": "kafka", "topic": resolved, "event_key": event_key}


def get_global_memory_bus(db: SessionDB, config: Dict[str, Any]) -> GlobalMemoryBus:
    bus = ((config or {}).get("supervisor") or {}).get("global_memory_bus") or {}
    backend = str(bus.get("backend") or "sqlite").lower()
    if backend == "sqlite":
        return SQLiteGlobalMemoryBus(db, config)
    if backend in {"kafka", "redpanda"}:
        return KafkaGlobalMemoryBus(config)
    raise ValueError(f"unsupported global memory bus backend: {backend}")


def discussion_storage_config(config: Dict[str, Any]) -> Dict[str, Any]:
    supervisor = (config or {}).get("supervisor") or {}
    raw = supervisor.get("discussion_memory_wiki") or {}
    storage = raw.get("storage") if isinstance(raw, dict) else {}
    defaults = {
        "root": "~/.hermes/memory-wiki",
        "backend": "local",
        "max_local_gb": 50,
        "raw_retention_days": 30,
        "hot_cache_days": 30,
        "state_uri": "~/.hermes/memory-wiki/discussions/state.sqlite",
        "lexical_index_uri": "~/.hermes/memory-wiki/discussions/lexical.sqlite",
        "vector_backend": "disabled",
        "graph_backend": "sqlite",
    }
    if isinstance(storage, dict):
        defaults.update(storage)
    return defaults


def discussion_sidecar_definitions(config: Dict[str, Any]) -> List[DiscussionSidecarDefinition]:
    supervisor = (config or {}).get("supervisor") or {}
    raw = supervisor.get("discussion_memory_wiki") or {}
    sidecars = raw.get("sidecars") if isinstance(raw, dict) else {}

    specs = {
        "discussion_capture": ("llm", "discussion_capture", "discussion.raw", "discussion.captured"),
        "claim_extractor": ("llm", "claim_extractor", "discussion.captured", "discussion.claims"),
        "citation_validator": ("deterministic_first", "citation_validator", "discussion.claims", "discussion.citations_validated"),
        "wiki_compiler": ("llm", "wiki_compiler", "discussion.citations_validated", "discussion.compiled"),
        "indexer": ("programmatic", None, "discussion.compiled", "discussion.indexed"),
        "sync": ("programmatic", None, "discussion.indexed", "discussion.synced"),
    }
    result: List[DiscussionSidecarDefinition] = []
    for name, (mode, role, input_topic, output_topic) in specs.items():
        cfg = sidecars.get(name, {}) if isinstance(sidecars, dict) and isinstance(sidecars.get(name), dict) else {}
        result.append(
            DiscussionSidecarDefinition(
                name=name,
                mode=str(cfg.get("mode") or mode),
                llm_role=role,
                input_topic=input_topic,
                output_topic=output_topic,
                interval_seconds=int(cfg.get("interval_seconds") or 300),
                timeout_seconds=int(cfg.get("timeout_seconds") or 120),
                lease_seconds=int(cfg.get("lease_seconds") or 300),
            )
        )
    return result


def dreaming_sidecar_definitions(config: Dict[str, Any]) -> List[DreamingSidecarDefinition]:
    supervisor = (config or {}).get("supervisor") or {}
    local_cfg = supervisor.get("dreaming") if isinstance(supervisor.get("dreaming"), dict) else {}
    global_cfg = supervisor.get("global_dreaming") if isinstance(supervisor.get("global_dreaming"), dict) else {}

    return [
        DreamingSidecarDefinition(
            name="local_dreaming",
            scope="tenant_repo",
            enabled=bool(local_cfg.get("enabled", False)),
            llm_role="dreaming",
            input_topic="memory.local.approved",
            output_topic="memory.local.dreaming.proposed",
            source=str(local_cfg.get("source") or "approved_local_memory"),
            interval_seconds=int(local_cfg.get("interval_seconds") or 3600),
            timeout_seconds=int(local_cfg.get("timeout_seconds") or 300),
            lease_seconds=int(local_cfg.get("lease_seconds") or 300),
            require_judge=bool(local_cfg.get("require_judge", True)),
            require_operator_approval=bool(local_cfg.get("require_operator_approval", True)),
            allow_private_raw_logs=bool(local_cfg.get("allow_private_raw_logs", False)),
        ),
        DreamingSidecarDefinition(
            name="global_dreaming",
            scope="global_redacted",
            enabled=bool(global_cfg.get("enabled", False)),
            llm_role="global_dreaming",
            input_topic="memory.global.canonical.approved",
            output_topic="memory.global.dreaming.proposed",
            source=str(global_cfg.get("source") or "approved_shareable_global_memory"),
            interval_seconds=int(global_cfg.get("interval_seconds") or 21600),
            timeout_seconds=int(global_cfg.get("timeout_seconds") or 300),
            lease_seconds=int(global_cfg.get("lease_seconds") or 600),
            require_judge=bool(global_cfg.get("require_judge", True)),
            require_operator_approval=bool(global_cfg.get("require_operator_approval", True)),
            allow_private_raw_logs=bool(global_cfg.get("allow_private_raw_logs", False)),
        ),
    ]


def _precuration_config(config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    supervisor = (config or {}).get("supervisor") or {}
    wiki = supervisor.get("global_memory_wiki") if isinstance(supervisor.get("global_memory_wiki"), dict) else {}
    raw = wiki.get("precuration") if isinstance(wiki.get("precuration"), dict) else {}
    defaults = {
        "enabled": True,
        "near_hamming_distance": 8,
        "min_near_confidence": 0.75,
        "skip_expensive_curator_on_exact": True,
        "skip_expensive_curator_on_near": True,
    }
    defaults.update(raw)
    return defaults


def _as_precuration_event(event: GlobalPreCurationEvent | Dict[str, Any]) -> GlobalPreCurationEvent:
    if isinstance(event, GlobalPreCurationEvent):
        return event
    data = dict(event or {})
    return GlobalPreCurationEvent(
        event_id=str(data.get("event_id") or data.get("id") or f"event_{stable_hash(data)[:16]}"),
        tenant_id=str(data.get("tenant_id") or "") or None,
        repo_id=str(data.get("repo_id") or "") or None,
        task_type=str(data.get("task_type") or ""),
        tool=str(data.get("tool") or ""),
        worker_kind=str(data.get("worker_kind") or ""),
        failure_signature=str(data.get("failure_signature") or ""),
        success_signature=str(data.get("success_signature") or ""),
        scope_signature=str(data.get("scope_signature") or ""),
        evidence_signature=str(data.get("evidence_signature") or ""),
        normalized_text=_normalize_text(str(data.get("normalized_text") or data.get("text") or data.get("claim") or "")),
        sensitivity=str(data.get("sensitivity") or "internal"),
        metadata=data.get("metadata") if isinstance(data.get("metadata"), dict) else {},
    )


def _lesson_is_usable_for_event(event: GlobalPreCurationEvent, lesson: Dict[str, Any]) -> bool:
    status = str(lesson.get("approval_state") or lesson.get("status") or "").lower()
    if status not in {"approved", "canonical", "applied"}:
        return False
    sensitivity = str(lesson.get("sensitivity") or "").lower()
    if sensitivity == "secret":
        return False
    lesson_tenant = str(lesson.get("tenant_id") or "")
    shareable = bool(
        lesson.get("cross_tenant_shareable")
        or lesson.get("global_shareable")
        or lesson.get("shareable")
        or str(lesson.get("scope") or "").lower() == "global"
    )
    if lesson_tenant and event.tenant_id and lesson_tenant != event.tenant_id and not shareable:
        return False
    if sensitivity == "confidential" and lesson_tenant and event.tenant_id != lesson_tenant and not shareable:
        return False
    return True


def _lesson_confidence(lesson: Dict[str, Any]) -> float:
    try:
        return float(lesson.get("confidence", lesson.get("score", 0.0)) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def _as_json_dict(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return dict(parsed) if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


def _exact_lesson_match(event: GlobalPreCurationEvent, lesson: Dict[str, Any]) -> bool:
    for key in ("failure_signature", "success_signature", "scope_signature", "evidence_signature"):
        event_value = str(getattr(event, key) or "")
        lesson_value = str(lesson.get(key) or "")
        if event_value and lesson_value and event_value == lesson_value:
            return True
    if event.normalized_text:
        lesson_text_hash = str(lesson.get("text_hash") or "")
        if lesson_text_hash and lesson_text_hash == text_hash(event.normalized_text):
            return True
    return False


def _near_lesson_match(event: GlobalPreCurationEvent, lesson: Dict[str, Any], *, max_distance: int) -> bool:
    if not event.normalized_text:
        return False
    lesson_simhash = str(lesson.get("simhash") or "")
    if not lesson_simhash:
        lesson_text = str(lesson.get("normalized_text") or lesson.get("claim") or "")
        if not lesson_text:
            return False
        lesson_simhash = simple_simhash(lesson_text)
    return hamming_distance_hex(simple_simhash(event.normalized_text), lesson_simhash) <= max_distance


def _normalize_global_lesson(raw: Dict[str, Any]) -> GlobalLessonRecord:
    data = dict(raw or {})
    normalized_text = _normalize_text(str(data.get("normalized_text") or data.get("claim") or ""))
    lesson_id = str(data.get("id") or data.get("lesson_id") or f"glesson_{stable_hash(data)[:16]}")
    confidence = _lesson_confidence(data)
    created_at = data.get("created_at")
    updated_at = data.get("updated_at")
    retired_at = data.get("retired_at")
    return GlobalLessonRecord(
        id=lesson_id,
        tenant_id=str(data.get("tenant_id") or "") or None,
        repo_id=str(data.get("repo_id") or "") or None,
        approval_state=str(data.get("approval_state") or data.get("status") or "approved"),
        scope=str(data.get("scope") or "global"),
        sensitivity=str(data.get("sensitivity") or "internal"),
        visibility=str(data.get("visibility") or "global_candidate"),
        claim_type=str(data.get("claim_type") or data.get("kind") or "lesson"),
        tool=str(data.get("tool") or ""),
        task_type=str(data.get("task_type") or ""),
        worker_kind=str(data.get("worker_kind") or ""),
        failure_signature=str(data.get("failure_signature") or ""),
        success_signature=str(data.get("success_signature") or ""),
        scope_signature=str(data.get("scope_signature") or ""),
        evidence_signature=str(data.get("evidence_signature") or ""),
        normalized_text=normalized_text,
        text_hash=str(data.get("text_hash") or text_hash(normalized_text)),
        simhash=str(data.get("simhash") or simple_simhash(normalized_text)),
        confidence=confidence,
        reuse_stats={str(k): int(v) for k, v in _as_json_dict(data.get("reuse_stats")).items()},
        approval_provenance=_as_json_dict(data.get("approval_provenance")),
        evidence_refs=_json_list(data.get("evidence_refs") or data.get("evidence_refs_json") or []),
        citation_refs=_json_list(data.get("citation_refs") or data.get("citation_refs_json") or []),
        cross_tenant_shareable=_as_bool(
            data.get("cross_tenant_shareable")
            if "cross_tenant_shareable" in data
            else data.get("global_shareable", data.get("shareable", False))
        ),
        created_at=float(created_at or _now()),
        updated_at=float(updated_at or _now()),
        retired_at=float(retired_at) if retired_at not in {None, ""} else None,
    )


def ensure_global_lesson_schema(db: SessionDB) -> None:
    def _do(conn):
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS hermes_global_lessons (
                id TEXT PRIMARY KEY,
                tenant_id TEXT,
                repo_id TEXT,
                approval_state TEXT NOT NULL,
                scope TEXT NOT NULL,
                sensitivity TEXT NOT NULL,
                visibility TEXT NOT NULL,
                claim_type TEXT NOT NULL,
                tool TEXT,
                task_type TEXT,
                worker_kind TEXT,
                failure_signature TEXT,
                success_signature TEXT,
                scope_signature TEXT,
                evidence_signature TEXT,
                normalized_text TEXT NOT NULL,
                text_hash TEXT NOT NULL,
                simhash TEXT NOT NULL,
                confidence REAL NOT NULL DEFAULT 0,
                reuse_stats_json TEXT,
                approval_provenance_json TEXT,
                evidence_refs_json TEXT,
                citation_refs_json TEXT,
                cross_tenant_shareable INTEGER NOT NULL DEFAULT 0,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                retired_at REAL
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_hermes_global_lessons_exact
                ON hermes_global_lessons(approval_state, sensitivity, failure_signature, success_signature, text_hash)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_hermes_global_lessons_scope
                ON hermes_global_lessons(tenant_id, repo_id, scope, approval_state, retired_at)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_hermes_global_lessons_simhash
                ON hermes_global_lessons(approval_state, simhash, confidence)
            """
        )

    db._execute_write(_do)


def persist_global_lesson(db: SessionDB, lesson: Dict[str, Any]) -> GlobalLessonRecord:
    ensure_global_lesson_schema(db)
    record = _normalize_global_lesson(lesson)
    record.updated_at = _now()

    def _do(conn):
        conn.execute(
            """
            INSERT OR REPLACE INTO hermes_global_lessons (
                id, tenant_id, repo_id, approval_state, scope, sensitivity,
                visibility, claim_type, tool, task_type, worker_kind,
                failure_signature, success_signature, scope_signature,
                evidence_signature, normalized_text, text_hash, simhash,
                confidence, reuse_stats_json, approval_provenance_json,
                evidence_refs_json, citation_refs_json, cross_tenant_shareable,
                created_at, updated_at, retired_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.id,
                record.tenant_id,
                record.repo_id,
                record.approval_state,
                record.scope,
                record.sensitivity,
                record.visibility,
                record.claim_type,
                record.tool,
                record.task_type,
                record.worker_kind,
                record.failure_signature,
                record.success_signature,
                record.scope_signature,
                record.evidence_signature,
                record.normalized_text,
                record.text_hash,
                record.simhash,
                record.confidence,
                json.dumps(record.reuse_stats, sort_keys=True),
                json.dumps(record.approval_provenance, sort_keys=True),
                json.dumps(record.evidence_refs, sort_keys=True),
                json.dumps(record.citation_refs, sort_keys=True),
                1 if record.cross_tenant_shareable else 0,
                record.created_at,
                record.updated_at,
                record.retired_at,
            ),
        )

    db._execute_write(_do)
    return record


def ensure_global_hot_cache_schema(db: SessionDB) -> None:
    def _do(conn):
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS hermes_global_hot_cache (
                id TEXT PRIMARY KEY,
                global_lesson_id TEXT NOT NULL,
                tenant_id TEXT,
                repo_id TEXT,
                scope TEXT NOT NULL,
                sensitivity TEXT NOT NULL,
                tool TEXT,
                task_type TEXT,
                worker_kind TEXT,
                failure_signature TEXT,
                success_signature TEXT,
                compact_text TEXT NOT NULL,
                confidence REAL NOT NULL DEFAULT 0,
                evidence_refs_json TEXT,
                reuse_stats_json TEXT,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                last_used_at REAL,
                expires_at REAL
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_hermes_global_hot_cache_exact
                ON hermes_global_hot_cache(tenant_id, repo_id, failure_signature, success_signature, expires_at)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_hermes_global_hot_cache_scope
                ON hermes_global_hot_cache(tenant_id, repo_id, scope, sensitivity, updated_at DESC)
            """
        )

    db._execute_write(_do)


def _compact_lesson_text(lesson: Dict[str, Any], max_chars: int = 360) -> str:
    text = str(lesson.get("compact_text") or lesson.get("normalized_text") or lesson.get("claim") or "").strip()
    if not text:
        failed = str(lesson.get("failure_signature") or lesson.get("failed_path") or "prior failure")
        success = str(lesson.get("success_signature") or lesson.get("working_path") or "known working path")
        text = f"Known lesson: when {failed} appears, prefer {success}."
    text = re.sub(r"\s+", " ", text)
    return text[:max_chars]


def _hot_cache_entry_from_row(row: Any) -> Dict[str, Any]:
    data = dict(row)
    return GlobalHotCacheEntry(
        id=data["id"],
        global_lesson_id=data["global_lesson_id"],
        tenant_id=data.get("tenant_id"),
        repo_id=data.get("repo_id"),
        scope=data["scope"],
        sensitivity=data["sensitivity"],
        tool=data.get("tool") or "",
        task_type=data.get("task_type") or "",
        worker_kind=data.get("worker_kind") or "",
        failure_signature=data.get("failure_signature") or "",
        success_signature=data.get("success_signature") or "",
        compact_text=data["compact_text"],
        confidence=float(data.get("confidence") or 0.0),
        evidence_refs=_json_list(data.get("evidence_refs_json")),
        reuse_stats={str(k): int(v) for k, v in _as_json_dict(data.get("reuse_stats_json")).items()},
        created_at=float(data.get("created_at") or 0.0),
        updated_at=float(data.get("updated_at") or 0.0),
        last_used_at=float(data["last_used_at"]) if data.get("last_used_at") is not None else None,
        expires_at=float(data["expires_at"]) if data.get("expires_at") is not None else None,
    ).to_dict()


def materialize_global_lesson_to_hot_cache(
    db: SessionDB,
    lesson: Dict[str, Any],
    event: GlobalPreCurationEvent | Dict[str, Any],
    *,
    ttl_seconds: int = 3600,
) -> GlobalHotCacheEntry:
    ensure_global_hot_cache_schema(db)
    evt = _as_precuration_event(event)
    source_id = str(lesson.get("id") or lesson.get("global_lesson_id") or "")
    cache_id = f"ghot_{stable_hash([source_id, evt.tenant_id, evt.repo_id, evt.task_type, evt.tool])[:16]}"
    now = _now()
    entry = GlobalHotCacheEntry(
        id=cache_id,
        global_lesson_id=source_id,
        tenant_id=evt.tenant_id or lesson.get("tenant_id"),
        repo_id=evt.repo_id or lesson.get("repo_id"),
        scope=str(lesson.get("scope") or "global"),
        sensitivity=str(lesson.get("sensitivity") or "internal"),
        tool=evt.tool or str(lesson.get("tool") or ""),
        task_type=evt.task_type or str(lesson.get("task_type") or ""),
        worker_kind=evt.worker_kind or str(lesson.get("worker_kind") or ""),
        failure_signature=evt.failure_signature or str(lesson.get("failure_signature") or ""),
        success_signature=evt.success_signature or str(lesson.get("success_signature") or ""),
        compact_text=_compact_lesson_text(lesson),
        confidence=_lesson_confidence(lesson),
        evidence_refs=_json_list(lesson.get("evidence_refs") or []),
        reuse_stats=dict(lesson.get("reuse_stats") or {}),
        created_at=now,
        updated_at=now,
        last_used_at=now,
        expires_at=now + int(ttl_seconds),
    )

    def _do(conn):
        conn.execute(
            """
            INSERT OR REPLACE INTO hermes_global_hot_cache (
                id, global_lesson_id, tenant_id, repo_id, scope, sensitivity,
                tool, task_type, worker_kind, failure_signature,
                success_signature, compact_text, confidence, evidence_refs_json,
                reuse_stats_json, created_at, updated_at, last_used_at, expires_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entry.id,
                entry.global_lesson_id,
                entry.tenant_id,
                entry.repo_id,
                entry.scope,
                entry.sensitivity,
                entry.tool,
                entry.task_type,
                entry.worker_kind,
                entry.failure_signature,
                entry.success_signature,
                entry.compact_text,
                entry.confidence,
                json.dumps(entry.evidence_refs, sort_keys=True),
                json.dumps(entry.reuse_stats, sort_keys=True),
                entry.created_at,
                entry.updated_at,
                entry.last_used_at,
                entry.expires_at,
            ),
        )

    db._execute_write(_do)
    return entry


def retrieve_global_hot_cache_for_event(
    db: SessionDB,
    event: GlobalPreCurationEvent | Dict[str, Any],
    *,
    limit: int = 3,
) -> List[Dict[str, Any]]:
    ensure_global_hot_cache_schema(db)
    evt = _as_precuration_event(event)
    now = _now()

    def _fetch(conn):
        rows = conn.execute(
            """
            SELECT * FROM hermes_global_hot_cache
            WHERE (expires_at IS NULL OR expires_at > ?)
            ORDER BY last_used_at DESC, confidence DESC
            LIMIT 200
            """,
            (now,),
        ).fetchall()
        return [_hot_cache_entry_from_row(row) for row in rows]

    rows = db._execute_write(_fetch)
    matches: List[Dict[str, Any]] = []
    for row in rows:
        lesson_like = {
            "id": row["global_lesson_id"],
            "tenant_id": row.get("tenant_id"),
            "repo_id": row.get("repo_id"),
            "status": "approved",
            "scope": row.get("scope"),
            "sensitivity": row.get("sensitivity"),
            "failure_signature": row.get("failure_signature"),
            "success_signature": row.get("success_signature"),
            "confidence": row.get("confidence"),
            "cross_tenant_shareable": str(row.get("scope") or "") == "global",
        }
        ok, _reason = _event_matches_lesson_scope(evt, lesson_like)
        if not ok:
            continue
        if _exact_lesson_match(evt, lesson_like):
            matches.append(row)
    matches.sort(key=lambda item: (-float(item.get("confidence") or 0), str(item.get("id") or "")))
    selected = matches[: max(0, int(limit))]
    if selected:
        ids = [item["id"] for item in selected]

        def _touch(conn):
            ts = _now()
            conn.executemany(
                "UPDATE hermes_global_hot_cache SET last_used_at = ?, updated_at = ? WHERE id = ?",
                [(ts, ts, cache_id) for cache_id in ids],
            )

        db._execute_write(_touch)
    return selected


def _global_lesson_from_row(row: Any) -> Dict[str, Any]:
    data = dict(row)
    return GlobalLessonRecord(
        id=data["id"],
        tenant_id=data.get("tenant_id"),
        repo_id=data.get("repo_id"),
        approval_state=data["approval_state"],
        scope=data["scope"],
        sensitivity=data["sensitivity"],
        visibility=data["visibility"],
        claim_type=data["claim_type"],
        tool=data.get("tool") or "",
        task_type=data.get("task_type") or "",
        worker_kind=data.get("worker_kind") or "",
        failure_signature=data.get("failure_signature") or "",
        success_signature=data.get("success_signature") or "",
        scope_signature=data.get("scope_signature") or "",
        evidence_signature=data.get("evidence_signature") or "",
        normalized_text=data["normalized_text"],
        text_hash=data["text_hash"],
        simhash=data["simhash"],
        confidence=float(data.get("confidence") or 0.0),
        reuse_stats={str(k): int(v) for k, v in _as_json_dict(data.get("reuse_stats_json")).items()},
        approval_provenance=_as_json_dict(data.get("approval_provenance_json")),
        evidence_refs=_json_list(data.get("evidence_refs_json")),
        citation_refs=_json_list(data.get("citation_refs_json")),
        cross_tenant_shareable=bool(data.get("cross_tenant_shareable")),
        created_at=float(data.get("created_at") or 0.0),
        updated_at=float(data.get("updated_at") or 0.0),
        retired_at=float(data["retired_at"]) if data.get("retired_at") is not None else None,
    ).to_dict()


def _event_matches_lesson_scope(event: GlobalPreCurationEvent, lesson: Dict[str, Any]) -> tuple[bool, str]:
    if not _lesson_is_usable_for_event(event, lesson):
        return False, "scope_or_sensitivity_gate"
    repo_id = str(lesson.get("repo_id") or "")
    if repo_id and event.repo_id and repo_id != event.repo_id:
        return False, "repo_mismatch"
    if str(lesson.get("sensitivity") or "").lower() == "secret":
        return False, "secret"
    return True, ""


def retrieve_global_lessons_for_event(
    db: SessionDB,
    event: GlobalPreCurationEvent | Dict[str, Any],
    *,
    config: Optional[Dict[str, Any]] = None,
    limit: int = 5,
) -> GlobalLessonRetrievalResult:
    ensure_global_lesson_schema(db)
    evt = _as_precuration_event(event)
    cfg = _precuration_config(config)
    max_distance = int(cfg.get("near_hamming_distance") or 8)
    min_confidence = float(cfg.get("min_near_confidence") or 0.75)
    query_id = f"glret_{stable_hash([evt.to_dict(), limit])[:16]}"
    audit = GlobalLessonRetrievalAudit(query_id=query_id, event_id=evt.event_id)

    def _fetch(conn):
        rows = conn.execute(
            """
            SELECT * FROM hermes_global_lessons
            WHERE approval_state IN ('approved', 'canonical', 'applied')
              AND retired_at IS NULL
              AND sensitivity != 'secret'
            ORDER BY updated_at DESC
            LIMIT 500
            """
        ).fetchall()
        return [_global_lesson_from_row(row) for row in rows]

    candidates = db._execute_write(_fetch)
    audit.considered = len(candidates)
    ranked: List[tuple[int, float, str, Dict[str, Any]]] = []

    for lesson in candidates:
        ok, reason = _event_matches_lesson_scope(evt, lesson)
        if not ok:
            audit.rejected.append({"id": lesson["id"], "reason": reason})
            continue
        if _exact_lesson_match(evt, lesson):
            audit.exact_matches += 1
            ranked.append((0, 1.0, "exact", lesson))
            audit.matched.append({"id": lesson["id"], "reason": "exact", "score": 1.0})
            continue
        confidence = _lesson_confidence(lesson)
        if confidence >= min_confidence and _near_lesson_match(evt, lesson, max_distance=max_distance):
            distance = hamming_distance_hex(simple_simhash(evt.normalized_text), str(lesson.get("simhash") or "0"))
            score = max(0.0, confidence - (distance / 100.0))
            audit.near_matches += 1
            ranked.append((1, score, "near", lesson))
            audit.matched.append({"id": lesson["id"], "reason": "near", "score": score})
        else:
            audit.rejected.append({"id": lesson["id"], "reason": "no_exact_or_near_match"})

    ranked.sort(key=lambda item: (item[0], -item[1], str(item[3].get("id") or "")))
    lessons = [lesson for _, _, _, lesson in ranked[: max(0, int(limit))]]
    audit.returned = len(lessons)
    return GlobalLessonRetrievalResult(lessons=lessons, audit=audit)


def run_persisted_global_precuration(
    db: SessionDB,
    event: GlobalPreCurationEvent | Dict[str, Any],
    *,
    local_lessons: Optional[Sequence[Dict[str, Any]]] = None,
    config: Optional[Dict[str, Any]] = None,
    limit: int = 5,
    record_feedback: bool = True,
) -> PersistedPreCurationResult:
    retrieval = retrieve_global_lessons_for_event(db, event, config=config, limit=limit)
    decision = should_curate_locally(
        event,
        retrieval.lessons,
        local_lessons=local_lessons,
        config=config,
    )
    metrics: Dict[str, int] = {}
    record_global_lesson_reuse_metric(metrics, decision.metric)
    if record_feedback and decision.global_claim_id and decision.matched_claim:
        updated = dict(decision.matched_claim)
        stats = dict(updated.get("reuse_stats") or {})
        record_global_lesson_reuse_metric(stats, decision.metric)
        updated["reuse_stats"] = stats
        persist_global_lesson(db, updated)
    return PersistedPreCurationResult(decision=decision, retrieval=retrieval, metrics=metrics)


def estimate_tokens(text: str) -> int:
    return max(1, (len(str(text or "")) + 3) // 4)


def hydrate_task_memory_from_global(
    db: SessionDB,
    event: GlobalPreCurationEvent | Dict[str, Any],
    *,
    local_claims: Optional[Sequence[Dict[str, Any]]] = None,
    config: Optional[Dict[str, Any]] = None,
    hot_limit: int = 3,
    global_limit: int = 3,
    token_budget: int = 800,
    ttl_seconds: int = 3600,
) -> HydratedMemoryPacket:
    evt = _as_precuration_event(event)
    hot_hits = retrieve_global_hot_cache_for_event(db, evt, limit=hot_limit)
    materialized: List[Dict[str, Any]] = []
    retrieval_audit: Dict[str, Any] = {"status": "skipped", "reason": "hot_cache_hit"}

    if not hot_hits:
        retrieved = retrieve_global_lessons_for_event(db, evt, config=config, limit=global_limit)
        retrieval_audit = retrieved.audit.to_dict()
        for lesson in retrieved.lessons[:global_limit]:
            entry = materialize_global_lesson_to_hot_cache(db, lesson, evt, ttl_seconds=ttl_seconds)
            materialized.append(entry.to_dict())
        hot_hits = retrieve_global_hot_cache_for_event(db, evt, limit=hot_limit)

    packet_id = f"gmem_{stable_hash([evt.to_dict(), [item.get('id') for item in hot_hits]])[:16]}"
    advisory_items: List[Dict[str, Any]] = []
    used_tokens = 0

    def _add_item(source: str, text: str, metadata: Dict[str, Any]) -> None:
        nonlocal used_tokens
        token_cost = estimate_tokens(text)
        if used_tokens + token_cost > int(token_budget):
            return
        used_tokens += token_cost
        advisory_items.append(
            {
                "source": source,
                "text": text,
                "estimated_tokens": token_cost,
                **metadata,
            }
        )

    for claim in local_claims or []:
        text = str(claim.get("text") or claim.get("body") or claim.get("claim") or "")
        if text:
            _add_item("local_memory", text, {"id": claim.get("id") or claim.get("record_id")})

    for hit in hot_hits:
        _add_item(
            "global_hot_cache",
            hit["compact_text"],
            {
                "id": hit["id"],
                "global_lesson_id": hit["global_lesson_id"],
                "confidence": hit["confidence"],
                "evidence_refs": hit.get("evidence_refs") or [],
                "advisory": True,
            },
        )

    status = "ready" if advisory_items else "empty"
    return HydratedMemoryPacket(
        packet_id=packet_id,
        event_id=evt.event_id,
        status=status,
        hot_cache_hits=hot_hits,
        global_lessons=materialized,
        local_claims=[dict(item) for item in (local_claims or [])],
        advisory_items=advisory_items,
        estimated_tokens=used_tokens,
        token_budget=int(token_budget),
        retrieval_audit=retrieval_audit,
        materialized=len(materialized),
    )


def should_curate_locally(
    event: GlobalPreCurationEvent | Dict[str, Any],
    approved_global_lessons: Sequence[Dict[str, Any]],
    *,
    local_lessons: Optional[Sequence[Dict[str, Any]]] = None,
    config: Optional[Dict[str, Any]] = None,
) -> GlobalPreCurationDecision:
    """Decide whether a local expensive curator should run for a runtime event.

    This is intentionally deterministic and LLM-free. It lets hot/warm local
    lessons and approved global lessons suppress duplicate curation before any
    model-backed sidecar spends tokens.
    """
    cfg = _precuration_config(config)
    evt = _as_precuration_event(event)
    if not cfg.get("enabled", True):
        return GlobalPreCurationDecision(
            action="curate_locally",
            reason="global pre-curation disabled",
            metric="global_lesson_miss",
            should_run_expensive_curator=True,
        )

    for lesson in local_lessons or []:
        if str(lesson.get("tier") or "").lower() not in {"hot", "warm"}:
            continue
        if _lesson_is_usable_for_event(evt, lesson) and _exact_lesson_match(evt, lesson):
            return GlobalPreCurationDecision(
                action="skip_local_exact_hit",
                reason="approved local hot/warm lesson already covers event",
                metric="local_lesson_hit",
                should_run_expensive_curator=False,
                global_claim_id=str(lesson.get("id") or "") or None,
                confidence=_lesson_confidence(lesson),
                matched_claim=dict(lesson),
            )

    usable_global = [lesson for lesson in approved_global_lessons if _lesson_is_usable_for_event(evt, lesson)]
    for lesson in usable_global:
        if _exact_lesson_match(evt, lesson):
            return GlobalPreCurationDecision(
                action="skip_global_exact_hit",
                reason="approved global lesson exactly covers event",
                metric="global_lesson_hit",
                should_run_expensive_curator=not bool(cfg.get("skip_expensive_curator_on_exact", True)),
                global_claim_id=str(lesson.get("id") or "") or None,
                confidence=_lesson_confidence(lesson),
                matched_claim=dict(lesson),
            )

    max_distance = int(cfg.get("near_hamming_distance") or 8)
    min_confidence = float(cfg.get("min_near_confidence") or 0.75)
    for lesson in usable_global:
        confidence = _lesson_confidence(lesson)
        if confidence >= min_confidence and _near_lesson_match(evt, lesson, max_distance=max_distance):
            return GlobalPreCurationDecision(
                action="confirm_global_near_hit",
                reason="approved global lesson is a near match; require lightweight local confirmation",
                metric="global_lesson_near_hit",
                should_run_expensive_curator=not bool(cfg.get("skip_expensive_curator_on_near", True)),
                local_confirmation_required=True,
                global_claim_id=str(lesson.get("id") or "") or None,
                confidence=confidence,
                matched_claim=dict(lesson),
            )

    return GlobalPreCurationDecision(
        action="curate_locally",
        reason="no approved local/global lesson matched event",
        metric="global_lesson_miss",
        should_run_expensive_curator=True,
    )


def record_global_lesson_reuse_metric(
    metrics: MutableMapping[str, int],
    metric: str,
    amount: int = 1,
) -> MutableMapping[str, int]:
    allowed = {
        "global_lesson_hit",
        "global_lesson_near_hit",
        "global_lesson_used",
        "global_lesson_helped",
        "global_lesson_ignored",
        "global_lesson_hurt",
        "global_lesson_miss",
    }
    if metric not in allowed:
        raise ValueError(f"unsupported global lesson reuse metric: {metric}")
    metrics[metric] = int(metrics.get(metric, 0)) + int(amount)
    return metrics


def update_global_lesson_reuse_feedback(
    lesson: Dict[str, Any],
    outcome: str,
    *,
    step: float = 0.02,
) -> Dict[str, Any]:
    """Return an updated lesson metadata copy after runtime feedback.

    This never imports local private evidence. It only records aggregate reuse
    counters and bounded confidence movement.
    """
    if outcome not in {"used", "helped", "ignored", "hurt"}:
        raise ValueError(f"unsupported global lesson feedback outcome: {outcome}")
    updated = dict(lesson or {})
    stats = dict(updated.get("reuse_stats") or {})
    record_global_lesson_reuse_metric(stats, f"global_lesson_{outcome}")
    confidence = _lesson_confidence(updated)
    if outcome == "helped":
        confidence += step
    elif outcome == "ignored":
        confidence -= step / 2
    elif outcome == "hurt":
        confidence -= step * 2
    updated["confidence"] = max(0.0, min(1.0, confidence))
    updated["reuse_stats"] = stats
    updated["last_reuse_feedback_at"] = _now()
    return updated


def ensure_discussion_memory_schema(db: SessionDB) -> None:
    def _do(conn):
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS hermes_discussion_memory_records (
                id TEXT PRIMARY KEY,
                tenant_id TEXT,
                record_type TEXT NOT NULL,
                title TEXT NOT NULL,
                summary TEXT NOT NULL,
                scope TEXT NOT NULL,
                domain TEXT NOT NULL,
                sensitivity TEXT NOT NULL,
                source_session_id TEXT,
                evidence_refs_json TEXT,
                citation_refs_json TEXT,
                claims_json TEXT,
                approval_state TEXT NOT NULL,
                producer_invocation_id TEXT,
                judge_invocation_id TEXT,
                operator_approved INTEGER NOT NULL DEFAULT 0,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_hermes_discussion_memory_scope
                ON hermes_discussion_memory_records(tenant_id, domain, scope, approval_state, updated_at DESC)
            """
        )

    db._execute_write(_do)


def _json_list(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return _json_list(parsed)
        except Exception:
            return []
    return []


def upsert_discussion_memory_record(db: SessionDB, record: DiscussionMemoryRecord) -> DiscussionMemoryRecord:
    ensure_discussion_memory_schema(db)
    record.updated_at = _now()

    def _do(conn):
        conn.execute(
            """
            INSERT OR REPLACE INTO hermes_discussion_memory_records (
                id, tenant_id, record_type, title, summary, scope, domain,
                sensitivity, source_session_id, evidence_refs_json,
                citation_refs_json, claims_json, approval_state,
                producer_invocation_id, judge_invocation_id, operator_approved,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.id,
                record.tenant_id,
                record.record_type,
                record.title,
                record.summary,
                record.scope,
                record.domain,
                record.sensitivity,
                record.source_session_id,
                json.dumps(record.evidence_refs, sort_keys=True),
                json.dumps(record.citation_refs, sort_keys=True),
                json.dumps(record.claims, sort_keys=True),
                record.approval_state,
                record.producer_invocation_id,
                record.judge_invocation_id,
                1 if record.operator_approved else 0,
                record.created_at,
                record.updated_at,
            ),
        )

    db._execute_write(_do)
    return record


def approval_invocation_allowed(record: Dict[str, Any]) -> ValidationResult:
    producer = str(record.get("producer_invocation_id") or "")
    judge = str(record.get("judge_invocation_id") or "")
    errors = []
    if not producer:
        errors.append("producer_invocation_id is required")
    if not judge:
        errors.append("judge_invocation_id is required")
    if producer and judge and producer == judge:
        errors.append("judge invocation must differ from producer invocation")
    if record.get("scope") == "global" and not record.get("operator_approved"):
        errors.append("global discussion memory requires operator approval")
    return ValidationResult(valid=not errors, errors=errors)


def fanout_discussion_record_to_indexes(db: SessionDB, record: DiscussionMemoryRecord) -> GlobalIndexFanoutResult:
    if record.approval_state not in {"approved", "canonical", "applied"}:
        return GlobalIndexFanoutResult(status="skipped", claim_id=record.id, errors=["discussion record must be approved"])
    if record.sensitivity == "secret":
        return GlobalIndexFanoutResult(status="skipped", claim_id=record.id, errors=["secret discussion records are not indexed"])

    from hermes_cli.memory_graph import upsert_graph_edge, upsert_graph_node
    from hermes_cli.memory_index import upsert_memory_index_document

    memory_id = f"discussion:{record.id}"
    text = " ".join([record.title, record.summary, " ".join(record.claims)]).strip()
    metadata = {
        "tenant_id": record.tenant_id,
        "domain": record.domain,
        "scope": record.scope,
        "sensitivity": record.sensitivity,
        "status": "approved",
        "tier": "discussion",
        "source_session_id": record.source_session_id,
        "evidence_refs": record.evidence_refs,
        "citation_refs": record.citation_refs,
    }
    upsert_memory_index_document(db, memory_id=memory_id, text=text, metadata=metadata)
    nodes = 1
    edges = 0
    upsert_graph_node(db, node_id=memory_id, kind="discussion_memory", label=record.title)
    for kind, values, relation in [
        ("domain", [record.domain], "APPLIES_TO_DOMAIN"),
        ("scope", [record.scope], "HAS_SCOPE"),
        ("tenant", [record.tenant_id] if record.tenant_id else [], "APPLIES_TO_TENANT"),
        ("evidence", record.evidence_refs, "SUPPORTED_BY"),
        ("citation", record.citation_refs, "CITES"),
    ]:
        for value in values:
            node_id = f"{kind}:{value}"
            upsert_graph_node(db, node_id=node_id, kind=kind, label=str(value))
            upsert_graph_edge(db, source_id=memory_id, target_id=node_id, relation=relation)
            nodes += 1
            edges += 1
    return GlobalIndexFanoutResult(
        status="indexed",
        claim_id=record.id,
        lexical_indexed=True,
        graph_nodes=nodes,
        graph_edges=edges,
        vector_payload={"id": memory_id, "text": text, "metadata": metadata},
    )


def publish_global_proposal(
    db: SessionDB,
    config: Dict[str, Any],
    raw_proposal: Dict[str, Any],
) -> Dict[str, Any]:
    proposal = normalize_proposal(raw_proposal)
    payload = proposal.to_dict()
    validation = validate_proposal(payload)
    if not validation.valid:
        return {"ok": False, "validation": validation.to_dict(), "proposal": payload}
    key = build_idempotency_key(payload)
    bus = get_global_memory_bus(db, config)
    result = bus.publish("proposed", payload, event_key=key)
    return {
        "ok": True,
        "proposal": payload,
        "validation": validation.to_dict(),
        "idempotency_key": key,
        "publish": result,
    }


def canonical_claim_to_index_payload(canonical_claim: Dict[str, Any]) -> Dict[str, Any]:
    claim = normalize_proposal(canonical_claim).to_dict()
    text = " ".join(
        part
        for part in [
            str(claim.get("title") or ""),
            str(claim.get("normalized_text") or ""),
            " ".join(claim.get("entities") or []),
            " ".join(claim.get("graph_keys") or []),
        ]
        if part
    ).strip()
    metadata = {
        "global_claim_id": claim["id"],
        "tenant_id": claim.get("tenant_id"),
        "domain": claim.get("domain"),
        "scope": claim.get("scope"),
        "visibility": claim.get("visibility"),
        "sensitivity": claim.get("sensitivity"),
        "claim_type": claim.get("claim_type"),
        "language": claim.get("language"),
        "status": "approved",
        "tier": "global",
        "source_instance_id": claim.get("source_instance_id"),
        "source_session_id": claim.get("source_session_id"),
        "text_hash": claim.get("text_hash"),
        "simhash": claim.get("simhash"),
        "evidence_refs": claim.get("evidence_refs") or [],
        "citation_refs": claim.get("citation_refs") or [],
        "entities": claim.get("entities") or [],
        "graph_keys": claim.get("graph_keys") or [],
        "confidence": claim.get("confidence"),
    }
    return {
        "memory_id": f"global:{claim['id']}",
        "text": text,
        "metadata": metadata,
        "vector_payload": {
            "id": f"global:{claim['id']}",
            "text": text,
            "metadata": metadata,
        },
    }


def fanout_canonical_claim_to_indexes(
    db: SessionDB,
    *,
    canonical_claim: Dict[str, Any],
    config: Optional[Dict[str, Any]] = None,
) -> GlobalIndexFanoutResult:
    """Fan out an approved canonical claim into local lexical/graph indexes.

    External vector/graph backends are intentionally represented as payload
    boundaries here; adapters can consume the returned vector payload later.
    """
    claim = normalize_proposal(canonical_claim).to_dict()
    if canonical_claim.get("approval_state") not in {"approved", "canonical", "applied"}:
        return GlobalIndexFanoutResult(
            status="skipped",
            claim_id=claim["id"],
            errors=["canonical claim must be approved before index fanout"],
        )
    if claim.get("sensitivity") == "secret":
        return GlobalIndexFanoutResult(
            status="skipped",
            claim_id=claim["id"],
            errors=["secret claims are not globally indexed"],
        )

    from hermes_cli.memory_graph import upsert_graph_edge, upsert_graph_node
    from hermes_cli.memory_index import upsert_memory_index_document

    payload = canonical_claim_to_index_payload({**claim, "approval_state": canonical_claim.get("approval_state")})
    upsert_memory_index_document(
        db,
        memory_id=payload["memory_id"],
        text=payload["text"],
        metadata=payload["metadata"],
    )

    graph_nodes = 0
    graph_edges = 0
    claim_node = payload["memory_id"]
    upsert_graph_node(db, node_id=claim_node, kind="global_claim", label=claim.get("title") or claim["id"])
    graph_nodes += 1

    def _edge_node(kind: str, value: str, relation: str) -> None:
        nonlocal graph_nodes, graph_edges
        if not value:
            return
        node_id = f"{kind}:{value}"
        upsert_graph_node(db, node_id=node_id, kind=kind, label=value)
        upsert_graph_edge(db, source_id=claim_node, target_id=node_id, relation=relation, weight=1.0)
        graph_nodes += 1
        graph_edges += 1

    _edge_node("domain", str(claim.get("domain") or ""), "APPLIES_TO_DOMAIN")
    _edge_node("scope", str(claim.get("scope") or ""), "HAS_SCOPE")
    _edge_node("tenant", str(claim.get("tenant_id") or ""), "APPLIES_TO_TENANT")
    for entity in claim.get("entities") or []:
        _edge_node("entity", str(entity), "MENTIONS_ENTITY")
    for graph_key in claim.get("graph_keys") or []:
        _edge_node("graph_key", str(graph_key), "HAS_GRAPH_KEY")
    for evidence_ref in claim.get("evidence_refs") or []:
        _edge_node("evidence", str(evidence_ref), "SUPPORTED_BY")
    for citation_ref in claim.get("citation_refs") or []:
        _edge_node("citation", str(citation_ref), "CITES")

    try:
        bus = get_global_memory_bus(db, config or {})
        bus.publish(
            "index_completed",
            {"claim_id": claim["id"], "memory_id": payload["memory_id"], "status": "indexed"},
            event_key=stable_hash(["index_completed", claim["id"]]),
        )
    except Exception:
        # Index fanout should remain useful even when bus publishing is disabled.
        pass

    return GlobalIndexFanoutResult(
        status="indexed",
        claim_id=claim["id"],
        lexical_indexed=True,
        graph_nodes=graph_nodes,
        graph_edges=graph_edges,
        vector_payload=payload["vector_payload"],
    )


def classify_dedupe(proposal: Dict[str, Any], candidates: Iterable[Dict[str, Any]]) -> DedupeDecision:
    normalized = normalize_proposal(proposal).to_dict()
    proposal_evidence_hash = evidence_hash(normalized.get("evidence_refs") or [])
    best = DedupeDecision(proposal_id=normalized["id"], dedupe_class="canonical_new", score=0.0)
    proposal_terms = set(re.findall(r"[\w:/.-]+", normalized["normalized_text"]))
    proposal_entities = set(normalized.get("entities") or [])

    for candidate_raw in candidates:
        candidate = normalize_proposal(candidate_raw).to_dict()
        cid = candidate["id"]
        reasons: List[str] = []
        if normalized["text_hash"] == candidate["text_hash"]:
            return DedupeDecision(normalized["id"], "exact_duplicate", cid, 1.0, ["text_hash"])
        if evidence_hash(candidate.get("evidence_refs") or []) == proposal_evidence_hash:
            decision = DedupeDecision(normalized["id"], "same_evidence", cid, 0.95, ["evidence_hash"])
            if decision.score > best.score:
                best = decision
        distance = hamming_distance_hex(normalized["simhash"], candidate["simhash"])
        if distance <= 6:
            decision = DedupeDecision(normalized["id"], "near_duplicate", cid, 0.9 - (distance / 100), ["simhash"])
            if decision.score > best.score:
                best = decision
        candidate_terms = set(re.findall(r"[\w:/.-]+", candidate["normalized_text"]))
        overlap = len(proposal_terms & candidate_terms) / max(1, len(proposal_terms | candidate_terms))
        entity_overlap = len(proposal_entities & set(candidate.get("entities") or []))
        if overlap >= 0.45 or entity_overlap >= 2:
            reasons.append("term_or_entity_overlap")
            if _looks_conflicting(normalized["normalized_text"], candidate["normalized_text"]):
                decision = DedupeDecision(normalized["id"], "conflict", cid, max(0.7, overlap), reasons + ["conflict_terms"])
            elif float(normalized.get("confidence") or 0) > float(candidate.get("confidence") or 0) + 0.1:
                decision = DedupeDecision(normalized["id"], "supersedes", cid, max(0.65, overlap), reasons + ["higher_confidence"])
            else:
                decision = DedupeDecision(normalized["id"], "same_topic", cid, max(0.55, overlap), reasons)
            if decision.score > best.score:
                best = decision
    if best.dedupe_class not in VALID_DEDUPE_CLASSES:
        best.dedupe_class = "canonical_new"
    return best


def _looks_conflicting(left: str, right: str) -> bool:
    conflict_pairs = [
        ("should", "should not"),
        ("use", "avoid"),
        ("enabled", "disabled"),
        ("safe", "unsafe"),
        ("allow", "deny"),
        ("global", "private"),
    ]
    for positive, negative in conflict_pairs:
        if positive in left and negative in right:
            return True
        if negative in left and positive in right:
            return True
    return False
