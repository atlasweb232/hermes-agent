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
from typing import Any, Dict, Iterable, List, Optional, Protocol

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
