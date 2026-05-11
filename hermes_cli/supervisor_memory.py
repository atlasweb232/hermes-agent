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
class LearningSidecarTickResult:
    rollup: Dict[str, Any]
    monitor: Dict[str, Any]
    policy: Dict[str, Any]
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
    for record in records:
        text = " ".join(
            str(part).strip()
            for part in (
                record.get("title"),
                record.get("body"),
                json.dumps(record.get("payload_json") or {}, ensure_ascii=False),
            )
            if part
        ).strip()
        if not text:
            continue
        kind = classify_meta_candidate_kind(text)
        claim = (record.get("title") or record.get("body") or text).strip()
        claim = claim[:240]
        if not claim:
            continue
        candidate_id = _stable_candidate_id(
            kind=kind,
            claim=claim,
            tenant_id=tenant_id or str(record.get("tenant_id") or ""),
            repo_id=repo_id or str(record.get("repo_id") or ""),
        )
        if candidate_id in seen:
            continue
        seen.add(candidate_id)
        score = float(record.get("score") or 0.0)
        if score <= 0.0:
            score = 0.35 if record.get("evidence_uri") else 0.2
        if record.get("status") not in {"active", "promoted", "ready"}:
            score *= 0.8
        if score < min_score:
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
        existing = db.list_meta_candidates(
            tenant_id=tenant_id,
            repo_id=repo_id,
            kind=candidate["kind"],
            status=None,
            limit=max_records,
        )
        if any(row["id"] == candidate["candidate_id"] for row in existing):
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

    run_id = f"learn_{uuid.uuid4().hex[:16]}"
    metrics = {
        "records_scanned": len(records),
        "candidates_created": created,
        "candidates_updated": updated,
        "candidates_proposed": proposed,
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
        },
        notes="learning policy reconciliation completed",
    )
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
        },
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
                last_tick = LearningSidecarTickResult(
                    rollup=rollup.to_dict(),
                    monitor=monitor.to_dict(),
                    policy=policy.to_dict(),
                    errors=[],
                )
        except Exception as exc:
            err = str(exc)
            tick_errors.append(err)
            errors.append(err)
            last_tick = LearningSidecarTickResult(
                rollup={"status": "error"},
                monitor={"status": "error"},
                policy={"status": "error"},
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
        db.update_meta_candidate_status(
            candidate_id,
            status="applied",
            evidence_json={
                "applied_at": _now(),
                "targets": targets,
            },
        )
    else:
        db.update_meta_candidate_status(
            candidate_id,
            status="approved",
            evidence_json={
                "approved_at": _now(),
                "targets": _candidate_targets(candidate),
            },
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


def reject_meta_candidate(
    db: SessionDB,
    *,
    candidate_id: str,
    reason: str = "rejected by policy",
) -> MetaCandidateActionResult:
    candidate = db.get_meta_candidate(candidate_id)
    if candidate is None:
        raise ValueError(f"unknown meta candidate: {candidate_id}")
    db.update_meta_candidate_status(
        candidate_id,
        status="rejected",
        evidence_json={
            "rejected_at": _now(),
            "reason": reason,
        },
    )
    return MetaCandidateActionResult(
        candidate_id=candidate_id,
        status="rejected",
        applied=False,
        config_written=False,
        notes=reason,
        candidate=candidate,
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
