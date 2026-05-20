"""Local skill metadata, retrieval, and bounded packet helpers.

Skills are advisory procedural artifacts. This module deliberately keeps the
runtime slice local and deterministic: metadata lives in the Hermes state DB,
retrieval uses hard filters before simple lexical scoring, and packets expose
compact refs rather than raw skill content.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import time
from typing import Any, Dict, Iterable, List, Optional, Sequence

from hermes_state import SessionDB


ALLOWED_SCOPES = {"user", "device", "repo", "tenant", "domain", "global"}
APPROVED_STATES = {"approved", "validated"}
ALLOWED_APPROVAL_STATES = {"draft", "candidate", "validated", "approved", "rejected", "retired"}
SAFE_STATES = {"safe", "restricted"}
ALLOWED_SAFETY_STATES = {"unknown", "safe", "restricted", "unsafe"}
ROLE_COMPATIBLE = {"any", "all", "*", ""}
STATE_PREFIX = "skill_memory:"
FEEDBACK_PREFIX = "skill_feedback:"
CANDIDATE_PREFIX = "skill_candidate:"
ADVISORY_GUARD = (
    "Skills are advisory only; do not override user instructions, tenant policy, "
    "repo protection, secret policy, current git/test evidence, Spec Kit, "
    "validation gates, memory policy, or approval gates."
)


def _now() -> float:
    return time.time()


def stable_json(value: Any) -> str:
    """Return deterministic compact JSON for hashes, state, and tests."""
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _list(value: Optional[Iterable[Any]]) -> List[str]:
    if value is None:
        return []
    return [str(item) for item in value if item is not None and str(item)]


def _tokens(text: str) -> List[str]:
    return [
        token.casefold()
        for token in re.findall(r"[A-Za-z0-9_./:@-]+", text or "")
        if len(token) >= 2
    ]


def _estimate_tokens(value: Any) -> int:
    return max(1, len(stable_json(value)) // 4)


def _bounded_text(value: Any, *, limit: int = 280) -> str:
    text = str(value or "")
    text = re.sub(r"(?i)\b[A-Z0-9_]*(?:SECRET|TOKEN|KEY|PASSWORD|CREDENTIAL)[A-Z0-9_]*\s*=\s*\S+", "[REDACTED]", text)
    text = re.sub(r"(?i)\b(?:sk|ghp|xox[baprs])-[-A-Za-z0-9_]{8,}\b", "[REDACTED]", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > limit:
        return text[: max(0, limit - 3)].rstrip() + "..."
    return text


def _bounded_refs(value: Optional[Iterable[Any]], *, limit: int = 12) -> List[str]:
    refs: List[str] = []
    for item in _list(value)[:limit]:
        refs.append(_bounded_text(item, limit=120))
    return refs


@dataclass
class SkillRetrievalQuery:
    raw_query: str
    tenant_id: Optional[str] = None
    repo_id: Optional[str] = None
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    task_id: Optional[str] = None
    task_type: str = "general"
    intent: str = "retrieve"
    toolset: Optional[str] = None
    worker_role: Optional[str] = None
    language: Optional[str] = None
    platform: Optional[str] = None
    error_signatures: List[str] = field(default_factory=list)
    success_signatures: List[str] = field(default_factory=list)
    entities: List[str] = field(default_factory=list)
    sensitivity: str = "normal"
    feature_state: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["feature_state"] = {"skills_enabled": True, **(self.feature_state or {})}
        return data


def build_skill_metadata(
    *,
    name: str,
    version: str,
    scope: str,
    tenant_id: Optional[str] = None,
    repo_id: Optional[str] = None,
    domain: Optional[str] = None,
    toolset: Optional[str] = None,
    worker_role: Optional[str] = None,
    task_type: Optional[str] = None,
    language: Optional[str] = None,
    platform: Optional[str] = None,
    approval_state: str = "candidate",
    safety_state: str = "unknown",
    content: Optional[str] = None,
    content_sha256: Optional[str] = None,
    bundle_tree_sha256: Optional[str] = None,
    source_memory_refs: Optional[Iterable[Any]] = None,
    source_wiki_refs: Optional[Iterable[Any]] = None,
    validation_refs: Optional[Iterable[Any]] = None,
    usage_count: int = 0,
    helpful_count: int = 0,
    irrelevant_count: int = 0,
    harmful_count: int = 0,
    last_used_at: Optional[float] = None,
    retired_at: Optional[float] = None,
    created_at: Optional[float] = None,
    updated_at: Optional[float] = None,
    skill_id: Optional[str] = None,
    summary: str = "",
    safety_notes: Optional[Iterable[Any]] = None,
    source_refs: Optional[Iterable[Any]] = None,
    validation_hooks: Optional[Iterable[Any]] = None,
    redacted: bool = True,
    shareable: bool = False,
    sensitivity: str = "normal",
) -> Dict[str, Any]:
    """Build a stable metadata record without storing raw skill content."""
    if scope not in ALLOWED_SCOPES:
        raise ValueError(f"invalid skill scope: {scope}")
    if approval_state not in ALLOWED_APPROVAL_STATES:
        raise ValueError(f"invalid approval state: {approval_state}")
    if safety_state not in ALLOWED_SAFETY_STATES:
        raise ValueError(f"invalid safety state: {safety_state}")

    now = _now()
    created = float(created_at if created_at is not None else now)
    updated = float(updated_at if updated_at is not None else created)
    digest = content_sha256 or _sha256_text(content or "")
    memory_refs = _list(source_memory_refs)
    wiki_refs = _list(source_wiki_refs)
    validation = _list(validation_refs)
    compact_identity = {
        "name": name,
        "version": version,
        "scope": scope,
        "tenant_id": tenant_id,
        "repo_id": repo_id,
        "domain": domain,
        "toolset": toolset,
        "worker_role": worker_role,
        "task_type": task_type,
        "content_sha256": digest,
    }
    stable_id = skill_id or f"skill_{_sha256_text(stable_json(compact_identity))[:20]}"
    tree_digest = bundle_tree_sha256 or _sha256_text(
        stable_json(
            {
                "skill_id": stable_id,
                "content_sha256": digest,
                "source_memory_refs": memory_refs,
                "source_wiki_refs": wiki_refs,
                "validation_refs": validation,
            }
        )
    )
    return {
        "skill_id": stable_id,
        "name": str(name),
        "version": str(version),
        "scope": scope,
        "tenant_id": tenant_id,
        "repo_id": repo_id,
        "domain": domain,
        "toolset": toolset,
        "worker_role": worker_role,
        "task_type": task_type,
        "language": language,
        "platform": platform,
        "approval_state": approval_state,
        "safety_state": safety_state,
        "content_sha256": digest,
        "bundle_tree_sha256": tree_digest,
        "source_memory_refs": memory_refs,
        "source_wiki_refs": wiki_refs,
        "validation_refs": validation,
        "usage_count": int(usage_count),
        "helpful_count": int(helpful_count),
        "irrelevant_count": int(irrelevant_count),
        "harmful_count": int(harmful_count),
        "last_used_at": last_used_at,
        "retired_at": retired_at,
        "created_at": created,
        "updated_at": updated,
        "summary": str(summary or ""),
        "source_refs": _list(source_refs) or [*memory_refs, *wiki_refs],
        "validation_hooks": _list(validation_hooks) or validation,
        "safety_notes": _list(safety_notes),
        "redacted": bool(redacted),
        "shareable": bool(shareable),
        "sensitivity": str(sensitivity or "normal"),
    }


class SkillMemoryRegistry:
    """Local/dev skill metadata adapter backed by SessionDB state_meta."""

    def __init__(self, db: SessionDB):
        self.db = db

    @staticmethod
    def _key(skill: Dict[str, Any]) -> str:
        tenant = skill.get("tenant_id") or "_global"
        return f"{STATE_PREFIX}{tenant}:{skill['skill_id']}"

    def save(self, skill: Dict[str, Any]) -> Dict[str, Any]:
        record = dict(skill)
        record["updated_at"] = float(record.get("updated_at") or _now())
        self.db.set_meta(self._key(record), stable_json(record))
        return record

    @staticmethod
    def _feedback_key(feedback: Dict[str, Any]) -> str:
        tenant = feedback.get("tenant_id") or "_global"
        return f"{FEEDBACK_PREFIX}{tenant}:{feedback['feedback_id']}"

    @staticmethod
    def _candidate_key(candidate: Dict[str, Any]) -> str:
        tenant = candidate.get("tenant_id") or "_global"
        return f"{CANDIDATE_PREFIX}{tenant}:{candidate['candidate_id']}"

    def get(self, skill_id: str, *, tenant_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        keys = []
        if tenant_id:
            keys.append(f"{STATE_PREFIX}{tenant_id}:{skill_id}")
        keys.append(f"{STATE_PREFIX}_global:{skill_id}")
        for key in keys:
            raw = self.db.get_meta(key)
            if raw:
                return json.loads(raw)
        if tenant_id:
            return None
        for record in self.list():
            if record.get("skill_id") == skill_id:
                return record
        return None

    def list(
        self,
        *,
        tenant_id: Optional[str] = None,
        scope: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        prefix = f"{STATE_PREFIX}{tenant_id}:%" if tenant_id else f"{STATE_PREFIX}%"
        with self.db._lock:
            rows = self.db._conn.execute(
                "SELECT value FROM state_meta WHERE key LIKE ? ORDER BY key LIMIT ?",
                (prefix, max(1, int(limit))),
            ).fetchall()
        records = [json.loads(row["value"] if isinstance(row, sqlite3.Row) else row[0]) for row in rows]
        if scope is not None:
            records = [record for record in records if record.get("scope") == scope]
        return records

    def save_feedback(self, feedback: Dict[str, Any]) -> Dict[str, Any]:
        self.db.set_meta(self._feedback_key(feedback), stable_json(feedback))
        return feedback

    def list_feedback(self, *, tenant_id: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        prefix = f"{FEEDBACK_PREFIX}{tenant_id}:%" if tenant_id else f"{FEEDBACK_PREFIX}%"
        with self.db._lock:
            rows = self.db._conn.execute(
                "SELECT value FROM state_meta WHERE key LIKE ? ORDER BY key LIMIT ?",
                (prefix, max(1, int(limit))),
            ).fetchall()
        return [json.loads(row["value"] if isinstance(row, sqlite3.Row) else row[0]) for row in rows]

    def save_candidate(self, candidate: Dict[str, Any]) -> Dict[str, Any]:
        self.db.set_meta(self._candidate_key(candidate), stable_json(candidate))
        return candidate

    def list_candidates(self, *, tenant_id: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        prefix = f"{CANDIDATE_PREFIX}{tenant_id}:%" if tenant_id else f"{CANDIDATE_PREFIX}%"
        with self.db._lock:
            rows = self.db._conn.execute(
                "SELECT value FROM state_meta WHERE key LIKE ? ORDER BY key LIMIT ?",
                (prefix, max(1, int(limit))),
            ).fetchall()
        return [json.loads(row["value"] if isinstance(row, sqlite3.Row) else row[0]) for row in rows]


def build_skill_retrieval_query(
    *,
    raw_query: str,
    tenant_id: Optional[str] = None,
    repo_id: Optional[str] = None,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    task_id: Optional[str] = None,
    task_type: str = "general",
    intent: Optional[str] = None,
    toolset: Optional[str] = None,
    worker_role: Optional[str] = None,
    language: Optional[str] = None,
    platform: Optional[str] = None,
    error_signatures: Optional[Iterable[Any]] = None,
    success_signatures: Optional[Iterable[Any]] = None,
    entities: Optional[Iterable[Any]] = None,
    sensitivity: str = "normal",
    feature_state: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    lowered = raw_query.casefold()
    inferred_intent = intent or ("repair" if any(word in lowered for word in ("fix", "fail", "error")) else "retrieve")
    inferred_entities = _list(entities)
    if not inferred_entities:
        inferred_entities = sorted({token for token in _tokens(raw_query) if "/" in token or "." in token})
    query = SkillRetrievalQuery(
        raw_query=raw_query,
        tenant_id=tenant_id,
        repo_id=repo_id,
        user_id=user_id,
        session_id=session_id,
        task_id=task_id,
        task_type=task_type,
        intent=inferred_intent,
        toolset=toolset,
        worker_role=worker_role,
        language=language,
        platform=platform,
        error_signatures=_list(error_signatures),
        success_signatures=_list(success_signatures),
        entities=inferred_entities,
        sensitivity=sensitivity,
        feature_state=feature_state or {"skills_enabled": True},
    )
    return query.to_dict()


def _feature_enabled(query: Dict[str, Any]) -> bool:
    feature_state = query.get("feature_state") if isinstance(query.get("feature_state"), dict) else {}
    return bool(feature_state.get("skills_enabled", True))


def _hard_filter_reason(skill: Dict[str, Any], query: Dict[str, Any]) -> Optional[str]:
    if not _feature_enabled(query):
        return "feature_disabled"
    if skill.get("retired_at") or skill.get("approval_state") == "retired":
        return "retired"
    if skill.get("approval_state") not in APPROVED_STATES:
        return "approval_state"
    if skill.get("safety_state") not in SAFE_STATES:
        return "safety_state"
    if int(skill.get("harmful_count") or 0) > max(0, int(skill.get("helpful_count") or 0)):
        return "harmful_feedback"
    if query.get("sensitivity") in {"secret", "restricted"} and skill.get("sensitivity") not in {"normal", "public"}:
        return "sensitivity"

    tenant_id = query.get("tenant_id")
    skill_tenant = skill.get("tenant_id")
    scope = skill.get("scope")
    if scope == "global" or skill_tenant is None:
        feature_state = query.get("feature_state") if isinstance(query.get("feature_state"), dict) else {}
        if not feature_state.get("tenant_global_skill_opt_in", False):
            return "global_opt_in"
        if skill.get("approval_state") != "approved" or not skill.get("redacted") or not skill.get("shareable"):
            return "global_shareability"
    elif tenant_id and skill_tenant != tenant_id:
        return "tenant_visibility"

    repo_id = query.get("repo_id")
    skill_repo = skill.get("repo_id")
    if skill_repo and repo_id and skill_repo != repo_id:
        return "repo_visibility"
    if scope == "repo" and skill_repo and repo_id is None:
        return "repo_visibility"

    query_role = query.get("worker_role")
    skill_role = skill.get("worker_role")
    if query_role and skill_role and str(skill_role).casefold() not in ROLE_COMPATIBLE and skill_role != query_role:
        return "worker_role"

    query_toolset = query.get("toolset")
    skill_toolset = skill.get("toolset")
    if query_toolset and skill_toolset and skill_toolset != query_toolset:
        return "toolset"

    return None


def score_skill(
    skill: Dict[str, Any],
    query: Dict[str, Any],
    *,
    lexical_score: Optional[float] = None,
    semantic_score: float = 0.0,
    now: Optional[float] = None,
) -> Optional[Dict[str, Any]]:
    """Apply hard filters first, then deterministic local scoring."""
    reason = _hard_filter_reason(skill, query)
    if reason:
        return None

    query_terms = set(_tokens(" ".join([query.get("raw_query") or "", *query.get("error_signatures", []), *query.get("success_signatures", [])])))
    skill_text = " ".join(
        str(part)
        for part in (
            skill.get("name"),
            skill.get("domain"),
            skill.get("task_type"),
            skill.get("summary"),
            " ".join(skill.get("safety_notes") or []),
        )
        if part
    )
    skill_terms = set(_tokens(skill_text))
    overlap = sorted(query_terms & skill_terms)
    lexical = lexical_score if lexical_score is not None else len(overlap) / max(1, len(query_terms))

    score = 0.15 + lexical * 0.35 + max(0.0, semantic_score) * 0.1
    features: Dict[str, Any] = {"lexical_score": lexical, "semantic_score": semantic_score, "matched_terms": overlap}
    for field_name, weight in (
        ("tenant_id", 0.08),
        ("repo_id", 0.08),
        ("toolset", 0.08),
        ("task_type", 0.06),
        ("worker_role", 0.06),
        ("language", 0.03),
        ("platform", 0.03),
    ):
        if query.get(field_name) and skill.get(field_name) == query.get(field_name):
            score += weight
            features[f"{field_name}_match"] = True

    helpful = int(skill.get("helpful_count") or 0)
    irrelevant = int(skill.get("irrelevant_count") or 0)
    harmful = int(skill.get("harmful_count") or 0)
    usage = int(skill.get("usage_count") or 0)
    confidence = (helpful + 1) / max(1, usage + 2 + irrelevant + harmful * 3)
    score += min(0.15, confidence * 0.15)
    features["confidence"] = confidence

    scope = skill.get("scope")
    if scope in {"domain", "global"}:
        score -= 0.08 if scope == "domain" else 0.12
        features["scope_penalty"] = scope
    elif scope == "tenant":
        score -= 0.03
        features["scope_penalty"] = scope

    updated_at = float(skill.get("updated_at") or skill.get("created_at") or 0.0)
    if updated_at and now:
        age_days = max(0.0, (now - updated_at) / 86400)
        recency = max(0.0, 1.0 - min(age_days, 120.0) / 120.0)
        score += recency * 0.04
        features["recency"] = recency

    score = max(0.0, min(1.0, score))
    result = dict(skill)
    result["score"] = score
    result["confidence"] = max(0.0, min(1.0, confidence))
    result["match_reason"] = ", ".join(overlap[:6]) if overlap else "metadata match"
    result["features"] = features
    return result


def _records(source: Any) -> List[Dict[str, Any]]:
    if isinstance(source, SkillMemoryRegistry):
        return source.list(limit=1000)
    return [dict(item) for item in source]


def retrieve_skills(
    skills: Any,
    query: Dict[str, Any],
    *,
    limit: int = 5,
    min_score: float = 0.0,
) -> Dict[str, Any]:
    if not _feature_enabled(query):
        return {
            "status": "disabled",
            "skills": [],
            "audit": {"considered_count": 0, "filtered_count": 0, "returned_count": 0},
            "baseline_memory_passthrough": True,
            "delegation_passthrough": True,
        }

    selected: List[Dict[str, Any]] = []
    filtered = 0
    considered = 0
    for skill in _records(skills):
        considered += 1
        if _hard_filter_reason(skill, query):
            filtered += 1
            continue
        scored = score_skill(skill, query, now=_now())
        if scored is None:
            filtered += 1
            continue
        if scored["score"] < min_score:
            continue
        selected.append(scored)
    selected.sort(key=lambda item: (-float(item.get("score") or 0.0), item.get("skill_id") or ""))
    selected = selected[: max(1, int(limit))]
    return {
        "status": "ok",
        "skills": selected,
        "audit": {
            "considered_count": considered,
            "filtered_count": filtered,
            "returned_count": len(selected),
            "strategy": "hard_filters_then_local_scoring",
        },
        "baseline_memory_passthrough": True,
        "delegation_passthrough": True,
    }


def _packet_item(skill: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "skill_id": skill.get("skill_id"),
        "name": skill.get("name"),
        "version": skill.get("version"),
        "scope": skill.get("scope"),
        "summary": skill.get("summary") or "",
        "match_reason": skill.get("match_reason") or "metadata match",
        "confidence": round(float(skill.get("confidence") or 0.0), 4),
        "validation_hooks": _list(skill.get("validation_hooks")) or _list(skill.get("validation_refs")),
        "source_refs": _list(skill.get("source_refs")) or [*_list(skill.get("source_memory_refs")), *_list(skill.get("source_wiki_refs"))],
        "safety_notes": _list(skill.get("safety_notes")),
        "content_sha256": skill.get("content_sha256"),
        "bundle_tree_sha256": skill.get("bundle_tree_sha256"),
    }


def build_bounded_skill_packet(
    *,
    query: Dict[str, Any],
    skills: Sequence[Dict[str, Any]],
    worker_role: str,
    max_skills: int = 3,
    max_token_estimate: int = 900,
) -> Dict[str, Any]:
    if not _feature_enabled(query):
        return {
            "status": "disabled",
            "packet_id": None,
            "tenant_id": query.get("tenant_id"),
            "repo_id": query.get("repo_id"),
            "task_id": query.get("task_id"),
            "worker_role": worker_role,
            "skills": [],
            "token_estimate": 0,
            "created_at": _now(),
            "authority": "advisory_only_no_override",
            "authority_guard": ADVISORY_GUARD,
            "baseline_memory_passthrough": True,
            "delegation_passthrough": True,
        }

    role_query = dict(query)
    role_query["worker_role"] = worker_role
    retrieved = retrieve_skills(skills, role_query, limit=max_skills)
    packet_skills: List[Dict[str, Any]] = []
    used_tokens = _estimate_tokens(ADVISORY_GUARD)
    for skill in retrieved["skills"]:
        item = _packet_item(skill)
        item_tokens = _estimate_tokens(item)
        if packet_skills and used_tokens + item_tokens > max_token_estimate:
            break
        if not packet_skills or used_tokens + item_tokens <= max_token_estimate:
            packet_skills.append(item)
            used_tokens += item_tokens
    created_at = _now()
    packet_identity = stable_json(
        {
            "tenant_id": query.get("tenant_id"),
            "repo_id": query.get("repo_id"),
            "task_id": query.get("task_id"),
            "worker_role": worker_role,
            "skills": [item.get("skill_id") for item in packet_skills],
            "created_at": int(created_at),
        }
    )
    return {
        "status": "ok" if packet_skills else "skipped",
        "packet_id": f"skill_packet_{_sha256_text(packet_identity)[:20]}",
        "tenant_id": query.get("tenant_id"),
        "repo_id": query.get("repo_id"),
        "task_id": query.get("task_id"),
        "worker_role": worker_role,
        "skills": packet_skills,
        "token_estimate": used_tokens,
        "created_at": created_at,
        "authority": "advisory_only_no_override",
        "authority_guard": ADVISORY_GUARD,
        "baseline_memory_passthrough": True,
        "delegation_passthrough": True,
        "retrieval_audit": retrieved["audit"],
    }


def build_skill_feedback(
    *,
    tenant_id: Optional[str],
    repo_id: Optional[str],
    task_id: str,
    session_id: Optional[str],
    skill_id: str,
    skill_version: str,
    worker_role: str,
    impact: str,
    evidence_refs: Optional[Iterable[Any]] = None,
    validation_refs: Optional[Iterable[Any]] = None,
    reason: str = "",
    created_at: Optional[float] = None,
    feedback_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Build bounded outcome feedback without raw transcript/log content."""
    if impact not in {"helpful", "irrelevant", "harmful", "unknown"}:
        raise ValueError(f"invalid skill feedback impact: {impact}")
    created = float(created_at if created_at is not None else _now())
    refs = _bounded_refs(evidence_refs)
    validations = _bounded_refs(validation_refs)
    identity = {
        "tenant_id": tenant_id,
        "repo_id": repo_id,
        "task_id": task_id,
        "session_id": session_id,
        "skill_id": skill_id,
        "skill_version": skill_version,
        "worker_role": worker_role,
        "impact": impact,
        "evidence_refs": refs,
        "validation_refs": validations,
        "created_at": int(created),
    }
    return {
        "feedback_id": feedback_id or f"skill_feedback_{_sha256_text(stable_json(identity))[:20]}",
        "tenant_id": tenant_id,
        "repo_id": repo_id,
        "task_id": str(task_id),
        "session_id": session_id,
        "skill_id": str(skill_id),
        "skill_version": str(skill_version),
        "worker_role": str(worker_role),
        "impact": impact,
        "evidence_refs": refs,
        "validation_refs": validations,
        "reason": _bounded_text(reason, limit=280),
        "created_at": created,
    }


def record_skill_feedback(registry: SkillMemoryRegistry, feedback: Dict[str, Any]) -> Dict[str, Any]:
    return registry.save_feedback(dict(feedback))


def build_harmful_skill_candidate(
    *,
    skill: Dict[str, Any],
    feedback: Dict[str, Any],
    candidate_kind: str = "repair",
) -> Dict[str, Any]:
    if candidate_kind not in {"repair", "retire"}:
        raise ValueError("candidate_kind must be repair or retire")
    created = _now()
    identity = {
        "skill_id": skill.get("skill_id"),
        "skill_version": skill.get("version") or feedback.get("skill_version"),
        "feedback_id": feedback.get("feedback_id"),
        "candidate_kind": candidate_kind,
    }
    return {
        "candidate_id": f"skill_candidate_{_sha256_text(stable_json(identity))[:20]}",
        "candidate_kind": candidate_kind,
        "candidate_state": "proposed",
        "tenant_id": skill.get("tenant_id") or feedback.get("tenant_id"),
        "repo_id": skill.get("repo_id") or feedback.get("repo_id"),
        "skill_id": skill.get("skill_id"),
        "skill_version": skill.get("version") or feedback.get("skill_version"),
        "name": skill.get("name"),
        "summary": _bounded_text(f"Review harmful feedback: {feedback.get('reason')}", limit=220),
        "source_feedback_refs": [feedback.get("feedback_id")],
        "evidence_refs": _bounded_refs(feedback.get("evidence_refs")),
        "validation_refs": _bounded_refs(feedback.get("validation_refs")),
        "approval_state": "candidate",
        "requires_validation": True,
        "requires_operator_approval": True,
        "can_publish": False,
        "created_at": created,
        "updated_at": created,
    }


def apply_skill_feedback(registry: SkillMemoryRegistry, feedback: Dict[str, Any]) -> Dict[str, Any]:
    skill = registry.get(feedback["skill_id"], tenant_id=feedback.get("tenant_id")) or registry.get(feedback["skill_id"])
    if skill is None:
        raise KeyError(f"skill not found: {feedback['skill_id']}")
    updated = dict(skill)
    impact = feedback.get("impact")
    updated["usage_count"] = int(updated.get("usage_count") or 0) + 1
    count_field = f"{impact}_count"
    if count_field in {"helpful_count", "irrelevant_count", "harmful_count"}:
        updated[count_field] = int(updated.get(count_field) or 0) + 1
    updated["unknown_count"] = int(updated.get("unknown_count") or 0) + (1 if impact == "unknown" else 0)
    updated["last_feedback_id"] = feedback.get("feedback_id")
    updated["last_used_at"] = max(float(updated.get("last_used_at") or 0.0), float(feedback.get("created_at") or _now()))
    helpful = int(updated.get("helpful_count") or 0)
    harmful = int(updated.get("harmful_count") or 0)
    if impact == "harmful":
        updated["retrieval_demoted"] = True
        updated["safety_state"] = "restricted" if updated.get("safety_state") == "safe" else updated.get("safety_state", "unknown")
        kind = "retire" if harmful > helpful else "repair"
        registry.save_candidate(build_harmful_skill_candidate(skill=updated, feedback=feedback, candidate_kind=kind))
    registry.save(updated)
    return updated


def _approved_ref_ids(refs: Optional[Iterable[Any]], *, kind: str) -> List[str]:
    approved: List[str] = []
    for index, item in enumerate(refs or []):
        if isinstance(item, dict):
            state = item.get("approval_state") or item.get("status")
            ref_id = item.get("ref") or item.get("id") or item.get(f"{kind}_id")
            raw = stable_json(item)
        else:
            state = "approved"
            ref_id = str(item)
            raw = str(item)
        if state != "approved" or not ref_id:
            continue
        ref = _bounded_text(ref_id, limit=120)
        if "raw_session" in raw or re.search(r"(?i)(SECRET|TOKEN|PASSWORD|API_KEY)", raw):
            ref = f"{kind}_{index}_{_sha256_text(raw)[:12]}"
        approved.append(ref)
    return approved


def build_skill_candidate_from_memory(
    *,
    tenant_id: Optional[str],
    repo_id: Optional[str],
    name: str,
    version: str,
    summary: str,
    source_memory_refs: Optional[Iterable[Any]] = None,
    source_wiki_refs: Optional[Iterable[Any]] = None,
    toolset: Optional[str] = None,
    worker_role: Optional[str] = None,
    validation_refs: Optional[Iterable[Any]] = None,
    approval_refs: Optional[Iterable[Any]] = None,
    created_at: Optional[float] = None,
) -> Dict[str, Any]:
    memory_refs = _approved_ref_ids(source_memory_refs, kind="memory")
    wiki_refs = _approved_ref_ids(source_wiki_refs, kind="wiki")
    if not memory_refs and not wiki_refs:
        raise ValueError("skill candidates require approved memory/wiki refs")
    validations = _bounded_refs(validation_refs)
    approvals = _bounded_refs(approval_refs)
    created = float(created_at if created_at is not None else _now())
    identity = {
        "tenant_id": tenant_id,
        "repo_id": repo_id,
        "name": name,
        "version": version,
        "source_memory_refs": memory_refs,
        "source_wiki_refs": wiki_refs,
    }
    can_publish = bool(validations and approvals)
    metadata = build_skill_metadata(
        name=name,
        version=version,
        scope="repo" if repo_id else "tenant",
        tenant_id=tenant_id,
        repo_id=repo_id,
        toolset=toolset,
        worker_role=worker_role,
        approval_state="candidate",
        safety_state="unknown",
        content=summary,
        source_memory_refs=memory_refs,
        source_wiki_refs=wiki_refs,
        validation_refs=validations,
        summary=_bounded_text(summary, limit=320),
        created_at=created,
        updated_at=created,
    )
    metadata.update(
        {
            "candidate_id": f"skill_candidate_{_sha256_text(stable_json(identity))[:20]}",
            "candidate_kind": "new_skill",
            "candidate_state": "validated" if can_publish else "proposed",
            "requires_validation": not bool(validations),
            "requires_operator_approval": not bool(approvals),
            "approval_refs": approvals,
            "can_publish": can_publish,
        }
    )
    return metadata


def attach_skill_refs_to_runtime_packet(packet: Any, skill_packet: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Attach compact skill refs to a runtime packet shape, stripping raw skill bodies."""
    if hasattr(packet, "to_dict"):
        data = packet.to_dict()
    else:
        data = dict(packet or {})
    for key in list(data):
        if "skill_content" in key or key == "skills":
            data.pop(key, None)
    if not skill_packet:
        data.setdefault("skill_packet_id", None)
        data.setdefault("skill_refs", [])
        return data
    refs = []
    for item in skill_packet.get("skills") or []:
        refs.append(
            {
                "skill_id": item.get("skill_id"),
                "version": item.get("version"),
                "content_sha256": item.get("content_sha256"),
                "bundle_tree_sha256": item.get("bundle_tree_sha256"),
            }
        )
    data["skill_packet_id"] = skill_packet.get("packet_id")
    data["skill_refs"] = refs
    return data


class SkillClawAdapter:
    """Local SkillClaw-compatible bundle adapter with shared sync disabled by default."""

    def __init__(self, root: Path | str, *, shared_sync_enabled: bool = False):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.shared_sync_enabled = bool(shared_sync_enabled)

    def _path(self, bundle_id: str) -> Path:
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", bundle_id)
        return self.root / f"{safe}.json"

    def write_bundle(
        self,
        *,
        skill: Dict[str, Any],
        files: Optional[Dict[str, str]] = None,
        validation_refs: Optional[Iterable[Any]] = None,
    ) -> Dict[str, Any]:
        compact_files = {
            str(path): {
                "sha256": _sha256_text(str(content)),
                "size": len(str(content).encode("utf-8")),
            }
            for path, content in sorted((files or {}).items())
        }
        tree_digest = _sha256_text(stable_json({"skill": _packet_item(skill), "files": compact_files}))
        bundle = {
            "bundle_id": f"skillclaw_{skill.get('skill_id')}_{tree_digest[:12]}",
            "skill_id": skill.get("skill_id"),
            "version": skill.get("version"),
            "content_sha256": skill.get("content_sha256"),
            "bundle_tree_sha256": tree_digest,
            "files": compact_files,
            "validation_refs": _bounded_refs(validation_refs),
            "created_at": _now(),
            "shared_sync_enabled": self.shared_sync_enabled,
        }
        self._path(bundle["bundle_id"]).write_text(stable_json(bundle), encoding="utf-8")
        return bundle

    def read_bundle(self, bundle_id: str) -> Dict[str, Any]:
        return json.loads(self._path(bundle_id).read_text(encoding="utf-8"))

    def ingest_validation_result(
        self,
        bundle_id: str,
        *,
        status: str,
        validation_refs: Optional[Iterable[Any]] = None,
        reason: str = "",
    ) -> Dict[str, Any]:
        bundle = self.read_bundle(bundle_id)
        result = {
            "bundle_id": bundle_id,
            "status": status,
            "validation_refs": _bounded_refs(validation_refs),
            "reason": _bounded_text(reason, limit=220),
            "created_at": _now(),
        }
        bundle["validation_result"] = result
        self._path(bundle_id).write_text(stable_json(bundle), encoding="utf-8")
        return result

    def stage_candidate(
        self,
        bundle: Dict[str, Any],
        *,
        tenant_id: Optional[str],
        global_candidate: bool = False,
    ) -> Dict[str, Any]:
        staged = {
            "bundle_id": bundle.get("bundle_id"),
            "tenant_id": tenant_id,
            "stage": "global_candidate" if global_candidate else "tenant_candidate",
            "content_sha256": bundle.get("content_sha256"),
            "bundle_tree_sha256": bundle.get("bundle_tree_sha256"),
            "can_publish": False,
            "shared_sync_enabled": self.shared_sync_enabled,
            "created_at": _now(),
        }
        bundle["staged_candidate"] = staged
        self._path(bundle["bundle_id"]).write_text(stable_json(bundle), encoding="utf-8")
        return staged

    def sync_shared(self) -> Dict[str, Any]:
        if not self.shared_sync_enabled:
            return {"status": "disabled", "reason": "shared SkillClaw sync is disabled by default"}
        return {"status": "skipped", "reason": "local adapter does not perform network sync"}


def build_skill_e2e_fixture(
    *,
    registry: SkillMemoryRegistry,
    tenant_id: str,
    repo_id: str,
    task_id: str,
    session_id: str,
    raw_query: str,
) -> Dict[str, Any]:
    skill = registry.save(
        build_skill_metadata(
            name="e2e pytest repair",
            version="1.0.0",
            scope="repo",
            tenant_id=tenant_id,
            repo_id=repo_id,
            toolset="terminal",
            worker_role="worker",
            task_type="validation",
            approval_state="approved",
            safety_state="safe",
            content="bounded procedure",
            summary="Fix pytest failures and rerun focused validation.",
            source_memory_refs=["mem-approved-e2e"],
            source_wiki_refs=["wiki-approved-e2e"],
            validation_refs=["pytest://e2e"],
        )
    )
    query = build_skill_retrieval_query(
        raw_query=raw_query,
        tenant_id=tenant_id,
        repo_id=repo_id,
        task_id=task_id,
        session_id=session_id,
        toolset="terminal",
        worker_role="worker",
        task_type="validation",
        feature_state={"skills_enabled": True},
    )
    retrieval = retrieve_skills(registry, query)
    skill_packet = build_bounded_skill_packet(query=query, skills=retrieval["skills"], worker_role="worker")
    worker_packet = attach_skill_refs_to_runtime_packet(
        {
            "id": f"worker_{task_id}",
            "task_id": task_id,
            "worker_role": "worker",
            "objective": _bounded_text(raw_query, limit=160),
        },
        skill_packet,
    )
    validation_refs = ["pytest://tests/hermes_cli/test_skill_memory.py"]
    feedback = record_skill_feedback(
        registry,
        build_skill_feedback(
            tenant_id=tenant_id,
            repo_id=repo_id,
            task_id=task_id,
            session_id=session_id,
            skill_id=skill["skill_id"],
            skill_version=skill["version"],
            worker_role="worker",
            impact="helpful",
            evidence_refs=["worker://result"],
            validation_refs=validation_refs,
            reason="Skill helped produce passing validation.",
        ),
    )
    apply_skill_feedback(registry, feedback)
    candidate = registry.save_candidate(
        build_skill_candidate_from_memory(
            tenant_id=tenant_id,
            repo_id=repo_id,
            name="e2e evolved pytest repair",
            version="1.0.1",
            summary="Refine pytest repair guidance from approved evidence.",
            source_memory_refs=[{"ref": "mem-approved-e2e", "approval_state": "approved"}],
            source_wiki_refs=[{"ref": "wiki-approved-e2e", "approval_state": "approved"}],
            toolset="terminal",
            worker_role="worker",
            validation_refs=validation_refs,
        )
    )
    return {
        "query": query,
        "retrieval": retrieval,
        "skill_packet": skill_packet,
        "worker_packet": worker_packet,
        "validation_refs": validation_refs,
        "feedback": feedback,
        "candidate": candidate,
    }
