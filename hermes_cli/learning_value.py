"""Cost/value observability helpers for runtime learning.

The functions in this module are deterministic by design. They summarize
whether existing memory avoided work, how much context was injected, and how a
baseline run compares to a memory-assisted run without calling curator, judge,
dreaming, or any other LLM-backed sidecar.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import re
import time
from typing import Any, Dict, List, Optional, Sequence

from hermes_cli.global_memory import (
    GlobalPreCurationEvent,
    hydrate_task_memory_from_global,
    run_persisted_global_precuration,
)
from hermes_state import SessionDB


def _now() -> float:
    return time.time()


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_status(value: Any) -> str:
    text = str(value or "").strip().lower()
    return text if text in {"success", "failed", "blocked", "timeout", "unknown"} else "unknown"


def command_family(command: str) -> str:
    text = str(command or "").strip()
    if not text:
        return ""
    first = re.split(r"\s+", text, maxsplit=1)[0]
    return first.strip()


def count_repeated_error_signatures(events: Sequence[Dict[str, Any]]) -> int:
    """Count repeated failing command/error signatures.

    A single failure is useful evidence but not a repeated-error loop. This
    returns the number of extra repeats beyond the first occurrence for each
    `(command_family, error_signature)` pair.
    """
    counts: Dict[tuple[str, str], int] = {}
    for event in events or []:
        status = _safe_status(event.get("status") or event.get("outcome"))
        if status == "success":
            continue
        family = str(event.get("command_family") or command_family(str(event.get("command") or "")))
        signature = str(event.get("error_signature") or event.get("failure_signature") or event.get("error") or "")
        if not family and not signature:
            continue
        key = (family, signature)
        counts[key] = counts.get(key, 0) + 1
    return sum(max(0, count - 1) for count in counts.values())


@dataclass
class LearningValueReport:
    id: str
    event_id: str
    tenant_id: Optional[str]
    repo_id: Optional[str]
    worker_model: str = ""
    worker_provider: str = ""
    memory_status: str = "unknown"
    memory_hits: int = 0
    global_lesson_hits: int = 0
    global_lesson_near_hits: int = 0
    global_lesson_misses: int = 0
    hot_cache_hits: int = 0
    skipped_curator_count: int = 0
    skipped_dreaming_count: int = 0
    estimated_packet_tokens: int = 0
    repeated_error_count: int = 0
    tool_error_count: int = 0
    validation_complete: bool = False
    outcome: str = "unknown"
    memory_effect: str = "unknown"
    escalation_count: int = 0
    notes: List[str] = field(default_factory=list)
    created_at: float = field(default_factory=_now)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class LowEndEvalRun:
    id: str
    task_id: str
    mode: str
    worker_model: str
    worker_provider: str = ""
    status: str = "unknown"
    tool_error_count: int = 0
    repeated_error_count: int = 0
    validation_complete: bool = False
    estimated_tokens: int = 0
    wall_time_seconds: float = 0.0
    escalation_count: int = 0
    memory_hits: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class LowEndEvalComparison:
    task_id: str
    baseline: Dict[str, Any]
    assisted: Dict[str, Any]
    improved: bool
    deltas: Dict[str, Any]
    verdict: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def build_learning_value_report(
    event: GlobalPreCurationEvent | Dict[str, Any],
    *,
    hydration: Optional[Dict[str, Any]] = None,
    precuration: Optional[Dict[str, Any]] = None,
    worker_model: str = "",
    worker_provider: str = "",
    tool_events: Optional[Sequence[Dict[str, Any]]] = None,
    outcome: str = "unknown",
    validation_complete: bool = False,
    escalation_count: int = 0,
) -> LearningValueReport:
    evt = event if isinstance(event, GlobalPreCurationEvent) else GlobalPreCurationEvent(**{k: v for k, v in dict(event).items() if k in GlobalPreCurationEvent.__dataclass_fields__})
    hydration = dict(hydration or {})
    precuration = dict(precuration or {})
    decision = precuration.get("decision") if isinstance(precuration.get("decision"), dict) else {}
    retrieval = precuration.get("retrieval") if isinstance(precuration.get("retrieval"), dict) else {}
    audit = retrieval.get("audit") if isinstance(retrieval.get("audit"), dict) else {}
    metrics = precuration.get("metrics") if isinstance(precuration.get("metrics"), dict) else {}
    advisory_items = hydration.get("advisory_items") if isinstance(hydration.get("advisory_items"), list) else []
    hot_hits = hydration.get("hot_cache_hits") if isinstance(hydration.get("hot_cache_hits"), list) else []
    repeated_errors = count_repeated_error_signatures(tool_events or [])
    tool_errors = sum(1 for item in (tool_events or []) if _safe_status(item.get("status") or item.get("outcome")) != "success")

    global_hits = max(_as_int(metrics.get("global_lesson_hit")), _as_int(audit.get("exact_matches")))
    near_hits = max(_as_int(metrics.get("global_lesson_near_hit")), _as_int(audit.get("near_matches")))
    misses = _as_int(metrics.get("global_lesson_miss"))
    skipped_curator = 1 if decision.get("should_run_expensive_curator") is False else 0
    skipped_dreaming = skipped_curator

    memory_effect = "unknown"
    if outcome == "success" and (global_hits or near_hits or advisory_items):
        memory_effect = "helped"
    elif outcome in {"failed", "blocked", "timeout"} and (global_hits or near_hits or advisory_items):
        memory_effect = "ignored_or_hurt"
    elif not (global_hits or near_hits or advisory_items):
        memory_effect = "unused"

    notes: List[str] = []
    if skipped_curator:
        notes.append("programmatic memory hit skipped expensive curator path")
    if hydration.get("estimated_tokens", 0):
        notes.append("compact advisory packet stayed within configured token budget")

    return LearningValueReport(
        id=f"lval_{evt.event_id or int(_now())}",
        event_id=evt.event_id,
        tenant_id=evt.tenant_id,
        repo_id=evt.repo_id,
        worker_model=worker_model,
        worker_provider=worker_provider,
        memory_status=str(hydration.get("status") or "unknown"),
        memory_hits=len(advisory_items),
        global_lesson_hits=global_hits,
        global_lesson_near_hits=near_hits,
        global_lesson_misses=misses,
        hot_cache_hits=len(hot_hits),
        skipped_curator_count=skipped_curator,
        skipped_dreaming_count=skipped_dreaming,
        estimated_packet_tokens=_as_int(hydration.get("estimated_tokens")),
        repeated_error_count=repeated_errors,
        tool_error_count=tool_errors,
        validation_complete=bool(validation_complete),
        outcome=_safe_status(outcome),
        memory_effect=memory_effect,
        escalation_count=_as_int(escalation_count),
        notes=notes,
    )


def run_learning_value_probe(
    db: SessionDB,
    event: Dict[str, Any],
    *,
    config: Optional[Dict[str, Any]] = None,
    worker_model: str = "",
    worker_provider: str = "",
    tool_events: Optional[Sequence[Dict[str, Any]]] = None,
    outcome: str = "unknown",
    validation_complete: bool = False,
    escalation_count: int = 0,
    token_budget: int = 800,
) -> Dict[str, Any]:
    precuration = run_persisted_global_precuration(db, event, config=config, limit=3, record_feedback=False)
    hydration = hydrate_task_memory_from_global(db, event, config=config, token_budget=token_budget)
    report = build_learning_value_report(
        event,
        hydration=hydration.to_dict(),
        precuration=precuration.to_dict(),
        worker_model=worker_model,
        worker_provider=worker_provider,
        tool_events=tool_events,
        outcome=outcome,
        validation_complete=validation_complete,
        escalation_count=escalation_count,
    )
    return {
        "report": report.to_dict(),
        "precuration": precuration.to_dict(),
        "hydration": hydration.to_dict(),
    }


def compare_low_end_eval_runs(baseline: LowEndEvalRun | Dict[str, Any], assisted: LowEndEvalRun | Dict[str, Any]) -> LowEndEvalComparison:
    base = baseline if isinstance(baseline, LowEndEvalRun) else LowEndEvalRun(**dict(baseline))
    assist = assisted if isinstance(assisted, LowEndEvalRun) else LowEndEvalRun(**dict(assisted))
    success_gain = int(assist.status == "success") - int(base.status == "success")
    tool_error_delta = base.tool_error_count - assist.tool_error_count
    repeated_error_delta = base.repeated_error_count - assist.repeated_error_count
    validation_gain = int(assist.validation_complete) - int(base.validation_complete)
    wall_time_delta = base.wall_time_seconds - assist.wall_time_seconds
    escalation_delta = base.escalation_count - assist.escalation_count
    improved = (
        success_gain > 0
        or tool_error_delta > 0
        or repeated_error_delta > 0
        or validation_gain > 0
        or escalation_delta > 0
    )
    if improved and assist.memory_hits > 0:
        verdict = "memory_assisted_improved"
    elif improved:
        verdict = "improved_without_memory_evidence"
    elif assist.memory_hits > 0:
        verdict = "memory_present_no_measured_gain"
    else:
        verdict = "no_measured_gain"
    return LowEndEvalComparison(
        task_id=assist.task_id or base.task_id,
        baseline=base.to_dict(),
        assisted=assist.to_dict(),
        improved=improved,
        deltas={
            "success_gain": success_gain,
            "tool_error_reduction": tool_error_delta,
            "repeated_error_reduction": repeated_error_delta,
            "validation_gain": validation_gain,
            "wall_time_reduction_seconds": wall_time_delta,
            "escalation_reduction": escalation_delta,
            "token_delta": assist.estimated_tokens - base.estimated_tokens,
        },
        verdict=verdict,
    )
