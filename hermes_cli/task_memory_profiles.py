"""Compact, deterministic task-memory retrieval profiles."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from hermes_cli.global_memory import (
    GlobalPreCurationEvent,
    _as_precuration_event,
    _compact_lesson_text,
    estimate_tokens,
    list_global_lessons,
    stable_hash,
)
from hermes_state import SessionDB


_LOW_COST_TOP_K_CAP = 3
_SECRET_PATTERNS = (
    re.compile(r"\b(?:sk|ghp|gho|xox[baprs])-[A-Za-z0-9._-]+\b"),
    re.compile(r"\b[A-Z0-9_]*(?:SECRET|TOKEN|KEY|PASSWORD)[A-Z0-9_]*\s*=\s*\S+", re.IGNORECASE),
    re.compile(r"\b[a-z0-9_]*(?:secret|token|key|password)[a-z0-9_]*\S*", re.IGNORECASE),
)


@dataclass
class TaskMemoryRetrievalProfile:
    profile: str
    mode: str
    llm_calls: List[str]
    exact_hit: bool
    semantic_fallback_used: bool
    fallback_backend: str
    top_k_cap: int
    token_budget: int
    estimated_tokens: int
    budget_exhausted: bool
    filters: Dict[str, str]
    matches: List[Dict[str, Any]] = field(default_factory=list)
    demoted: List[Dict[str, str]] = field(default_factory=list)
    retrieval_audit: Dict[str, Any] = field(default_factory=dict)
    injection_items: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _event_with_signature_aliases(event: GlobalPreCurationEvent | Dict[str, Any]) -> GlobalPreCurationEvent:
    if isinstance(event, GlobalPreCurationEvent):
        return event
    data = dict(event or {})
    if not data.get("failure_signature"):
        data["failure_signature"] = data.get("error_signature") or data.get("command_error_signature") or ""
    if not data.get("success_signature"):
        data["success_signature"] = data.get("command_signature") or data.get("success_command_signature") or ""
    return _as_precuration_event(data)


def _profile_filters(event: GlobalPreCurationEvent) -> Dict[str, str]:
    filters: Dict[str, str] = {}
    for key in ("tenant_id", "repo_id", "tool", "task_type", "worker_kind"):
        value = str(getattr(event, key) or "")
        if value:
            filters[key] = value
    return filters


def _metadata_rejection(filters: Dict[str, str], lesson: Dict[str, Any]) -> Optional[str]:
    for key, value in filters.items():
        if str(lesson.get(key) or "") != value:
            if key == "tenant_id":
                return "tenant_mismatch"
            if key == "repo_id":
                return "repo_mismatch"
            return f"{key}_mismatch"
    return None


def _signature_values(event: GlobalPreCurationEvent, lesson: Dict[str, Any]) -> tuple[set[str], set[str]]:
    event_values = {
        str(event.failure_signature or ""),
        str(event.success_signature or ""),
        str(event.scope_signature or ""),
        str(event.evidence_signature or ""),
    }
    lesson_values = {
        str(lesson.get("failure_signature") or ""),
        str(lesson.get("success_signature") or ""),
        str(lesson.get("scope_signature") or ""),
        str(lesson.get("evidence_signature") or ""),
    }
    return {value for value in event_values if value}, {value for value in lesson_values if value}


def _signature_match_kind(event: GlobalPreCurationEvent, lesson: Dict[str, Any]) -> Optional[str]:
    event_values, lesson_values = _signature_values(event, lesson)
    if event_values & lesson_values:
        return "signature_exact"
    return None


def _negative_feedback_reason(stats: Dict[str, Any]) -> Optional[str]:
    positive_keys = ("helped", "positive", "accepted", "applied", "success")
    negative_keys = ("hurt", "ignored", "failure", "negative", "rejected")
    positive = 0
    negative = 0
    for key, raw_value in (stats or {}).items():
        try:
            value = int(raw_value)
        except (TypeError, ValueError):
            continue
        lowered = str(key).lower()
        if any(token in lowered for token in positive_keys):
            positive += value
        if any(token in lowered for token in negative_keys):
            negative += value
    if negative > positive:
        return "negative_feedback_exceeds_positive"
    return None


def _sanitize_compact_text(text: str, *, max_chars: int = 320) -> str:
    compact = re.sub(r"\s+", " ", str(text or "")).strip()
    for pattern in _SECRET_PATTERNS:
        compact = pattern.sub("[REDACTED]", compact)
    compact = re.sub(r"\braw transcript\b", "redacted context", compact, flags=re.IGNORECASE)
    compact = re.sub(r"\braw logs?\b", "redacted logs", compact, flags=re.IGNORECASE)
    return compact[:max_chars]


def _bounded_match(
    lesson: Dict[str, Any],
    *,
    source: str,
    match_kind: str,
    score: float,
    demotion_reason: Optional[str] = None,
) -> Dict[str, Any]:
    compact_text = _sanitize_compact_text(_compact_lesson_text(lesson))
    estimated = estimate_tokens(compact_text)
    return {
        "id": str(lesson.get("id") or lesson.get("global_lesson_id") or ""),
        "source": source,
        "match_kind": match_kind,
        "score": round(float(score), 4),
        "confidence": round(float(lesson.get("confidence") or score or 0.0), 4),
        "evidence_refs": [str(item) for item in (lesson.get("evidence_refs") or [])][:5],
        "compact_text": compact_text,
        "advisory": True,
        "estimated_tokens": estimated,
        "demotion_applied": bool(demotion_reason),
        **({"demotion_reason": demotion_reason} if demotion_reason else {}),
    }


def _fallback_match(event: GlobalPreCurationEvent) -> Dict[str, Any]:
    text = "No exact approved task memory matched this scoped event; proceed with local task context only."
    fallback_id = f"local_fake_{stable_hash([event.to_dict(), text])[:12]}"
    return {
        "id": fallback_id,
        "source": "semantic_fallback",
        "match_kind": "semantic_fallback",
        "score": 0.0,
        "confidence": 0.0,
        "evidence_refs": [],
        "compact_text": text,
        "advisory": True,
        "estimated_tokens": estimate_tokens(text),
        "demotion_applied": False,
    }


def _select_injection_items(matches: Sequence[Dict[str, Any]], token_budget: int) -> tuple[List[Dict[str, Any]], int, bool]:
    selected: List[Dict[str, Any]] = []
    used_tokens = 0
    budget_exhausted = False
    for item in matches:
        cost = int(item.get("estimated_tokens") or estimate_tokens(item.get("compact_text", "")))
        if used_tokens + cost > int(token_budget):
            budget_exhausted = True
            continue
        used_tokens += cost
        selected.append(
            {
                "id": item["id"],
                "source": item["source"],
                "match_kind": item["match_kind"],
                "score": item["score"],
                "confidence": item["confidence"],
                "evidence_refs": list(item.get("evidence_refs") or []),
                "advisory_text": item["compact_text"],
                "estimated_tokens": cost,
                "demotion_applied": bool(item.get("demotion_applied")),
            }
        )
    return selected, used_tokens, budget_exhausted


def build_task_memory_retrieval_profile(
    db: SessionDB,
    event: GlobalPreCurationEvent | Dict[str, Any],
    *,
    profile: str = "low_cost_worker",
    top_k: int = 3,
    token_budget: int = 240,
    semantic_fallback: bool = True,
    config: Optional[Dict[str, Any]] = None,
) -> TaskMemoryRetrievalProfile:
    """Build a compact, JSON-safe memory packet preview for low-cost workers.

    The profile is programmatic by design: it performs exact metadata and
    signature matching over approved SQLite lessons only, never calls curator,
    judge, dreaming, vector, or graph sidecars, and never mutates reuse stats.
    """
    del config
    evt = _event_with_signature_aliases(event)
    requested_top_k = max(0, int(top_k))
    top_k_cap = min(requested_top_k, _LOW_COST_TOP_K_CAP)
    budget = max(0, int(token_budget))
    filters = _profile_filters(evt)
    lessons = list_global_lessons(db, approval_state="approved", limit=500)
    audit: Dict[str, Any] = {
        "event_id": evt.event_id,
        "considered": len(lessons),
        "returned": 0,
        "exact_matches": 0,
        "rejected": [],
        "matched": [],
    }
    ranked: List[tuple[int, int, float, str, Dict[str, Any]]] = []
    demoted: List[Dict[str, str]] = []

    for lesson in lessons:
        lesson_id = str(lesson.get("id") or "")
        if str(lesson.get("sensitivity") or "").lower() == "secret":
            audit["rejected"].append({"id": lesson_id, "reason": "secret"})
            continue
        rejection = _metadata_rejection(filters, lesson)
        if rejection:
            audit["rejected"].append({"id": lesson_id, "reason": rejection})
            continue
        match_kind = _signature_match_kind(evt, lesson)
        if not match_kind:
            audit["rejected"].append({"id": lesson_id, "reason": "no_signature_match"})
            continue
        audit["exact_matches"] += 1
        base_score = max(0.0, min(1.0, float(lesson.get("confidence") or 0.0)))
        demotion_reason = _negative_feedback_reason(lesson.get("reuse_stats") or {})
        score = max(0.0, base_score - 0.25) if demotion_reason else base_score
        match = _bounded_match(
            lesson,
            source="global_lesson",
            match_kind=match_kind,
            score=score,
            demotion_reason=demotion_reason,
        )
        demotion_rank = 1 if demotion_reason else 0
        if demotion_reason:
            demoted.append({"id": lesson_id, "reason": demotion_reason})
        ranked.append((0, demotion_rank, score, lesson_id, match))
        audit["matched"].append({"id": lesson_id, "reason": match_kind, "score": round(score, 4)})

    ranked.sort(key=lambda item: (item[0], item[1], -item[2], item[3]))
    matches = [item[4] for item in ranked[:top_k_cap]]
    exact_hit = bool(matches)
    fallback_backend = "disabled"
    semantic_fallback_used = False
    if not exact_hit and semantic_fallback:
        fallback_backend = "local_fake"
        semantic_fallback_used = True
        matches = [_fallback_match(evt)][:top_k_cap]

    injection_items, estimated_tokens, budget_exhausted = _select_injection_items(matches, budget)
    audit["returned"] = len(matches)
    return TaskMemoryRetrievalProfile(
        profile=str(profile or "low_cost_worker"),
        mode="programmatic",
        llm_calls=[],
        exact_hit=exact_hit,
        semantic_fallback_used=semantic_fallback_used,
        fallback_backend=fallback_backend,
        top_k_cap=top_k_cap,
        token_budget=budget,
        estimated_tokens=estimated_tokens,
        budget_exhausted=budget_exhausted,
        filters=filters,
        matches=matches,
        demoted=demoted,
        retrieval_audit=audit,
        injection_items=injection_items,
    )
