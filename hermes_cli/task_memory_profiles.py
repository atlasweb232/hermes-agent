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
    retrieve_global_hot_cache_for_event,
    stable_hash,
)
from hermes_cli.memory_wiki_backends import build_memory_wiki_backends
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
    signature_hit: bool
    semantic_fallback_used: bool
    vector_fallback_used: bool
    graph_fallback_used: bool
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
    metrics: Dict[str, int] = field(default_factory=dict)

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


def _load_profile_lessons(db: SessionDB) -> List[Dict[str, Any]]:
    lessons: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for state in ("approved", "canonical", "applied"):
        for lesson in list_global_lessons(db, approval_state=state, limit=500):
            lesson_id = str(lesson.get("id") or "")
            if lesson_id in seen:
                continue
            seen.add(lesson_id)
            lessons.append(lesson)
    lessons.sort(key=lambda item: (-float(item.get("updated_at") or 0.0), str(item.get("id") or "")))
    return lessons[:500]


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


def _hot_cache_match_kind(event: GlobalPreCurationEvent, entry: Dict[str, Any]) -> Optional[str]:
    lesson_like = {
        "failure_signature": entry.get("failure_signature") or "",
        "success_signature": entry.get("success_signature") or "",
    }
    if _signature_match_kind(event, lesson_like):
        return "hot_cache_signature_exact"
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


def _bounded_hot_cache_match(entry: Dict[str, Any], *, match_kind: str) -> Dict[str, Any]:
    lesson_like = {
        "id": entry.get("global_lesson_id") or entry.get("id") or "",
        "confidence": entry.get("confidence") or 0.0,
        "evidence_refs": entry.get("evidence_refs") or [],
        "compact_text": entry.get("compact_text") or "",
        "normalized_text": entry.get("compact_text") or "",
    }
    return _bounded_match(
        lesson_like,
        source="global_hot_cache",
        match_kind=match_kind,
        score=float(entry.get("confidence") or 0.0),
    )


def _fallback_config(config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    wiki = ((config or {}).get("supervisor") or {}).get("global_memory_wiki") or {}
    profile_cfg = wiki.get("task_memory_profile") if isinstance(wiki.get("task_memory_profile"), dict) else {}
    fallback = profile_cfg.get("vector_graph_fallback") if isinstance(profile_cfg.get("vector_graph_fallback"), dict) else {}
    return fallback or {}


def _vector_graph_fallback_enabled(config: Optional[Dict[str, Any]]) -> bool:
    fallback = _fallback_config(config)
    wiki = ((config or {}).get("supervisor") or {}).get("global_memory_wiki") or {}
    vector_cfg = wiki.get("vector_index") if isinstance(wiki.get("vector_index"), dict) else {}
    graph_cfg = wiki.get("graph_index") if isinstance(wiki.get("graph_index"), dict) else {}
    return (
        bool(fallback.get("enabled", False))
        and str(vector_cfg.get("backend") or "disabled").lower() == "local_fake"
        and str(graph_cfg.get("backend") or "disabled").lower() in {"sqlite", "memory"}
    )


def _fallback_threshold(config: Optional[Dict[str, Any]]) -> float:
    fallback = _fallback_config(config)
    try:
        return max(0.0, min(1.0, float(fallback.get("min_exact_score", 1.0))))
    except (TypeError, ValueError):
        return 1.0


def _fallback_limit(config: Optional[Dict[str, Any]], top_k_cap: int) -> int:
    fallback = _fallback_config(config)
    try:
        configured = int(fallback.get("max_candidates", top_k_cap or _LOW_COST_TOP_K_CAP))
    except (TypeError, ValueError):
        configured = top_k_cap or _LOW_COST_TOP_K_CAP
    return max(1, min(_LOW_COST_TOP_K_CAP, configured, top_k_cap or _LOW_COST_TOP_K_CAP))


def _fallback_terms(text: str) -> List[str]:
    terms: List[str] = []
    seen = set()
    for token in re.findall(r"[a-z0-9][a-z0-9_.:/-]{2,}", str(text or "").lower()):
        if any(pattern.search(token) for pattern in _SECRET_PATTERNS):
            continue
        if token not in seen:
            seen.add(token)
            terms.append(token)
        if len(terms) >= 16:
            break
    return terms


def _fallback_graph_keys(data: Dict[str, Any], terms: Sequence[str]) -> List[str]:
    keys: List[str] = []
    for key in ("tool", "task_type", "worker_kind", "failure_signature", "success_signature", "scope"):
        value = str(data.get(key) or "").strip()
        if value and not any(pattern.search(value) for pattern in _SECRET_PATTERNS):
            keys.append(f"{key}:{stable_hash(value)[:16]}")
    keys.extend(f"term:{stable_hash(term)[:12]}" for term in list(terms)[:8])
    return keys


def _fallback_skip_reason(lesson: Dict[str, Any]) -> Optional[str]:
    if str(lesson.get("approval_state") or "") not in {"approved", "canonical", "applied"}:
        return "not_approved_canonical"
    if str(lesson.get("scope") or "") != "global":
        return "private"
    if not bool(lesson.get("cross_tenant_shareable")):
        return "private"
    sensitivity = str(lesson.get("sensitivity") or "").lower()
    if sensitivity == "secret":
        return "secret"
    text = str(lesson.get("normalized_text") or "")
    if any(pattern.search(text) for pattern in _SECRET_PATTERNS):
        return "secret"
    return None


def _indexable_fallback_payload(lesson: Dict[str, Any]) -> Dict[str, Any]:
    text = _sanitize_compact_text(_compact_lesson_text(lesson), max_chars=480)
    terms = _fallback_terms(text)
    graph_keys = _fallback_graph_keys(lesson, terms)
    return {
        "id": str(lesson.get("id") or ""),
        "approval_state": lesson.get("approval_state") or "approved",
        "scope": "global",
        "visibility": lesson.get("visibility") or "global_candidate",
        "sensitivity": lesson.get("sensitivity") or "internal",
        "shareable": True,
        "global_safe": True,
        "text": text,
        "evidence_refs": [str(item) for item in (lesson.get("evidence_refs") or [])][:5],
        "graph_keys": graph_keys,
        "metadata": {
            "tool": lesson.get("tool") or "",
            "task_type": lesson.get("task_type") or "",
            "worker_kind": lesson.get("worker_kind") or "",
            "confidence": float(lesson.get("confidence") or 0.0),
        },
    }


def _vector_graph_fallback_matches(
    lessons: Sequence[Dict[str, Any]],
    event: GlobalPreCurationEvent,
    *,
    config: Optional[Dict[str, Any]],
    top_k_cap: int,
    metrics: Dict[str, int],
    audit: Dict[str, Any],
) -> tuple[List[Dict[str, Any]], bool, bool]:
    if not _vector_graph_fallback_enabled(config):
        audit["vector_graph_fallback"] = {"enabled": False, "reason": "disabled"}
        return [], False, False

    bundle = build_memory_wiki_backends(config or {})
    fallback_limit = _fallback_limit(config, top_k_cap)
    indexed_ids: set[str] = set()
    eligible: Dict[str, Dict[str, Any]] = {}
    for lesson in lessons:
        lesson_id = str(lesson.get("id") or "")
        reason = _fallback_skip_reason(lesson)
        if reason == "private":
            metrics["skipped_private"] += 1
            audit["rejected"].append({"id": "[redacted]", "reason": "fallback_private"})
            continue
        if reason == "secret":
            metrics["skipped_secret"] += 1
            audit["rejected"].append({"id": "[redacted]", "reason": "fallback_secret"})
            continue
        if reason:
            audit["rejected"].append({"id": lesson_id, "reason": f"fallback_{reason}"})
            continue
        payload = _indexable_fallback_payload(lesson)
        try:
            bundle.vector_index.upsert(lesson_id, payload)
            bundle.graph_index.upsert(lesson_id, payload)
        except Exception as exc:
            audit.setdefault("fallback_errors", []).append({"id": lesson_id, "reason": str(exc)[:120]})
            continue
        indexed_ids.add(lesson_id)
        eligible[lesson_id] = lesson

    query_text = " ".join(
        part
        for part in [
            event.normalized_text,
            event.failure_signature,
            event.success_signature,
            event.tool,
            event.task_type,
            event.worker_kind,
        ]
        if part
    )
    scored: Dict[str, tuple[float, set[str]]] = {}
    vector_used = False
    graph_used = False
    for row in bundle.vector_index.search(query_text, limit=fallback_limit):
        lesson_id = str(row.get("id") or "")
        if lesson_id not in indexed_ids:
            continue
        vector_used = True
        score = max(0.0, min(1.0, float(row.get("score") or 0.0)))
        current_score, sources = scored.get(lesson_id, (0.0, set()))
        sources.add("vector")
        scored[lesson_id] = (max(current_score, score), sources)

    event_terms = _fallback_terms(query_text)
    event_keys = _fallback_graph_keys(event.to_dict(), event_terms)
    for key in event_keys:
        for edge in bundle.graph_index.neighbors(key, limit=fallback_limit):
            lesson_id = str(edge.get("target_id") or "")
            if lesson_id not in indexed_ids:
                continue
            graph_used = True
            current_score, sources = scored.get(lesson_id, (0.0, set()))
            sources.add("graph")
            scored[lesson_id] = (max(current_score, 0.5), sources)

    ranked: List[tuple[float, str, Dict[str, Any]]] = []
    for lesson_id, (score, sources) in scored.items():
        lesson = eligible[lesson_id]
        match_kind = "vector_graph_fallback" if sources == {"vector", "graph"} else f"{next(iter(sorted(sources)))}_fallback"
        ranked.append(
            (
                score,
                lesson_id,
                _bounded_match(
                    lesson,
                    source="global_lesson",
                    match_kind=match_kind,
                    score=score,
                ),
            )
        )
    ranked.sort(key=lambda item: (-item[0], item[1]))
    matches = [item[2] for item in ranked[:fallback_limit]]
    if matches:
        metrics["vector_fallback_used"] = 1 if vector_used else 0
        metrics["graph_fallback_used"] = 1 if graph_used else 0
        audit["matched"].extend(
            {"id": item["id"], "reason": item["match_kind"], "score": item["score"]} for item in matches
        )
    audit["vector_graph_fallback"] = {
        "enabled": True,
        "indexed": len(indexed_ids),
        "returned": len(matches),
        "vector_used": vector_used,
        "graph_used": graph_used,
    }
    return matches, vector_used and bool(matches), graph_used and bool(matches)


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
    signature matching over approved SQLite lessons first, never calls curator,
    judge, or dreaming sidecars, and never mutates reuse stats. Optional
    vector/graph fallback is disabled by default and only uses local fake
    adapters when explicitly configured.
    """
    evt = _event_with_signature_aliases(event)
    requested_top_k = max(0, int(top_k))
    top_k_cap = min(requested_top_k, _LOW_COST_TOP_K_CAP)
    budget = max(0, int(token_budget))
    filters = _profile_filters(evt)
    hot_cache_hits = retrieve_global_hot_cache_for_event(db, evt, limit=top_k_cap)
    lessons = _load_profile_lessons(db)
    audit: Dict[str, Any] = {
        "event_id": evt.event_id,
        "considered": len(lessons),
        "returned": 0,
        "exact_matches": 0,
        "hot_cache_matches": 0,
        "rejected": [],
        "matched": [],
    }
    metrics: Dict[str, int] = {
        "exact_hit": 0,
        "signature_hit": 0,
        "vector_fallback_used": 0,
        "graph_fallback_used": 0,
        "skipped_private": 0,
        "skipped_secret": 0,
    }
    ranked: List[tuple[int, int, float, str, Dict[str, Any]]] = []
    demoted: List[Dict[str, str]] = []

    for entry in hot_cache_hits:
        cache_id = str(entry.get("id") or "")
        lesson_id = str(entry.get("global_lesson_id") or cache_id)
        match_kind = _hot_cache_match_kind(evt, entry)
        if not match_kind:
            continue
        audit["exact_matches"] += 1
        audit["hot_cache_matches"] += 1
        score = max(0.0, min(1.0, float(entry.get("confidence") or 0.0)))
        match = _bounded_hot_cache_match(entry, match_kind=match_kind)
        ranked.append((-1, 0, score, lesson_id, match))
        audit["matched"].append({"id": lesson_id, "reason": match_kind, "score": round(score, 4)})

    for lesson in lessons:
        lesson_id = str(lesson.get("id") or "")
        if str(lesson.get("sensitivity") or "").lower() == "secret":
            audit["rejected"].append({"id": "[redacted]", "reason": "secret"})
            continue
        rejection = _metadata_rejection(filters, lesson)
        if rejection:
            audit["rejected"].append({"id": lesson_id, "reason": rejection})
            continue
        match_kind = _signature_match_kind(evt, lesson)
        if not match_kind:
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
    signature_hit = bool(audit["exact_matches"])
    metrics["exact_hit"] = 1 if exact_hit else 0
    metrics["signature_hit"] = 1 if signature_hit else 0
    fallback_backend = "disabled"
    semantic_fallback_used = False
    vector_fallback_used = False
    graph_fallback_used = False
    best_exact_score = max((float(item[4].get("score") or 0.0) for item in ranked), default=0.0)
    threshold = _fallback_threshold(config)
    hot_cache_exact_hit = bool(audit["hot_cache_matches"])
    should_try_vector_graph = (not hot_cache_exact_hit) and (not exact_hit or best_exact_score < threshold)
    if should_try_vector_graph:
        fallback_matches, vector_fallback_used, graph_fallback_used = _vector_graph_fallback_matches(
            lessons,
            evt,
            config=config,
            top_k_cap=top_k_cap,
            metrics=metrics,
            audit=audit,
        )
        if fallback_matches:
            fallback_backend = "local_fake_vector+sqlite_graph"
            matches = fallback_matches[:top_k_cap]
    else:
        audit["fallback_reason"] = (
            "local_hot_cache_exact_signature_hit" if hot_cache_exact_hit else "local_exact_signature_hit"
        )

    if not matches and semantic_fallback:
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
        signature_hit=signature_hit,
        semantic_fallback_used=semantic_fallback_used,
        vector_fallback_used=vector_fallback_used,
        graph_fallback_used=graph_fallback_used,
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
        metrics=metrics,
    )
