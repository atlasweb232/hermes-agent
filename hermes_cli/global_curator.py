"""Single-consumer global curator: the ordered drain that removes the promotion race.

The concurrency problem (raised in review): many tenants promote candidates at once.
The dedup classifier + merge semantics exist (``merge_or_persist_global_lesson``), but
classification is read-then-write — two tenants promoting near-duplicates concurrently
can both classify as ``canonical_new`` and both insert, because neither sees the other's
row yet. That is a TOCTOU race no per-call logic can close.

The fix is architectural, not algorithmic: tenants do NOT write the global pool directly.
They *publish* an idempotent proposal to the dedupe topic; a SINGLE ordered consumer (this
curator) drains it and applies the merge semantics serially. One writer ⇒ the
read-then-write sequence is serialized ⇒ no race. The durable bus
(``hermes_cli.learning_bus``) gives ordering, at-least-once delivery, idempotency
(``event_key``), leasing, retry and dead-lettering for free.

Scaling note: to run more than one curator, partition the bus by a coarse *dedup-cluster*
key (e.g. ``failure_signature`` / simhash bucket) so all near-duplicates of a cluster land
on the same partition → same consumer → still serialized within a cluster, parallel across
clusters. The default single consumer is race-free without partitioning.

This module is learning-plane (off the serving path); it is meant to be driven by the
curator sidecar / a scheduled job, never inline in ``run_agent``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from hermes_state import SessionDB
from hermes_cli.global_memory import (
    GlobalCurationResult,
    build_global_topic,
    build_idempotency_key,
    lesson_meets_quorum,
    merge_or_persist_global_lesson,
    persist_global_lesson,
)
from hermes_cli.learning_bus import (
    consume_learning_events,
    mark_learning_event_consumed,
    publish_learning_event_safely,
)


DEDUPE_TOPIC = "dedupe_requested"
DEDUPE_DONE_TOPIC = "dedupe_completed"

# A candidate promoted to global enters QUARANTINED — not in the usable set
# ({approved, canonical, applied}), so it is never retrieved/applied. It is flipped to
# CANONICAL (usable) only once distinct-tenant quorum is met. This is the core poisoning
# defense: one tenant alone can never make a global lesson usable.
PRE_ACTIVE_STATES = {"quarantined", "global_candidate", "proposed"}
QUORUM_ACTIVE_STATE = "canonical"


def resolve_dedupe_topic(config: Optional[Dict[str, Any]]) -> str:
    return build_global_topic(config or {}, DEDUPE_TOPIC)


def publish_global_lesson_proposal(
    db: SessionDB,
    lesson: Dict[str, Any],
    *,
    config: Optional[Dict[str, Any]] = None,
) -> Any:
    """Producer side: a tenant/supervisor publishes a lesson proposal to the dedupe topic.

    This REPLACES direct ``persist_global_lesson`` calls on the promotion path — the
    global pool is written only by the curator consumer. The ``event_key`` is an
    idempotency hash (tenant + normalized text + evidence), so an at-least-once redelivery
    or an accidental double-publish collapses to one queued event.
    """
    payload = dict(lesson)
    key = build_idempotency_key(
        {
            "tenant_id": payload.get("tenant_id"),
            "normalized_text": payload.get("normalized_text") or payload.get("claim") or "",
            "evidence_refs": payload.get("evidence_refs") or [],
        }
    )
    return publish_learning_event_safely(
        db,
        topic=resolve_dedupe_topic(config),
        payload=payload,
        tenant_id=payload.get("tenant_id"),
        repo_id=payload.get("repo_id"),
        event_key=key,
    )


@dataclass
class CurationRunResult:
    consumer: str
    processed: int = 0
    created: int = 0
    merged: int = 0
    conflicts: int = 0
    quorum_met: int = 0
    promoted: int = 0  # quarantined → canonical (usable) on quorum
    failed: int = 0
    dead_lettered: int = 0
    results: List[GlobalCurationResult] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "consumer": self.consumer,
            "processed": self.processed,
            "created": self.created,
            "merged": self.merged,
            "conflicts": self.conflicts,
            "quorum_met": self.quorum_met,
            "promoted": self.promoted,
            "failed": self.failed,
            "dead_lettered": self.dead_lettered,
        }


@dataclass
class GlobalPromotionResult:
    candidate_id: str
    status: str  # "published" | "blocked"
    notes: str = ""
    event_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "status": self.status,
            "notes": self.notes,
            "event_id": self.event_id,
        }


def promote_candidate_to_global_pool(
    db: SessionDB,
    *,
    candidate_id: str,
    config: Optional[Dict[str, Any]] = None,
    require_verification: bool = True,
    require_held_out: Optional[bool] = None,
    initial_state: str = "quarantined",
) -> GlobalPromotionResult:
    """Promote an approved meta-candidate into the global pool — via the curator, gated.

    This is the supervisor→global link. It does NOT write the pool directly: it builds a
    global-lesson proposal from the candidate and publishes it to the dedupe topic
    (``publish_global_lesson_proposal``) for the single-consumer curator to merge. The
    candidate must be approved AND carry passing, model-independent verification; for
    cross-tenant/global scope, held-out verification is required by default (the
    teacher-independence rule). The proposal enters QUARANTINED — quorum flips it usable.
    """
    candidate = db.get_meta_candidate(candidate_id)
    if candidate is None:
        raise ValueError(f"unknown meta candidate: {candidate_id}")
    status = str(candidate.get("status") or "").lower()
    if status not in {"approved", "applied"}:
        return GlobalPromotionResult(candidate_id, "blocked", f"candidate not approved (status={status})")

    evidence = candidate.get("evidence_json") if isinstance(candidate.get("evidence_json"), dict) else {}
    from hermes_cli.verification_evidence import (
        evidence_has_passing_verification,
        load_verification_gate_config,
    )

    if require_held_out is None:
        require_held_out = load_verification_gate_config(config)["require_held_out_for_global"]
    if require_verification and not evidence_has_passing_verification(evidence, require_held_out=require_held_out):
        return GlobalPromotionResult(
            candidate_id, "blocked",
            "no passing held-out verification; cannot promote to global",
        )

    verification = evidence.get("verification") if isinstance(evidence.get("verification"), dict) else {}
    evidence_refs = [r for r in [evidence.get("evidence_uri"), verification.get("evidence_uri")] if r]
    proposal = {
        "tenant_id": candidate.get("tenant_id"),
        "repo_id": candidate.get("repo_id"),
        "approval_state": initial_state,
        "scope": "global",
        "sensitivity": str(evidence.get("sensitivity") or "internal"),
        "visibility": "global_candidate",
        "claim_type": str(candidate.get("kind") or "lesson"),
        "normalized_text": str(candidate.get("claim") or ""),
        "confidence": float(candidate.get("score") or evidence.get("confidence") or 0.0),
        "evidence_refs": evidence_refs or [f"candidate://{candidate_id}"],
        "cross_tenant_shareable": True,
        "failure_signature": str(evidence.get("failure_signature") or ""),
        "success_signature": str(evidence.get("successful_action") or evidence.get("success_signature") or ""),
        "approval_provenance": {"candidate_id": candidate_id, "verification": verification},
    }
    event = publish_global_lesson_proposal(db, proposal, config=config)
    return GlobalPromotionResult(
        candidate_id, "published", "published to global dedupe topic",
        event_id=getattr(event, "id", None),
    )


def run_global_curator_once(
    db: SessionDB,
    *,
    config: Optional[Dict[str, Any]] = None,
    consumer: str = "global-curator",
    limit: int = 50,
    lease_seconds: float = 300.0,
    min_distinct_tenants: int = 2,
    require_held_out: bool = False,
    promote_on_quorum: bool = True,
) -> CurationRunResult:
    """Lease a batch from the dedupe topic and apply merge semantics serially.

    On success the event is acked (``consumed``). On failure it is left leased — the bus
    re-leases it after the lease expires and dead-letters it after ``max_attempts``, so a
    poison-pill can't block the topic forever and a transient error is retried. Each
    resulting lesson is checked against the quorum gate (distinct-tenant corroboration,
    optionally held-out), surfaced in the result for the lifecycle stage to act on.
    """
    topic = resolve_dedupe_topic(config)
    consumed = consume_learning_events(
        db, consumer=consumer, topics=[topic], limit=limit, lease_seconds=lease_seconds
    )
    result = CurationRunResult(consumer=consumer, dead_lettered=len(consumed.dead_lettered))

    for event in consumed.leased:
        try:
            lesson = dict(event.payload_json or {})
            out = merge_or_persist_global_lesson(db, lesson)
            if out.action == "created":
                result.created += 1
            elif out.action == "merged":
                result.merged += 1
            elif out.action == "conflict":
                result.conflicts += 1
            if out.action in {"created", "merged"} and lesson_meets_quorum(
                out.lesson,
                min_distinct_tenants=min_distinct_tenants,
                require_held_out=require_held_out,
            ):
                result.quorum_met += 1
                # Quorum gate: flip a quarantined lesson to canonical (usable) ONLY now
                # that distinct-tenant corroboration is satisfied. Before this, the lesson
                # is not in the usable set and is never retrieved — one tenant can't make
                # a global lesson live.
                if promote_on_quorum and str(out.lesson.get("approval_state") or "").lower() in PRE_ACTIVE_STATES:
                    promoted = dict(out.lesson)
                    promoted["approval_state"] = QUORUM_ACTIVE_STATE
                    persist_global_lesson(db, promoted)
                    out.lesson = promoted
                    result.promoted += 1
            result.results.append(out)
            mark_learning_event_consumed(db, event.id)
            result.processed += 1
        except Exception:
            # Leave unacked: lease expiry → retry → eventual dead-letter via max_attempts.
            result.failed += 1
    return result


def run_global_curator_loop(
    db: SessionDB,
    *,
    config: Optional[Dict[str, Any]] = None,
    consumer: str = "global-curator",
    max_batches: int = 100,
    **kwargs: Any,
) -> CurationRunResult:
    """Drain the topic across multiple batches until empty or ``max_batches`` reached.

    Bounded (no infinite loop) so it is safe to call from a scheduled job. Aggregates the
    per-batch results into one summary.
    """
    total = CurationRunResult(consumer=consumer)
    for _ in range(max(1, int(max_batches))):
        batch = run_global_curator_once(db, config=config, consumer=consumer, **kwargs)
        total.processed += batch.processed
        total.created += batch.created
        total.merged += batch.merged
        total.conflicts += batch.conflicts
        total.quorum_met += batch.quorum_met
        total.promoted += batch.promoted
        total.failed += batch.failed
        total.dead_lettered += batch.dead_lettered
        total.results.extend(batch.results)
        if batch.processed == 0 and batch.failed == 0 and batch.dead_lettered == 0:
            break  # topic drained
    return total
