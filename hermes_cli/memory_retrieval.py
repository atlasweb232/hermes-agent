"""Structured targeted memory retrieval for supervisor context injection."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
import re
import time
from typing import Any, Dict, Iterable, List, Optional

from hermes_state import SessionDB


def _now() -> float:
    return time.time()


def _tokens(text: str) -> List[str]:
    return [token.casefold() for token in re.findall(r"[A-Za-z0-9_./:@-]+", text or "") if len(token) >= 2]


@dataclass
class TaskRetrievalQuery:
    raw_query: str
    tenant_id: Optional[str] = None
    repo_id: Optional[str] = None
    tool: Optional[str] = None
    machine_id: Optional[str] = None
    task_type: str = "general"
    intent: str = "general"
    entities: List[str] = field(default_factory=list)
    error_signatures: List[str] = field(default_factory=list)
    success_signatures: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class RetrievalCandidate:
    id: str
    kind: str
    claim: str
    score: float
    status: str
    evidence: Dict[str, Any] = field(default_factory=dict)
    features: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class RetrievalRunAudit:
    run_id: str
    query: Dict[str, Any]
    filters: Dict[str, Any]
    candidates_considered: int
    candidates_returned: int
    features: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=_now)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def classify_task_query(
    query: str,
    *,
    tenant_id: Optional[str] = None,
    repo_id: Optional[str] = None,
    tool: Optional[str] = None,
    machine_id: Optional[str] = None,
) -> TaskRetrievalQuery:
    lowered = query.casefold()
    if any(word in lowered for word in ("worker-router", "claude", "codex", "deepseek", "cursor")):
        task_type = "tool_routing"
    elif any(word in lowered for word in ("test", "pytest", "validate", "smoke")):
        task_type = "validation"
    elif any(word in lowered for word in ("implement", "fix", "refactor", "build")):
        task_type = "implementation"
    else:
        task_type = "general"
    intent = "repair" if any(word in lowered for word in ("fail", "error", "broken", "fix")) else "retrieve"
    entities = []
    for token in _tokens(query):
        if "/" in token or "." in token or token in {"claude", "codex", "deepseek", "worker-router", "oauth"}:
            entities.append(token)
    errors = re.findall(r"(?:error|failed|exception|timeout|unknown option)[^.\n]{0,120}", query, flags=re.IGNORECASE)
    successes = re.findall(r"(?:succeeded|works|passed|completed)[^.\n]{0,120}", query, flags=re.IGNORECASE)
    return TaskRetrievalQuery(
        raw_query=query,
        tenant_id=tenant_id,
        repo_id=repo_id,
        tool=tool,
        machine_id=machine_id,
        task_type=task_type,
        intent=intent,
        entities=sorted(set(entities)),
        error_signatures=[item.strip() for item in errors],
        success_signatures=[item.strip() for item in successes],
    )


def normalize_candidate_metadata(candidate: Dict[str, Any]) -> Dict[str, Any]:
    evidence = candidate.get("evidence_json") if isinstance(candidate.get("evidence_json"), dict) else {}
    return {
        "tenant_id": candidate.get("tenant_id") or evidence.get("tenant_id"),
        "repo_id": candidate.get("repo_id") or evidence.get("repo_id"),
        "tool": evidence.get("tool") or evidence.get("failed_path") or evidence.get("working_path"),
        "machine_id": evidence.get("machine_id"),
        "task_type": evidence.get("task_type") or candidate.get("kind"),
        "scope": evidence.get("scope") or "global",
        "tier": evidence.get("tier") or "warm",
        "status": candidate.get("status"),
        "evidence": evidence,
    }


def score_retrieval_candidate(
    candidate: Dict[str, Any],
    query: TaskRetrievalQuery,
    *,
    lexical_score: float = 0.0,
    vector_score: float = 0.0,
    graph_score: float = 0.0,
    now: Optional[float] = None,
) -> RetrievalCandidate:
    metadata = normalize_candidate_metadata(candidate)
    evidence = metadata["evidence"]
    base = float(candidate.get("score") or 0.0)
    score = base * 0.7
    features: Dict[str, Any] = {
        "base_score": base,
        "lexical_score": lexical_score,
        "vector_score": vector_score,
        "graph_score": graph_score,
    }
    text = " ".join(
        str(part)
        for part in (
            candidate.get("kind"),
            candidate.get("claim"),
            evidence.get("match"),
            evidence.get("failed_path"),
            evidence.get("working_path"),
            evidence.get("error_signature"),
        )
        if part
    ).casefold()
    query_terms = set(_tokens(query.raw_query))
    candidate_terms = set(_tokens(text))
    exact_overlap = query_terms & candidate_terms
    exact_score = len(exact_overlap) / max(1, len(query_terms))
    score += exact_score * 0.25
    score += lexical_score * 0.15
    score += vector_score * 0.05
    score += graph_score * 0.05
    features["exact_score"] = exact_score
    features["matched_terms"] = sorted(exact_overlap)
    if query.tenant_id and metadata.get("tenant_id") not in {None, query.tenant_id}:
        score -= 0.5
        features["tenant_penalty"] = True
    if query.repo_id and metadata.get("repo_id") not in {None, query.repo_id}:
        score -= 0.35
        features["repo_penalty"] = True
    if query.tool and metadata.get("tool") and query.tool not in str(metadata.get("tool")):
        score -= 0.15
        features["tool_penalty"] = True
    updated_at = float(candidate.get("updated_at") or candidate.get("created_at") or 0.0)
    if updated_at and now:
        age_days = max(0.0, (now - updated_at) / 86400)
        recency = max(0.0, 1.0 - min(age_days, 90.0) / 90.0)
        score += recency * 0.05
        features["recency"] = recency
    return RetrievalCandidate(
        id=str(candidate.get("id")),
        kind=str(candidate.get("kind") or ""),
        claim=str(candidate.get("claim") or ""),
        score=max(0.0, min(1.0, score)),
        status=str(candidate.get("status") or ""),
        evidence=evidence,
        features=features,
    )


def retrieve_memory_candidates(
    db: SessionDB,
    *,
    query: TaskRetrievalQuery,
    statuses: Iterable[str],
    limit: int = 5,
    min_score: float = 0.6,
) -> Dict[str, Any]:
    selected: List[RetrievalCandidate] = []
    considered = 0
    scan_limit = max(20, int(limit) * 6)
    for status in statuses:
        rows = db.list_meta_candidates(tenant_id=query.tenant_id, repo_id=query.repo_id, status=status, limit=scan_limit)
        if query.tenant_id is not None or query.repo_id is not None:
            rows.extend(db.list_meta_candidates(tenant_id=None, repo_id=None, status=status, limit=scan_limit))
        for row in rows:
            considered += 1
            metadata = normalize_candidate_metadata(row)
            if query.tenant_id and metadata.get("tenant_id") not in {None, query.tenant_id}:
                continue
            if query.repo_id and metadata.get("repo_id") not in {None, query.repo_id}:
                continue
            scored = score_retrieval_candidate(row, query, now=_now())
            if not scored.features.get("matched_terms"):
                continue
            if scored.score < min_score:
                continue
            if any(existing.id == scored.id for existing in selected):
                continue
            selected.append(scored)
    selected.sort(key=lambda item: item.score, reverse=True)
    selected = selected[: max(1, int(limit))]
    run_id = f"retr_{hashlib.sha256((query.raw_query + str(_now())).encode()).hexdigest()[:16]}"
    audit = RetrievalRunAudit(
        run_id=run_id,
        query=query.to_dict(),
        filters={"statuses": list(statuses), "min_score": min_score, "limit": limit},
        candidates_considered=considered,
        candidates_returned=len(selected),
        features={"strategy": "metadata_exact_lexical"},
    )
    return {"candidates": [item.to_dict() for item in selected], "audit": audit.to_dict()}


def build_memory_packet(
    *,
    query: TaskRetrievalQuery,
    candidates: List[Dict[str, Any]],
    max_chars: int = 2500,
) -> Dict[str, Any]:
    header = (
        "ADVISORY MEMORY ONLY: explicit task instructions, git, tests, logs, "
        "and current operator commands are more authoritative."
    )
    compact: List[Dict[str, Any]] = []
    used = len(header)
    for candidate in candidates:
        evidence = candidate.get("evidence") if isinstance(candidate.get("evidence"), dict) else {}
        item = {
            "id": candidate.get("id"),
            "kind": candidate.get("kind"),
            "claim": candidate.get("claim"),
            "score": candidate.get("score"),
            "status": candidate.get("status"),
            "evidence_label": evidence.get("evidence_uri") or evidence.get("source_record_id") or evidence.get("record_id"),
            "scope_labels": [label for label in (query.tenant_id, query.repo_id, query.tool, query.task_type) if label],
            "features": candidate.get("features") or {},
        }
        rendered = json.dumps(item, ensure_ascii=False, sort_keys=True)
        if used + len(rendered) + 2 > max_chars:
            break
        compact.append(item)
        used += len(rendered) + 2
    return {
        "header": header,
        "query": query.to_dict(),
        "candidates": compact,
        "truncated": len(compact) < len(candidates),
    }


def record_memory_feedback(
    db: SessionDB,
    *,
    candidate_id: str,
    outcome: str,
    reason: str = "",
) -> Dict[str, Any]:
    candidate = db.get_meta_candidate(candidate_id)
    if candidate is None:
        raise ValueError(f"unknown meta candidate: {candidate_id}")
    score = float(candidate.get("score") or 0.0)
    if outcome == "helpful":
        score = min(1.0, score + 0.05)
    elif outcome == "irrelevant":
        score = max(0.0, score - 0.1)
    elif outcome == "harmful":
        score = max(0.0, score - 0.25)
    evidence = candidate.get("evidence_json") if isinstance(candidate.get("evidence_json"), dict) else {}
    feedback = evidence.get("feedback")
    if not isinstance(feedback, list):
        feedback = []
    feedback.append({"outcome": outcome, "reason": reason, "at": _now()})
    evidence["feedback"] = feedback
    db.update_meta_candidate_status(candidate_id, status=str(candidate.get("status") or "proposed"), evidence_json=evidence, score=score)
    return {"candidate_id": candidate_id, "outcome": outcome, "score": score}
