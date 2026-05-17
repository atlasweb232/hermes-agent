"""Supervisor memory readiness and packet assembly helpers.

This module keeps the first Hermes memory-framework slice deterministic:
policy lookup, repository-scoped search, compact packet assembly, and
readiness persistence in state.db.
"""

from __future__ import annotations

import hashlib
import contextlib
import json
import re
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional

from hermes_cli.config import load_config
from hermes_state import SessionDB


def _now() -> float:
    return time.time()


def _as_list(value: Optional[Iterable[str]]) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return [item for item in value if item]


def get_supervisor_memory_policy(config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if config is None:
        config = load_config()
    supervisor = config.get("supervisor", {})
    if not isinstance(supervisor, dict):
        return {}
    memory = supervisor.get("memory", {})
    return memory if isinstance(memory, dict) else {}


@dataclass
class MemoryReadinessResult:
    status: str
    reason: str
    packet_id: Optional[str] = None
    required: bool = False
    candidate_count: int = 0
    evidence_count: int = 0
    query: str = ""
    scopes: List[str] = field(default_factory=list)
    checked_at: float = field(default_factory=_now)
    policy_version: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class MemoryPacketResult:
    packet_id: str
    status: str
    query: str
    scopes: List[str]
    claims: List[Dict[str, Any]] = field(default_factory=list)
    evidence: List[Dict[str, Any]] = field(default_factory=list)
    contradictions: List[Dict[str, Any]] = field(default_factory=list)
    freshness: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    created_at: float = field(default_factory=_now)
    expires_at: Optional[float] = None
    source: str = "supervisor.memory.router"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class LearningRollupResult:
    run_id: str
    status: str
    records_scanned: int
    candidates_created: int
    candidates_updated: int
    notes: str
    metrics: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class LearningMonitorResult:
    status: str
    runs_observed: int
    candidates_observed: int
    readiness_observed: int
    ready_packets: int
    blocked_packets: int
    degraded_packets: int
    metrics: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class LearningPolicyResult:
    run_id: str
    status: str
    promoted: int = 0
    applied: int = 0
    rolled_back: int = 0
    notes: str = ""
    metrics: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class CandidateHousekeepingItem:
    candidate_id: str
    kind: str
    status: str
    action: str
    reason: str
    score: Optional[float] = None
    created_at: Optional[float] = None
    updated_at: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class CandidateHousekeepingResult:
    status: str
    scanned: int
    archived: int
    skipped: int
    dry_run: bool
    items: List[CandidateHousekeepingItem] = field(default_factory=list)
    metrics: Dict[str, Any] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class LearningSidecarTickResult:
    rollup: Dict[str, Any]
    monitor: Dict[str, Any]
    policy: Dict[str, Any]
    housekeeping: Dict[str, Any] = field(default_factory=dict)
    bus: Dict[str, Any] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class LearningSidecarResult:
    status: str
    ticks: int
    interval_seconds: float
    once: bool
    tenant_id: Optional[str] = None
    repo_id: Optional[str] = None
    last_tick: Optional[LearningSidecarTickResult] = None
    errors: List[str] = field(default_factory=list)
    metrics: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        if self.last_tick is not None:
            data["last_tick"] = self.last_tick.to_dict()
        return data


@dataclass
class MetaCandidateActionResult:
    candidate_id: str
    status: str
    applied: bool
    config_written: bool
    config_targets: List[str] = field(default_factory=list)
    notes: str = ""
    candidate: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _build_claim_from_record(record: Dict[str, Any]) -> Dict[str, Any]:
    payload = record.get("payload_json")
    claim = {
        "record_id": record.get("id"),
        "kind": record.get("kind"),
        "title": record.get("title"),
        "body": record.get("body"),
        "status": record.get("status"),
        "score": record.get("score"),
        "evidence_uri": record.get("evidence_uri"),
        "evidence_sha256": record.get("evidence_sha256"),
    }
    if isinstance(payload, dict):
        claim["payload"] = payload
    elif payload is not None:
        claim["payload"] = payload
    return claim


def _build_evidence_from_record(record: Dict[str, Any]) -> Dict[str, Any]:
    payload = {
        "record_id": record.get("id"),
        "packet_id": record.get("packet_id"),
        "uri": record.get("evidence_uri"),
        "sha256": record.get("evidence_sha256"),
        "kind": record.get("kind"),
        "title": record.get("title"),
    }
    body = record.get("body")
    if body:
        payload["excerpt"] = body[:400]
    return payload


def _stable_candidate_id(
    *,
    kind: str,
    claim: str,
    tenant_id: Optional[str],
    repo_id: Optional[str],
) -> str:
    raw = "|".join([kind, claim.strip().lower(), tenant_id or "", repo_id or ""])
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
    return f"metacand_{digest}"


_KIND_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("routing_hint", re.compile(r"\b(oauth|deploy|callback|redirect|endpoint)\b", re.I)),
    ("validation_recipe", re.compile(r"\b(test|pytest|unit test|integration test|validation|assert)\b", re.I)),
    ("hook_rule", re.compile(r"\b(hook|trigger|lifecycle|compaction)\b", re.I)),
    ("memory_rule", re.compile(r"\b(memory|wiki|digest|claim|evidence)\b", re.I)),
    ("recovery_hint", re.compile(r"\b(retry|recover|requeue|crash|timeout|blocked)\b", re.I)),
]


def classify_meta_candidate_kind(text: str) -> str:
    for kind, pattern in _KIND_PATTERNS:
        if pattern.search(text):
            return kind
    return "playbook"


def build_learning_metrics(
    db: SessionDB,
    *,
    tenant_id: Optional[str] = None,
    repo_id: Optional[str] = None,
    recent_runs: int = 20,
) -> Dict[str, Any]:
    runs = db.list_learning_runs(tenant_id=tenant_id, repo_id=repo_id, limit=recent_runs)
    candidates = db.list_meta_candidates(tenant_id=tenant_id, repo_id=repo_id, limit=recent_runs)
    readiness = db.list_memory_readiness(tenant_id=tenant_id, repo_id=repo_id, limit=recent_runs)
    packets = db.list_memory_packets(tenant_id=tenant_id, repo_id=repo_id, limit=recent_runs)
    outcome_records = db.list_memory_records(
        tenant_id=tenant_id,
        repo_id=repo_id,
        kind="task_outcome",
        limit=recent_runs,
    )
    ready_packets = sum(1 for p in packets if p.get("status") == "ready")
    blocked_packets = sum(1 for p in packets if p.get("status") == "blocked")
    degraded_packets = sum(1 for p in packets if p.get("status") == "degraded")
    completed_outcomes = 0
    blocked_outcomes = 0
    failure_outcomes = 0
    memory_packet_used = 0
    for record in outcome_records:
        payload = record.get("payload_json") if isinstance(record.get("payload_json"), dict) else {}
        event_kind = str(payload.get("event_kind") or "")
        if event_kind == "completed":
            completed_outcomes += 1
        elif event_kind == "blocked":
            blocked_outcomes += 1
        elif event_kind in {"gave_up", "crashed", "timed_out", "spawn_failed", "completion_blocked_hallucination"}:
            failure_outcomes += 1
        if payload.get("memory_packet_id"):
            memory_packet_used += 1
    avg_candidate_score = 0.0
    scored = [float(c.get("score") or 0.0) for c in candidates if c.get("score") is not None]
    if scored:
        avg_candidate_score = sum(scored) / len(scored)
    return {
        "runs_observed": len(runs),
        "candidates_observed": len(candidates),
        "readiness_observed": len(readiness),
        "ready_packets": ready_packets,
        "blocked_packets": blocked_packets,
        "degraded_packets": degraded_packets,
        "ready_ratio": (ready_packets / len(packets)) if packets else 0.0,
        "blocked_ratio": (blocked_packets / len(packets)) if packets else 0.0,
        "avg_candidate_score": avg_candidate_score,
        "task_outcomes_observed": len(outcome_records),
        "completed_outcomes": completed_outcomes,
        "blocked_outcomes": blocked_outcomes,
        "failure_outcomes": failure_outcomes,
        "memory_packet_used": memory_packet_used,
        "task_success_ratio": (
            completed_outcomes / len(outcome_records)
            if outcome_records
            else 0.0
        ),
        "memory_packet_use_ratio": (
            memory_packet_used / len(outcome_records)
            if outcome_records
            else 0.0
        ),
    }


def _rollup_filter_policy(learning_policy: Dict[str, Any]) -> Dict[str, Any]:
    policy = learning_policy.get("rollup_filters")
    return policy if isinstance(policy, dict) else {}


def _record_text(record: Dict[str, Any]) -> str:
    return " ".join(
        str(part).strip()
        for part in (
            record.get("title"),
            record.get("body"),
            json.dumps(record.get("payload_json") or {}, ensure_ascii=False),
        )
        if part
    ).strip()


def _matches_any_pattern(text: str, patterns: Iterable[str]) -> bool:
    lowered = text.lower()
    for pattern in patterns:
        marker = str(pattern or "").strip().lower()
        if marker and marker in lowered:
            return True
    return False


def _memory_record_rollup_skip_reason(
    record: Dict[str, Any],
    *,
    learning_policy: Dict[str, Any],
) -> Optional[str]:
    filters = _rollup_filter_policy(learning_policy)
    kind = str(record.get("kind") or "")
    status = str(record.get("status") or "")
    if status in {"archived", "deleted", "rejected", "rolled_back"}:
        return f"record_status:{status}"
    curator_only = {
        str(item)
        for item in filters.get("curator_only_record_kinds", ["tool_routing_lesson"])
        if item
    }
    if kind in curator_only:
        return f"curator_only:{kind}"

    text = _record_text(record)
    if _matches_any_pattern(text, filters.get("synthetic_title_patterns") or []):
        return "synthetic_marker"

    if kind == "task_outcome":
        task_policy = filters.get("task_outcome")
        if not isinstance(task_policy, dict):
            task_policy = {}
        if task_policy.get("enabled", True) is False:
            return "task_outcome_disabled"
        payload = record.get("payload_json") if isinstance(record.get("payload_json"), dict) else {}
        event_kind = str(payload.get("event_kind") or "")
        allowed = {
            str(item)
            for item in task_policy.get("allowed_event_kinds", ["completed"])
            if item
        }
        if allowed and event_kind not in allowed:
            return f"task_outcome_event:{event_kind or 'missing'}"
        if task_policy.get("require_memory_packet", True):
            packet_id = record.get("packet_id") or payload.get("memory_packet_id") or payload.get("packet_id")
            if not packet_id:
                return "task_outcome_missing_memory_packet"
        min_task_score = float(task_policy.get("min_score", 0.75) or 0.75)
        if float(record.get("score") or 0.0) < min_task_score:
            return "task_outcome_low_score"
    return None


def _existing_candidate_blocks_rollup(
    candidate: Dict[str, Any],
    *,
    learning_policy: Dict[str, Any],
) -> Optional[str]:
    filters = _rollup_filter_policy(learning_policy)
    terminal_statuses = {
        str(item)
        for item in filters.get(
            "terminal_existing_statuses",
            ["approved", "applied", "archived", "rejected", "rolled_back"],
        )
        if item
    }
    status = str(candidate.get("status") or "")
    if status in terminal_statuses:
        return f"existing_candidate_status:{status}"
    return None


def _candidate_quality_skip_reason(
    candidate: Dict[str, Any],
    *,
    learning_policy: Dict[str, Any],
) -> Optional[str]:
    filters = _rollup_filter_policy(learning_policy)
    claim = str(candidate.get("claim") or "")
    evidence = candidate.get("evidence_json") if isinstance(candidate.get("evidence_json"), dict) else {}
    filters = _rollup_filter_policy(learning_policy)
    if filters.get("require_evidence_for_candidates", True) and not evidence:
        return "missing_evidence"
    evidence_text = json.dumps(evidence, ensure_ascii=False)
    combined = f"{claim} {evidence_text}"
    if _matches_any_pattern(combined, filters.get("synthetic_title_patterns") or []):
        return "synthetic_marker"

    record_id = str(evidence.get("record_id") or "")
    evidence_uri = str(evidence.get("evidence_uri") or "")
    is_kanban = record_id.startswith("kanban_event_") or evidence_uri.startswith("kanban://")
    if not is_kanban:
        return None

    lowered_claim = claim.lower()
    non_completed_markers = (
        "blocked:",
        "gave_up:",
        "timed_out:",
        "crashed:",
        "completion_blocked_hallucination:",
        "reclaimed:",
    )
    if lowered_claim.startswith(non_completed_markers):
        return "kanban_non_completed_outcome"

    task_policy = filters.get("task_outcome")
    if not isinstance(task_policy, dict):
        task_policy = {}
    if task_policy.get("require_memory_packet", True) and not evidence.get("packet_id"):
        return "kanban_missing_memory_packet"
    min_task_score = float(task_policy.get("min_score", 0.75) or 0.75)
    if float(candidate.get("score") or 0.0) < min_task_score:
        return "kanban_low_score"
    return None


def rollup_learning_candidates(
    db: SessionDB,
    *,
    tenant_id: Optional[str] = None,
    repo_id: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
) -> LearningRollupResult:
    policy = get_supervisor_memory_policy(config)
    learning_policy = (config or load_config()).get("supervisor", {}).get("learning", {})
    if not isinstance(learning_policy, dict):
        learning_policy = {}
    if not learning_policy.get("enabled", True):
        run_id = f"learn_{uuid.uuid4().hex[:16]}"
        db.record_learning_run(
            run_id=run_id,
            tenant_id=tenant_id,
            repo_id=repo_id,
            status="disabled",
            metrics_json={"reason": "learning disabled"},
            notes="learning disabled in config",
        )
        return LearningRollupResult(
            run_id=run_id,
            status="disabled",
            records_scanned=0,
            candidates_created=0,
            candidates_updated=0,
            notes="learning disabled in config",
            metrics={"enabled": False},
        )

    max_records = int(learning_policy.get("max_records", 50) or 50)
    min_score = float(learning_policy.get("min_score", 0.2) or 0.2)
    records = db.list_memory_records(tenant_id=tenant_id, repo_id=repo_id, limit=max_records)
    created = 0
    updated = 0
    proposed = 0
    seen: set[str] = set()
    candidate_payloads: list[dict[str, Any]] = []
    skipped: Dict[str, int] = {}

    def mark_skipped(reason: str) -> None:
        skipped[reason] = skipped.get(reason, 0) + 1

    for record in records:
        skip_reason = _memory_record_rollup_skip_reason(
            record,
            learning_policy=learning_policy,
        )
        if skip_reason:
            mark_skipped(skip_reason)
            continue
        if record.get("kind") == "task_outcome":
            try:
                from hermes_cli.learning_bus import publish_learning_event_safely

                publish_learning_event_safely(
                    db,
                    topic="learning.task_outcome.accepted",
                    payload={
                        "record_id": record.get("id"),
                        "status": record.get("status"),
                        "score": record.get("score"),
                        "payload": record.get("payload_json"),
                    },
                    tenant_id=tenant_id or record.get("tenant_id"),
                    repo_id=repo_id or record.get("repo_id"),
                    task_id=record.get("task_id"),
                    event_key=f"task_outcome:{record.get('id')}",
                )
            except Exception:
                pass
        text = _record_text(record)
        if not text:
            mark_skipped("empty_text")
            continue
        kind = classify_meta_candidate_kind(text)
        claim = (record.get("title") or record.get("body") or text).strip()
        claim = claim[:240]
        if not claim:
            mark_skipped("empty_claim")
            continue
        candidate_id = _stable_candidate_id(
            kind=kind,
            claim=claim,
            tenant_id=tenant_id or str(record.get("tenant_id") or ""),
            repo_id=repo_id or str(record.get("repo_id") or ""),
        )
        if candidate_id in seen:
            mark_skipped("duplicate_in_batch")
            continue
        seen.add(candidate_id)
        score = float(record.get("score") or 0.0)
        if score <= 0.0:
            score = 0.35 if record.get("evidence_uri") else 0.2
        if record.get("status") not in {"active", "promoted", "ready"}:
            score *= 0.8
        if score < min_score:
            mark_skipped("below_min_score")
            continue
        existing_candidate = db.get_meta_candidate(candidate_id)
        if existing_candidate is not None:
            existing_skip = _existing_candidate_blocks_rollup(
                existing_candidate,
                learning_policy=learning_policy,
            )
            if existing_skip:
                mark_skipped(existing_skip)
                continue
        evidence = {
            "record_id": record.get("id"),
            "packet_id": record.get("packet_id"),
            "evidence_uri": record.get("evidence_uri"),
            "evidence_sha256": record.get("evidence_sha256"),
            "status": record.get("status"),
        }
        candidate_payloads.append(
            {
                "candidate_id": candidate_id,
                "kind": kind,
                "claim": claim,
                "evidence": evidence,
                "score": score,
            }
        )

    for candidate in candidate_payloads:
        proposed += 1
        existing = db.get_meta_candidate(candidate["candidate_id"])
        if existing is not None:
            updated += 1
        else:
            created += 1
        db.upsert_meta_candidate(
            candidate_id=candidate["candidate_id"],
            kind=candidate["kind"],
            claim=candidate["claim"],
            evidence_json=candidate["evidence"],
            score=candidate["score"],
            status="proposed",
            tenant_id=tenant_id,
            repo_id=repo_id,
        )
        try:
            from hermes_cli.learning_bus import publish_learning_event_safely

            publish_learning_event_safely(
                db,
                topic="learning.candidate.proposed",
                payload=candidate,
                tenant_id=tenant_id,
                repo_id=repo_id,
                event_key=f"candidate:{candidate['candidate_id']}",
            )
        except Exception:
            pass

    run_id = f"learn_{uuid.uuid4().hex[:16]}"
    metrics = {
        "records_scanned": len(records),
        "candidates_created": created,
        "candidates_updated": updated,
        "candidates_proposed": proposed,
        "records_skipped": sum(skipped.values()),
        "skipped": skipped,
        "min_score": min_score,
        "max_records": max_records,
        "policy": policy,
    }
    db.record_learning_run(
        run_id=run_id,
        tenant_id=tenant_id,
        repo_id=repo_id,
        status="completed",
        metrics_json=metrics,
        notes="learning rollup completed",
    )
    try:
        from hermes_cli.learning_bus import publish_learning_event_safely

        publish_learning_event_safely(
            db,
            topic="learning.rollup.completed",
            payload={"run_id": run_id, "metrics": metrics},
            tenant_id=tenant_id,
            repo_id=repo_id,
            event_key=f"rollup:{run_id}",
        )
    except Exception:
        pass
    return LearningRollupResult(
        run_id=run_id,
        status="completed",
        records_scanned=len(records),
        candidates_created=created,
        candidates_updated=updated,
        notes="learning rollup completed",
        metrics=metrics,
    )


def monitor_learning(
    db: SessionDB,
    *,
    tenant_id: Optional[str] = None,
    repo_id: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
) -> LearningMonitorResult:
    learning_policy = (config or load_config()).get("supervisor", {}).get("monitoring", {})
    if not isinstance(learning_policy, dict):
        learning_policy = {}
    if not learning_policy.get("enabled", True):
        return LearningMonitorResult(
            status="disabled",
            runs_observed=0,
            candidates_observed=0,
            readiness_observed=0,
            ready_packets=0,
            blocked_packets=0,
            degraded_packets=0,
            metrics={"enabled": False},
        )
    recent_runs = int(learning_policy.get("recent_runs", 20) or 20)
    metrics = build_learning_metrics(
        db,
        tenant_id=tenant_id,
        repo_id=repo_id,
        recent_runs=recent_runs,
    )
    status = "healthy"
    if metrics["blocked_ratio"] > 0.5 and metrics["ready_ratio"] == 0:
        status = "degraded"
    if metrics.get("task_outcomes_observed", 0) and metrics.get("task_success_ratio", 1.0) < 0.25:
        status = "degraded"
    return LearningMonitorResult(
        status=status,
        runs_observed=metrics["runs_observed"],
        candidates_observed=metrics["candidates_observed"],
        readiness_observed=metrics["readiness_observed"],
        ready_packets=metrics["ready_packets"],
        blocked_packets=metrics["blocked_packets"],
        degraded_packets=metrics["degraded_packets"],
        metrics=metrics,
    )


def reconcile_learning_candidates(
    db: SessionDB,
    *,
    tenant_id: Optional[str] = None,
    repo_id: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
) -> LearningPolicyResult:
    if config is None:
        config = load_config()
    supervisor_cfg = config.get("supervisor", {})
    learning_policy = supervisor_cfg.get("learning", {})
    if not isinstance(learning_policy, dict):
        learning_policy = {}
    promotion_policy = learning_policy.get("promotion", {})
    if not isinstance(promotion_policy, dict):
        promotion_policy = {}
    rollback_policy = learning_policy.get("rollback", {})
    if not isinstance(rollback_policy, dict):
        rollback_policy = {}

    run_id = f"policy_{uuid.uuid4().hex[:16]}"
    metrics = build_learning_metrics(
        db,
        tenant_id=tenant_id,
        repo_id=repo_id,
        recent_runs=int((supervisor_cfg.get("monitoring", {}) or {}).get("recent_runs", 20) or 20),
    )
    monitor = monitor_learning(db, tenant_id=tenant_id, repo_id=repo_id, config=config)

    promotion_enabled = bool(promotion_policy.get("enabled", True))
    rollback_enabled = bool(rollback_policy.get("enabled", True))
    min_score = float(promotion_policy.get("min_score", 0.7) or 0.7)
    min_ready_ratio = float(promotion_policy.get("min_ready_ratio", 0.5) or 0.5)
    auto_apply = bool(promotion_policy.get("auto_apply", False))
    apply_min_score = float(promotion_policy.get("apply_min_score", max(min_score, 0.85)) or max(min_score, 0.85))
    max_candidates = int(promotion_policy.get("max_candidates", 5) or 5)
    blocked_ratio_threshold = float(rollback_policy.get("blocked_ratio", 0.5) or 0.5)
    degraded_statuses = {str(s) for s in (rollback_policy.get("degraded_statuses") or ["degraded"]) if s}

    promoted = 0
    applied = 0
    rolled_back = 0
    skipped: Dict[str, int] = {}

    def mark_skipped(reason: str) -> None:
        skipped[reason] = skipped.get(reason, 0) + 1

    if promotion_enabled and monitor.status not in degraded_statuses and metrics["ready_ratio"] >= min_ready_ratio:
        candidates = db.list_meta_candidates(
            tenant_id=tenant_id,
            repo_id=repo_id,
            status="proposed",
            limit=max_candidates,
        )
        for candidate in candidates:
            score = float(candidate.get("score") or 0.0)
            if score < min_score:
                mark_skipped("below_min_score")
                continue
            if not _candidate_is_auto_promotable(candidate):
                mark_skipped("not_auto_promotable")
                continue
            quality_skip = _candidate_quality_skip_reason(
                candidate,
                learning_policy=learning_policy,
            )
            if quality_skip:
                mark_skipped(f"quality_gate:{quality_skip}")
                continue
            apply_candidate = auto_apply and score >= apply_min_score
            approve_meta_candidate(
                db,
                candidate_id=candidate["id"],
                apply=apply_candidate,
                config=config,
            )
            promoted += 1
            if apply_candidate:
                applied += 1
    if rollback_enabled and (monitor.status in degraded_statuses or metrics["blocked_ratio"] >= blocked_ratio_threshold):
        candidate_rows = db.list_meta_candidates(
            tenant_id=tenant_id,
            repo_id=repo_id,
            status="applied",
            limit=max_candidates,
        )
        candidate_ids = [row["id"] for row in candidate_rows]
        if candidate_ids:
            rollback_targets = rollback_applied_candidates(
                db,
                candidate_ids=candidate_ids,
                config=config,
                reason=(
                    f"monitor={monitor.status} blocked_ratio={metrics['blocked_ratio']:.2f}"
                ),
            )
            rolled_back = len(rollback_targets)

    db.record_learning_run(
        run_id=run_id,
        tenant_id=tenant_id,
        repo_id=repo_id,
        status="completed",
        metrics_json={
            "monitor": monitor.to_dict(),
            "metrics": metrics,
            "promotion_enabled": promotion_enabled,
            "rollback_enabled": rollback_enabled,
            "min_score": min_score,
            "min_ready_ratio": min_ready_ratio,
            "apply_min_score": apply_min_score,
            "blocked_ratio_threshold": blocked_ratio_threshold,
            "promoted": promoted,
            "applied": applied,
            "rolled_back": rolled_back,
            "promotion_skipped": skipped,
        },
        notes="learning policy reconciliation completed",
    )
    try:
        from hermes_cli.learning_bus import publish_learning_event_safely

        publish_learning_event_safely(
            db,
            topic="learning.policy.completed",
            payload={
                "run_id": run_id,
                "promoted": promoted,
                "applied": applied,
                "rolled_back": rolled_back,
                "promotion_skipped": skipped,
            },
            tenant_id=tenant_id,
            repo_id=repo_id,
            event_key=f"policy:{run_id}",
        )
    except Exception:
        pass
    return LearningPolicyResult(
        run_id=run_id,
        status="completed",
        promoted=promoted,
        applied=applied,
        rolled_back=rolled_back,
        notes="learning policy reconciliation completed",
        metrics={
            "monitor": monitor.to_dict(),
            "metrics": metrics,
            "promotion_skipped": skipped,
        },
    )


def _candidate_is_auto_promotable(candidate: Dict[str, Any]) -> bool:
    """Return whether policy reconciliation may auto-approve a candidate."""
    if candidate.get("kind") != "command_repair_policy":
        return True
    evidence = candidate.get("evidence_json")
    if not isinstance(evidence, dict):
        return False
    validation = evidence.get("validation")
    if not isinstance(validation, dict):
        return False
    return bool(validation.get("eligible_for_approval")) and not validation.get("errors")


def _candidate_housekeeping_policy(config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if config is None:
        config = load_config()
    learning = (config.get("supervisor") or {}).get("learning") or {}
    if not isinstance(learning, dict):
        return {}
    policy = learning.get("housekeeping")
    return policy if isinstance(policy, dict) else {}


def _archive_meta_candidate(
    db: SessionDB,
    candidate: Dict[str, Any],
    *,
    reason: str,
    run_id: str,
    now: Optional[float] = None,
) -> bool:
    archived_at = _now() if now is None else now
    evidence = _candidate_evidence_with_action(
        candidate,
        action={
            "archived_at": archived_at,
            "housekeeping_run_id": run_id,
            "previous_status": candidate.get("status"),
            "reason": reason,
        },
    )
    return db.update_meta_candidate_status(
        str(candidate.get("id") or ""),
        status="archived",
        evidence_json=evidence,
    )


def archive_meta_candidate(
    db: SessionDB,
    *,
    candidate_id: str,
    reason: str = "archived by operator",
) -> MetaCandidateActionResult:
    candidate = db.get_meta_candidate(candidate_id)
    if candidate is None:
        raise ValueError(f"unknown meta candidate: {candidate_id}")
    _archive_meta_candidate(
        db,
        candidate,
        reason=reason,
        run_id="manual",
    )
    return MetaCandidateActionResult(
        candidate_id=candidate_id,
        status="archived",
        applied=False,
        config_written=False,
        notes=reason,
        candidate=candidate,
    )


def _candidate_match_text(candidate: Dict[str, Any]) -> str:
    evidence = candidate.get("evidence_json") if isinstance(candidate.get("evidence_json"), dict) else {}
    parts = [
        candidate.get("kind"),
        candidate.get("claim"),
        evidence.get("match"),
        evidence.get("failed_path"),
        evidence.get("working_path"),
        evidence.get("policy_type"),
        evidence.get("mode"),
        evidence.get("assignee"),
        evidence.get("workspace_kind"),
    ]
    return " ".join(str(part) for part in parts if part).casefold()


def _query_tokens(query: str) -> List[str]:
    return [
        token
        for token in re.findall(r"[a-zA-Z0-9_.:/-]+", query.casefold())
        if len(token) >= 4
    ]


def _candidate_matches_query(candidate: Dict[str, Any], query: str) -> bool:
    tokens = _query_tokens(query)
    if not tokens:
        return False
    candidate_tokens = set(_query_tokens(_candidate_match_text(candidate)))
    return any(token in candidate_tokens for token in tokens)


def memory_tier_for_candidate(candidate: Dict[str, Any], *, config: Optional[Dict[str, Any]] = None, now: Optional[float] = None) -> str:
    cfg = config or load_config()
    tiers = (cfg.get("supervisor") or {}).get("memory_tiers") or {}
    if not isinstance(tiers, dict) or tiers.get("enabled", True) is False:
        return "warm"
    evidence = candidate.get("evidence_json") if isinstance(candidate.get("evidence_json"), dict) else {}
    if evidence.get("tier") in {"hot", "warm", "cold"}:
        return str(evidence["tier"])
    score = float(candidate.get("score") or 0.0)
    current = _now() if now is None else now
    created = float(candidate.get("updated_at") or candidate.get("created_at") or current)
    age = max(0.0, current - created)
    if age <= float(tiers.get("hot_ttl_seconds", 86400) or 86400):
        return "hot"
    if score >= float(tiers.get("cold_min_confidence", 0.75) or 0.75):
        return "cold"
    return "warm" if score >= float(tiers.get("warm_min_confidence", 0.6) or 0.6) else "cold"


def update_memory_candidate_feedback(
    db: SessionDB,
    *,
    candidate_id: str,
    outcome: str,
    reason: str = "",
) -> Dict[str, Any]:
    from hermes_cli.memory_retrieval import record_memory_feedback

    return record_memory_feedback(db, candidate_id=candidate_id, outcome=outcome, reason=reason)


def retrieve_learning_context(
    db: SessionDB,
    *,
    query: str,
    tenant_id: Optional[str] = None,
    repo_id: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Return compact approved/applied learning guidance for prompt injection."""
    if config is None:
        config = load_config()
    learning = (config.get("supervisor") or {}).get("learning") or {}
    if not isinstance(learning, dict):
        learning = {}
    injection = learning.get("injection")
    if not isinstance(injection, dict):
        injection = {}
    if injection.get("enabled", True) is False:
        return {
            "status": "disabled",
            "query": query,
            "candidates": [],
            "metrics": {"reason": "learning injection disabled"},
        }

    statuses = [
        str(status)
        for status in (injection.get("statuses") or ["approved", "applied"])
        if status
    ]
    max_candidates = max(0, int(injection.get("max_candidates", 5) or 5))
    min_score = float(injection.get("min_score", 0.6) or 0.6)
    max_chars = max(200, int(injection.get("max_chars", 2500) or 2500))
    require_match = bool(injection.get("require_match", True))
    use_structured = bool(injection.get("structured_retrieval", True))

    if use_structured:
        from hermes_cli.memory_retrieval import (
            build_memory_packet,
            classify_task_query,
            retrieve_memory_candidates,
        )

        task_query = classify_task_query(query, tenant_id=tenant_id, repo_id=repo_id)
        result = retrieve_memory_candidates(
            db,
            query=task_query,
            statuses=statuses,
            limit=max_candidates,
            min_score=min_score,
        )
        structured_skipped: Dict[str, int] = {}
        for status in statuses:
            for candidate in db.list_meta_candidates(
                tenant_id=tenant_id,
                repo_id=repo_id,
                status=status,
                limit=max(max_candidates * 4, 20),
            ):
                quality_skip = _candidate_quality_skip_reason(
                    candidate,
                    learning_policy=learning,
                )
                if quality_skip:
                    key = f"quality_gate:{quality_skip}"
                    structured_skipped[key] = structured_skipped.get(key, 0) + 1
        packet = build_memory_packet(
            query=task_query,
            candidates=result["candidates"],
            max_chars=max_chars,
        )
        candidates = []
        for item in result["candidates"]:
            evidence = item.get("evidence") if isinstance(item.get("evidence"), dict) else {}
            candidates.append(
                {
                    "id": item.get("id"),
                    "kind": item.get("kind"),
                    "claim": item.get("claim"),
                    "score": item.get("score"),
                    "status": item.get("status"),
                    "match": evidence.get("match"),
                    "policy_type": evidence.get("policy_type"),
                    "mode": evidence.get("mode"),
                    "failed_path": evidence.get("failed_path"),
                    "working_path": evidence.get("working_path"),
                    "source_record_id": evidence.get("source_record_id") or evidence.get("record_id"),
                    "evidence_uri": evidence.get("evidence_uri"),
                    "features": item.get("features"),
                    "tier": memory_tier_for_candidate(
                        {"score": item.get("score"), "status": item.get("status"), "evidence_json": evidence},
                        config=config,
                    ),
                }
            )
        return {
            "status": "ready" if candidates else "empty",
            "query": query,
            "candidates": candidates,
            "packet": packet,
            "metrics": {
                **result["audit"],
                "returned": len(candidates),
                "skipped": structured_skipped,
                "statuses": statuses,
                "min_score": min_score,
                "max_candidates": max_candidates,
                "max_chars": max_chars,
                "require_match": require_match,
            },
        }

    selected: List[Dict[str, Any]] = []
    skipped: Dict[str, int] = {}

    def mark_skipped(reason: str) -> None:
        skipped[reason] = skipped.get(reason, 0) + 1

    for status in statuses:
        scan_limit = max(max_candidates * 4, 20)
        rows = db.list_meta_candidates(
            tenant_id=tenant_id,
            repo_id=repo_id,
            status=status,
            limit=scan_limit,
        )
        if tenant_id is not None or repo_id is not None:
            rows.extend(
                db.list_meta_candidates(
                    tenant_id=None,
                    repo_id=None,
                    status=status,
                    limit=scan_limit,
                )
            )
        for candidate in rows:
            if len(selected) >= max_candidates:
                break
            if any(existing.get("id") == candidate.get("id") for existing in selected):
                mark_skipped("duplicate_candidate")
                continue
            score = float(candidate.get("score") or 0.0)
            if score < min_score:
                mark_skipped("below_min_score")
                continue
            quality_skip = _candidate_quality_skip_reason(
                candidate,
                learning_policy=learning,
            )
            if quality_skip:
                mark_skipped(f"quality_gate:{quality_skip}")
                continue
            if require_match and not _candidate_matches_query(candidate, query):
                mark_skipped("query_mismatch")
                continue
            evidence = candidate.get("evidence_json") if isinstance(candidate.get("evidence_json"), dict) else {}
            selected.append(
                {
                    "id": candidate.get("id"),
                    "kind": candidate.get("kind"),
                    "claim": candidate.get("claim"),
                    "score": score,
                    "status": candidate.get("status"),
                    "match": evidence.get("match"),
                    "assignee": evidence.get("assignee"),
                    "workspace_kind": evidence.get("workspace_kind"),
                    "policy_type": evidence.get("policy_type"),
                    "mode": evidence.get("mode"),
                    "failed_path": evidence.get("failed_path"),
                    "working_path": evidence.get("working_path"),
                    "source_record_id": evidence.get("source_record_id") or evidence.get("record_id"),
                    "evidence_uri": evidence.get("evidence_uri"),
                }
            )
        if len(selected) >= max_candidates:
            break

    rendered = json.dumps(selected, ensure_ascii=False, sort_keys=True)
    truncated = False
    if len(rendered) > max_chars:
        truncated = True
        kept: List[Dict[str, Any]] = []
        total = 2
        for candidate in selected:
            candidate_text = json.dumps(candidate, ensure_ascii=False, sort_keys=True)
            if total + len(candidate_text) + 2 > max_chars:
                break
            kept.append(candidate)
            total += len(candidate_text) + 2
        selected = kept

    return {
        "status": "ready" if selected else "empty",
        "query": query,
        "candidates": selected,
        "metrics": {
            "returned": len(selected),
            "skipped": skipped,
            "statuses": statuses,
            "min_score": min_score,
            "max_candidates": max_candidates,
            "max_chars": max_chars,
            "truncated": truncated,
        },
    }


def run_candidate_housekeeping(
    db: SessionDB,
    *,
    tenant_id: Optional[str] = None,
    repo_id: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
    dry_run: bool = False,
    now: Optional[float] = None,
) -> CandidateHousekeepingResult:
    """Archive stale/noisy meta-candidates without blocking runtime execution."""
    policy = _candidate_housekeeping_policy(config)
    if policy.get("enabled", True) is False:
        return CandidateHousekeepingResult(
            status="disabled",
            scanned=0,
            archived=0,
            skipped=0,
            dry_run=bool(dry_run),
            metrics={"reason": "housekeeping disabled"},
        )

    now_ts = _now() if now is None else float(now)
    run_id = f"hk_{uuid.uuid4().hex[:16]}"
    max_scan = max(1, int(policy.get("max_scan", 1000) or 1000))
    max_per_run = max(1, int(policy.get("max_candidates_per_run", 100) or 100))
    max_runtime_seconds = max(0.1, float(policy.get("max_runtime_seconds", 10) or 10))
    proposed_ttl_days = float(policy.get("proposed_ttl_days", 7) or 0)
    rejected_ttl_days = float(policy.get("rejected_ttl_days", 30) or 0)
    approved_ttl_days = float(policy.get("approved_ttl_days", 0) or 0)
    max_candidates_per_kind = int(policy.get("max_candidates_per_kind", 25) or 0)
    learning_policy = (config or load_config()).get("supervisor", {}).get("learning", {})
    if not isinstance(learning_policy, dict):
        learning_policy = {}
    archive_invalid_proposed = bool(
        _rollup_filter_policy(learning_policy).get("archive_invalid_proposed", True)
    )
    archive_invalid_approved = bool(
        _rollup_filter_policy(learning_policy).get("archive_invalid_approved", True)
    )

    rows = db.list_meta_candidates(
        tenant_id=tenant_id,
        repo_id=repo_id,
        limit=max_scan,
    )
    start_ts = _now()
    items: List[CandidateHousekeepingItem] = []
    archived = 0
    skipped = 0
    errors: List[str] = []
    planned_ids: set[str] = set()
    by_kind_status: Dict[str, int] = {}

    def age_days(row: Dict[str, Any]) -> float:
        created = float(row.get("created_at") or row.get("updated_at") or now_ts)
        return max(0.0, (now_ts - created) / 86400.0)

    def plan_archive(row: Dict[str, Any], reason: str) -> None:
        nonlocal archived, skipped
        candidate_id = str(row.get("id") or "")
        if not candidate_id or candidate_id in planned_ids:
            return
        if len(items) >= max_per_run:
            skipped += 1
            return
        if _now() - start_ts > max_runtime_seconds:
            skipped += 1
            return
        planned_ids.add(candidate_id)
        item = CandidateHousekeepingItem(
            candidate_id=candidate_id,
            kind=str(row.get("kind") or ""),
            status=str(row.get("status") or ""),
            action="archive",
            reason=reason,
            score=row.get("score"),
            created_at=row.get("created_at"),
            updated_at=row.get("updated_at"),
        )
        items.append(item)
        if dry_run:
            return
        try:
            if _archive_meta_candidate(db, row, reason=reason, run_id=run_id, now=now_ts):
                archived += 1
            else:
                skipped += 1
        except Exception as exc:
            errors.append(f"{candidate_id}: {exc}")

    for row in rows:
        status = str(row.get("status") or "")
        kind_status_key = f"{row.get('kind') or 'unknown'}:{status or 'unknown'}"
        by_kind_status[kind_status_key] = by_kind_status.get(kind_status_key, 0) + 1
        if status == "proposed" and proposed_ttl_days > 0 and age_days(row) >= proposed_ttl_days:
            plan_archive(row, f"proposed candidate older than {proposed_ttl_days:g} days")
        elif status == "rejected" and rejected_ttl_days > 0 and age_days(row) >= rejected_ttl_days:
            plan_archive(row, f"rejected candidate older than {rejected_ttl_days:g} days")
        elif status == "approved" and approved_ttl_days > 0 and age_days(row) >= approved_ttl_days:
            plan_archive(row, f"approved candidate older than {approved_ttl_days:g} days")
        elif (
            (status == "proposed" and archive_invalid_proposed)
            or (status == "approved" and archive_invalid_approved)
        ):
            quality_skip = _candidate_quality_skip_reason(row, learning_policy=learning_policy)
            if quality_skip:
                plan_archive(row, f"quality gate failed: {quality_skip}")

    if max_candidates_per_kind > 0:
        grouped: Dict[str, List[Dict[str, Any]]] = {}
        for row in rows:
            if str(row.get("status") or "") != "proposed":
                continue
            kind = str(row.get("kind") or "unknown")
            grouped.setdefault(kind, []).append(row)
        for kind, kind_rows in grouped.items():
            kind_rows.sort(key=lambda row: float(row.get("created_at") or 0), reverse=True)
            for row in kind_rows[max_candidates_per_kind:]:
                plan_archive(
                    row,
                    f"exceeds max proposed candidates per kind ({max_candidates_per_kind}) for {kind}",
                )

    status = "completed" if not errors else "completed_with_errors"
    if dry_run:
        archived = 0
    return CandidateHousekeepingResult(
        status=status,
        scanned=len(rows),
        archived=archived,
        skipped=skipped,
        dry_run=bool(dry_run),
        items=items,
        metrics={
            "run_id": run_id,
            "planned": len(items),
            "max_scan": max_scan,
            "max_candidates_per_run": max_per_run,
            "max_candidates_per_kind": max_candidates_per_kind,
            "by_kind_status": by_kind_status,
        },
        errors=errors,
    )


def run_learning_sidecar(
    db_factory: Optional[Callable[[], SessionDB]] = None,
    *,
    tenant_id: Optional[str] = None,
    repo_id: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
    interval_seconds: float = 300.0,
    once: bool = False,
    stop_event: Any = None,
    rollup_fn: Callable[..., LearningRollupResult] = rollup_learning_candidates,
    monitor_fn: Callable[..., LearningMonitorResult] = monitor_learning,
    reconcile_fn: Callable[..., LearningPolicyResult] = reconcile_learning_candidates,
    sleep_fn: Callable[[float], None] = time.sleep,
    on_tick: Optional[Callable[[LearningSidecarTickResult], None]] = None,
    housekeeping_fn: Callable[..., CandidateHousekeepingResult] = run_candidate_housekeeping,
) -> LearningSidecarResult:
    """Run the optional learning sidecar loop.

    The sidecar is intentionally thin: it reuses the existing monitor and
    policy reconciliation paths rather than inventing a parallel control
    plane. Each tick performs rollup -> monitor -> reconcile so task-event
    captures can become candidates without a separate manual command.
    ``once=True`` runs a single tick and exits; otherwise the loop sleeps for
    ``interval_seconds`` between ticks until ``stop_event`` is set.
    """
    if db_factory is None:
        db_factory = SessionDB

    ticks = 0
    errors: List[str] = []
    last_tick: Optional[LearningSidecarTickResult] = None
    housekeeping_policy = _candidate_housekeeping_policy(config)
    housekeeping_interval = float(
        housekeeping_policy.get("interval_seconds", 3600) or 3600
    )
    last_housekeeping_at = 0.0
    while True:
        tick_errors: List[str] = []
        try:
            with contextlib.closing(db_factory()) as db:
                rollup = rollup_fn(
                    db,
                    tenant_id=tenant_id,
                    repo_id=repo_id,
                    config=config,
                )
                monitor = monitor_fn(
                    db,
                    tenant_id=tenant_id,
                    repo_id=repo_id,
                    config=config,
                )
                policy = reconcile_fn(
                    db,
                    tenant_id=tenant_id,
                    repo_id=repo_id,
                    config=config,
                )
                housekeeping: Dict[str, Any] = {
                    "status": "skipped",
                    "reason": "interval_not_due",
                }
                if housekeeping_policy.get("enabled", True) is not False:
                    current_ts = _now()
                    if (
                        once
                        or last_housekeeping_at <= 0
                        or current_ts - last_housekeeping_at >= housekeeping_interval
                    ):
                        try:
                            housekeeping = housekeeping_fn(
                                db,
                                tenant_id=tenant_id,
                                repo_id=repo_id,
                                config=config,
                                dry_run=False,
                            ).to_dict()
                            last_housekeeping_at = current_ts
                        except Exception as exc:
                            err = f"housekeeping: {exc}"
                            tick_errors.append(err)
                            errors.append(err)
                            housekeeping = {"status": "error", "error": str(exc)}
                else:
                    housekeeping = {"status": "disabled"}
                try:
                    from hermes_cli.learning_bus import learning_bus_metrics

                    bus = learning_bus_metrics(db)
                except Exception as exc:
                    bus = {"status": "error", "error": str(exc)}
                last_tick = LearningSidecarTickResult(
                    rollup=rollup.to_dict(),
                    monitor=monitor.to_dict(),
                    policy=policy.to_dict(),
                    housekeeping=housekeeping,
                    bus=bus,
                    errors=list(tick_errors),
                )
        except Exception as exc:
            err = str(exc)
            tick_errors.append(err)
            errors.append(err)
            last_tick = LearningSidecarTickResult(
                rollup={"status": "error"},
                monitor={"status": "error"},
                policy={"status": "error"},
                housekeeping={"status": "error"},
                bus={"status": "error"},
                errors=list(tick_errors),
            )
        ticks += 1
        if on_tick is not None and last_tick is not None:
            try:
                on_tick(last_tick)
            except Exception as exc:
                err = str(exc)
                tick_errors.append(err)
                errors.append(err)
                last_tick.errors.append(err)
        if once:
            break
        if stop_event is not None and getattr(stop_event, "is_set", lambda: False)():
            break
        try:
            sleep_fn(max(0.0, float(interval_seconds)))
        except Exception as exc:
            err = str(exc)
            tick_errors.append(err)
            errors.append(err)
            if once:
                break
    status = "completed" if not errors else "completed_with_errors"
    return LearningSidecarResult(
        status=status,
        ticks=ticks,
        interval_seconds=float(interval_seconds),
        once=bool(once),
        tenant_id=tenant_id,
        repo_id=repo_id,
        last_tick=last_tick,
        errors=errors,
        metrics={
            "ticks": ticks,
            "errors": len(errors),
        },
    )


def _remove_candidate_refs_from_bucket(bucket: List[Dict[str, Any]], candidate_ids: set[str]) -> int:
    removed = 0
    kept: List[Dict[str, Any]] = []
    for entry in bucket:
        if not isinstance(entry, dict):
            kept.append(entry)
            continue
        entry_id = str(entry.get("candidate_id") or entry.get("id") or "").strip()
        if entry_id and entry_id in candidate_ids:
            removed += 1
            continue
        kept.append(entry)
    bucket[:] = kept
    return removed


def rollback_applied_candidates(
    db: SessionDB,
    *,
    candidate_ids: Iterable[str],
    config: Optional[Dict[str, Any]] = None,
    reason: str = "learning monitor degraded",
) -> List[str]:
    if config is None:
        config = load_config()
    candidate_id_set = {str(cid).strip() for cid in candidate_ids if str(cid).strip()}
    if not candidate_id_set:
        return []
    supervisor = config.setdefault("supervisor", {})
    if not isinstance(supervisor, dict):
        supervisor = {}
        config["supervisor"] = supervisor
    learning = supervisor.setdefault("learning", {})
    if not isinstance(learning, dict):
        learning = {}
        supervisor["learning"] = learning

    active_buckets = [
        "approved_candidates",
        "applied_candidates",
        "routing_hints",
        "validation_recipes",
        "hook_rules",
        "memory_rules",
        "recovery_hints",
        "playbooks",
    ]
    rolled_back: List[str] = []
    for bucket_name in active_buckets:
        bucket = learning.get(bucket_name)
        if isinstance(bucket, list):
            _remove_candidate_refs_from_bucket(bucket, candidate_id_set)

    history = learning.setdefault("rolled_back_candidates", [])
    if not isinstance(history, list):
        history = []
        learning["rolled_back_candidates"] = history

    now = _now()
    for candidate_id in candidate_id_set:
        candidate = db.get_meta_candidate(candidate_id)
        if candidate is None:
            continue
        db.update_meta_candidate_status(
            candidate_id,
            status="rolled_back",
            evidence_json={
                "rolled_back_at": now,
                "reason": reason,
            },
        )
        rolled_back.append(candidate_id)
        _append_unique_entry(
            history,
            {
                "id": candidate_id,
                "kind": candidate.get("kind"),
                "claim": candidate.get("claim"),
                "score": candidate.get("score"),
                "status": "rolled_back",
                "rolled_back_at": now,
                "reason": reason,
            },
        )

    if rolled_back:
        from hermes_cli.config import save_config

        save_config(config)
    return rolled_back


def _candidate_targets(candidate: Dict[str, Any]) -> List[str]:
    kind = str(candidate.get("kind") or "").strip()
    claim = str(candidate.get("claim") or "").strip()
    if not kind and not claim:
        return []
    if kind == "routing_hint":
        return ["supervisor.learning.routing_hints"]
    if kind == "validation_recipe":
        return ["supervisor.learning.validation_recipes"]
    if kind == "hook_rule":
        return ["supervisor.learning.hook_rules"]
    if kind == "memory_rule":
        return ["supervisor.learning.memory_rules"]
    if kind == "recovery_hint":
        return ["supervisor.learning.recovery_hints"]
    return ["supervisor.learning.playbooks"]


def _append_unique_entry(container: List[Dict[str, Any]], entry: Dict[str, Any], key: str = "id") -> None:
    seen = {str(item.get(key)) for item in container if item.get(key) is not None}
    identifier = str(entry.get(key) or "")
    if identifier and identifier in seen:
        return
    container.append(entry)


def _structured_routing_hint(candidate: Dict[str, Any], applied_at: Optional[float] = None) -> Dict[str, Any]:
    evidence = candidate.get("evidence_json") if isinstance(candidate.get("evidence_json"), dict) else {}
    match = str(candidate.get("match") or evidence.get("match") or candidate.get("claim") or "").strip()
    assignee = candidate.get("assignee") or evidence.get("assignee") or evidence.get("profile") or evidence.get("worker")
    workspace_kind = candidate.get("workspace_kind") or evidence.get("workspace_kind")
    hint = {
        "id": candidate.get("id"),
        "candidate_id": candidate.get("id"),
        "kind": "routing_hint",
        "match": match,
        "assignee": assignee,
        "workspace_kind": workspace_kind,
        "claim": candidate.get("claim"),
        "score": candidate.get("score"),
        "status": candidate.get("status"),
        "tenant_id": candidate.get("tenant_id"),
        "repo_id": candidate.get("repo_id"),
        "applied_at": applied_at or _now(),
    }
    if evidence:
        hint["evidence_json"] = evidence
    return hint


def apply_meta_candidate_to_config(
    config: Dict[str, Any],
    candidate: Dict[str, Any],
) -> List[str]:
    supervisor = config.setdefault("supervisor", {})
    if not isinstance(supervisor, dict):
        supervisor = {}
        config["supervisor"] = supervisor
    learning = supervisor.setdefault("learning", {})
    if not isinstance(learning, dict):
        learning = {}
        supervisor["learning"] = learning

    applied_at = _now()
    entry = {
        "id": candidate.get("id"),
        "kind": candidate.get("kind"),
        "claim": candidate.get("claim"),
        "score": candidate.get("score"),
        "status": candidate.get("status"),
        "applied_at": applied_at,
    }
    evidence = candidate.get("evidence_json")
    if isinstance(evidence, dict) and evidence:
        entry["evidence_json"] = evidence
    targets = _candidate_targets(candidate)

    approved = learning.setdefault("approved_candidates", [])
    if not isinstance(approved, list):
        approved = []
        learning["approved_candidates"] = approved
    _append_unique_entry(approved, entry)

    applied = learning.setdefault("applied_candidates", [])
    if not isinstance(applied, list):
        applied = []
        learning["applied_candidates"] = applied
    _append_unique_entry(applied, entry)

    target_key_map = {
        "supervisor.learning.routing_hints": "routing_hints",
        "supervisor.learning.validation_recipes": "validation_recipes",
        "supervisor.learning.hook_rules": "hook_rules",
        "supervisor.learning.memory_rules": "memory_rules",
        "supervisor.learning.recovery_hints": "recovery_hints",
        "supervisor.learning.playbooks": "playbooks",
    }
    for target in targets:
        bucket_name = target_key_map.get(target, "playbooks")
        bucket = learning.setdefault(bucket_name, [])
        if not isinstance(bucket, list):
            bucket = []
            learning[bucket_name] = bucket
        if bucket_name == "routing_hints":
            _append_unique_entry(bucket, _structured_routing_hint(candidate, applied_at))
        else:
            _append_unique_entry(bucket, entry)
    return targets


def approve_meta_candidate(
    db: SessionDB,
    *,
    candidate_id: str,
    apply: bool = False,
    config: Optional[Dict[str, Any]] = None,
) -> MetaCandidateActionResult:
    candidate = db.get_meta_candidate(candidate_id)
    if candidate is None:
        raise ValueError(f"unknown meta candidate: {candidate_id}")

    if config is None:
        config = load_config()
    targets: List[str] = []
    config_written = False
    applied = False
    notes = "candidate approved"

    if apply:
        targets = apply_meta_candidate_to_config(config, candidate)
        from hermes_cli.config import save_config

        save_config(config)
        config_written = True
        applied = True
        notes = "candidate approved and applied to config"
        evidence = _candidate_evidence_with_action(
            candidate,
            action={"applied_at": _now(), "targets": targets},
        )
        db.update_meta_candidate_status(
            candidate_id,
            status="applied",
            evidence_json=evidence,
        )
    else:
        evidence = _candidate_evidence_with_action(
            candidate,
            action={"approved_at": _now(), "targets": _candidate_targets(candidate)},
        )
        db.update_meta_candidate_status(
            candidate_id,
            status="approved",
            evidence_json=evidence,
        )
        targets = _candidate_targets(candidate)

    return MetaCandidateActionResult(
        candidate_id=candidate_id,
        status="applied" if applied else "approved",
        applied=applied,
        config_written=config_written,
        config_targets=targets,
        notes=notes,
        candidate=candidate,
    )


def _candidate_evidence_with_action(
    candidate: Dict[str, Any],
    *,
    action: Dict[str, Any],
) -> Dict[str, Any]:
    evidence = candidate.get("evidence_json")
    merged = dict(evidence) if isinstance(evidence, dict) else {}
    actions = merged.get("actions")
    if not isinstance(actions, list):
        actions = []
    actions.append(action)
    merged["actions"] = actions
    merged.update(action)
    return merged


def reject_meta_candidate(
    db: SessionDB,
    *,
    candidate_id: str,
    reason: str = "rejected by policy",
) -> MetaCandidateActionResult:
    candidate = db.get_meta_candidate(candidate_id)
    if candidate is None:
        raise ValueError(f"unknown meta candidate: {candidate_id}")
    evidence = _candidate_evidence_with_action(
        candidate,
        action={"rejected_at": _now(), "reason": reason},
    )
    db.update_meta_candidate_status(
        candidate_id,
        status="rejected",
        evidence_json=evidence,
    )
    return MetaCandidateActionResult(
        candidate_id=candidate_id,
        status="rejected",
        applied=False,
        config_written=False,
        notes=reason,
        candidate=candidate,
    )


def apply_learning_judge_decision(
    db: SessionDB,
    *,
    decision: Any,
    config: Optional[Dict[str, Any]] = None,
    allow_enforcement: bool = False,
) -> MetaCandidateActionResult:
    """Persist a strict learning-judge decision against a meta-candidate.

    Judge approval is advisory by default. Runtime config application still
    requires the global allow_enforcement policy and the decision's explicit
    allow_enforcement flag.
    """
    candidate_id = str(getattr(decision, "candidate_id", "") or "")
    candidate = db.get_meta_candidate(candidate_id)
    if candidate is None:
        raise ValueError(f"unknown meta candidate: {candidate_id}")
    decision_value = str(getattr(decision, "decision", "") or "")
    confidence = float(getattr(decision, "confidence", 0.0) or 0.0)
    rationale = str(getattr(decision, "rationale", "") or "")
    risk_flags = list(getattr(decision, "risk_flags", []) or [])
    action = {
        "judged_at": _now(),
        "judge_decision": decision_value,
        "judge_confidence": confidence,
        "judge_rationale": rationale,
        "judge_risk_flags": risk_flags,
        "judge_allow_enforcement": bool(getattr(decision, "allow_enforcement", False)),
    }
    evidence = _candidate_evidence_with_action(candidate, action=action)
    db.update_meta_candidate_status(
        candidate_id,
        status=str(candidate.get("status") or "proposed"),
        evidence_json=evidence,
    )

    if decision_value == "approve":
        should_apply = bool(allow_enforcement and getattr(decision, "allow_enforcement", False))
        return approve_meta_candidate(
            db,
            candidate_id=candidate_id,
            apply=should_apply,
            config=config,
        )
    if decision_value == "reject":
        return reject_meta_candidate(
            db,
            candidate_id=candidate_id,
            reason=f"learning judge rejected: {rationale}",
        )

    updated = db.get_meta_candidate(candidate_id) or candidate
    db.update_meta_candidate_status(candidate_id, status="needs_human", evidence_json=evidence)
    updated = db.get_meta_candidate(candidate_id) or updated
    return MetaCandidateActionResult(
        candidate_id=candidate_id,
        status="needs_human",
        applied=False,
        config_written=False,
        notes=rationale or "learning judge requested human review",
        candidate=updated,
    )


def search_memory_context(
    db: SessionDB,
    *,
    query: str,
    tenant_id: Optional[str] = None,
    repo_id: Optional[str] = None,
    limit: int = 10,
) -> Dict[str, Any]:
    records = db.search_memory_records(
        query,
        tenant_id=tenant_id,
        repo_id=repo_id,
        limit=limit,
    )
    packets = db.list_memory_packets(
        tenant_id=tenant_id,
        repo_id=repo_id,
        limit=limit,
    )
    return {
        "query": query,
        "records": records,
        "packets": packets,
        "claims": [_build_claim_from_record(record) for record in records],
        "evidence": [_build_evidence_from_record(record) for record in records if record.get("evidence_uri")],
    }


def create_memory_packet(
    db: SessionDB,
    *,
    query: str,
    tenant_id: Optional[str] = None,
    repo_id: Optional[str] = None,
    job_id: Optional[str] = None,
    task_id: Optional[str] = None,
    scopes: Optional[Iterable[str]] = None,
    required: bool = False,
    config: Optional[Dict[str, Any]] = None,
) -> MemoryPacketResult:
    policy = get_supervisor_memory_policy(config)
    scope_list = _as_list(scopes) or [s for s in (tenant_id, repo_id, job_id, task_id) if s]
    search_limit = int(policy.get("search_limit", 12) or 12)
    min_evidence = int(policy.get("min_evidence_items", 1) or 1)
    ttl_seconds = int(policy.get("packet_ttl_seconds", 3600) or 3600)
    search = search_memory_context(
        db,
        query=query,
        tenant_id=tenant_id,
        repo_id=repo_id,
        limit=search_limit,
    )
    claims = search["claims"]
    evidence = search["evidence"]
    contradictions: List[Dict[str, Any]] = []
    freshness = {
        "policy": "fresh",
        "candidate_count": len(claims),
        "evidence_count": len(evidence),
    }

    if len(evidence) < min_evidence and claims:
        status = "degraded"
        freshness["policy"] = "weak-evidence"
    elif claims:
        status = "ready"
    elif required and policy.get("block_on_missing_packet", True):
        status = "blocked"
    elif required:
        status = "empty"
    else:
        status = "empty"

    confidence = 0.0
    if claims:
        scores = [float(c.get("score") or 0.0) for c in claims]
        confidence = sum(scores) / len(scores) if scores else 0.35
        if confidence == 0.0:
            confidence = 0.35 if evidence else 0.15

    packet_id = f"mempkt_{uuid.uuid4().hex[:16]}"
    created_at = _now()
    packet = MemoryPacketResult(
        packet_id=packet_id,
        status=status,
        query=query,
        scopes=scope_list,
        claims=claims,
        evidence=evidence,
        contradictions=contradictions,
        freshness=freshness,
        confidence=confidence,
        created_at=created_at,
        expires_at=created_at + ttl_seconds if ttl_seconds > 0 else None,
    )

    db.upsert_memory_packet(
        packet_id=packet.packet_id,
        query=query,
        status=packet.status,
        tenant_id=tenant_id,
        repo_id=repo_id,
        job_id=job_id,
        task_id=task_id,
        scopes=packet.scopes,
        claims_json=packet.claims,
        evidence_json=packet.evidence,
        contradictions_json=packet.contradictions,
        freshness_json=packet.freshness,
        confidence=packet.confidence,
        source=packet.source,
        expires_at=packet.expires_at,
    )

    for claim in claims:
        db.upsert_memory_record(
            record_id=str(claim.get("record_id") or uuid.uuid4().hex),
            kind=str(claim.get("kind") or "claim"),
            title=claim.get("title"),
            body=claim.get("body"),
            payload_json=claim,
            status=str(claim.get("status") or "active"),
            score=float(claim.get("score") or 0.0) if claim.get("score") is not None else None,
            tenant_id=tenant_id,
            repo_id=repo_id,
            job_id=job_id,
            task_id=task_id,
            packet_id=packet.packet_id,
            evidence_uri=claim.get("evidence_uri"),
            evidence_sha256=claim.get("evidence_sha256"),
        )

    db.record_memory_readiness(
        status=packet.status,
        scope=",".join(packet.scopes) if packet.scopes else "global",
        required=required,
        reason="packet_created" if packet.status == "ready" else "packet_created_with_fallback",
        packet_id=packet.packet_id,
        tenant_id=tenant_id,
        repo_id=repo_id,
        job_id=job_id,
        task_id=task_id,
        policy_version="v1",
        config_snapshot=policy,
    )
    return packet


def evaluate_memory_readiness(
    db: SessionDB,
    *,
    query: str,
    tenant_id: Optional[str] = None,
    repo_id: Optional[str] = None,
    job_id: Optional[str] = None,
    task_id: Optional[str] = None,
    required: bool = False,
    scopes: Optional[Iterable[str]] = None,
    config: Optional[Dict[str, Any]] = None,
) -> MemoryReadinessResult:
    policy = get_supervisor_memory_policy(config)
    if not policy.get("enabled", True):
        result = MemoryReadinessResult(
            status="not_required" if not required else "blocked",
            reason="supervisor memory disabled in config",
            required=required,
            query=query,
            scopes=_as_list(scopes),
            policy_version="v1",
        )
        db.record_memory_readiness(
            status=result.status,
            scope=",".join(result.scopes) if result.scopes else "global",
            required=required,
            reason=result.reason,
            tenant_id=tenant_id,
            repo_id=repo_id,
            job_id=job_id,
            task_id=task_id,
            policy_version=result.policy_version,
            config_snapshot=policy,
        )
        return result

    search = search_memory_context(
        db,
        query=query,
        tenant_id=tenant_id,
        repo_id=repo_id,
        limit=int(policy.get("search_limit", 12) or 12),
    )
    claims = search["claims"]
    evidence = search["evidence"]
    packet_rows = db.list_memory_packets(
        tenant_id=tenant_id,
        repo_id=repo_id,
        job_id=job_id,
        task_id=task_id,
        limit=1,
    )
    packet = packet_rows[0] if packet_rows else None
    now = _now()

    packet_id = None
    packet_reason = None
    if packet:
        expires_at = packet.get("expires_at")
        if expires_at is None or float(expires_at) >= now:
            packet_id = packet.get("id")
            packet_reason = "packet_available"
        else:
            packet_reason = "packet_expired"

    if packet_id:
        status = "ready"
        reason = packet_reason or "packet_available"
    elif claims and len(evidence) >= int(policy.get("min_evidence_items", 1) or 1):
        status = "ready"
        reason = "candidate_memory_available"
    elif claims:
        status = "degraded"
        reason = "insufficient_evidence"
    elif required and policy.get("block_on_missing_packet", True):
        status = "blocked"
        reason = "required_packet_missing"
    elif required:
        status = "empty"
        reason = "required_packet_missing_but_fallback_allowed"
    else:
        status = "not_required"
        reason = "memory_optional"

    result = MemoryReadinessResult(
        status=status,
        reason=reason,
        packet_id=packet_id,
        required=required,
        candidate_count=len(claims),
        evidence_count=len(evidence),
        query=query,
        scopes=_as_list(scopes),
        checked_at=now,
        policy_version="v1",
    )
    db.record_memory_readiness(
        status=result.status,
        scope=",".join(result.scopes) if result.scopes else "global",
        required=required,
        reason=result.reason,
        packet_id=result.packet_id,
        tenant_id=tenant_id,
        repo_id=repo_id,
        job_id=job_id,
        task_id=task_id,
        policy_version=result.policy_version,
        config_snapshot={
            "policy": policy,
            "search_limit": policy.get("search_limit", 12),
            "min_evidence_items": policy.get("min_evidence_items", 1),
        },
    )
    return result
