"""DGM-H experiment lane helpers.

This module keeps HyperAgent-style evolution bounded: Hermes stores variants
and evaluations, but promotion still flows through reviewed meta-candidates.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from hermes_cli.config import load_config
from hermes_state import SessionDB


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


@dataclass
class DgmVariantResult:
    variant_id: str
    status: str
    kind: str
    tool_profile: str
    parent_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DgmEvaluationResult:
    evaluation_id: str
    variant_id: str
    status: str
    score: Optional[float]
    tool_profile: str
    meta_candidate_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ToolProfileResult:
    profile: str
    tools: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DgmEvolutionResult:
    status: str
    objective: str
    parent_ids: List[str]
    child_ids: List[str]
    evaluations: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def get_supervisor_tool_registry(config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    cfg = config or load_config()
    registry = cfg.get("supervisor", {}).get("tools", {}).get("registry", {})
    return registry if isinstance(registry, dict) else {}


def get_tool_profile_tools(
    profile: str,
    *,
    config: Optional[Dict[str, Any]] = None,
) -> ToolProfileResult:
    cfg = config or load_config()
    supervisor = cfg.get("supervisor", {})
    tools_cfg = supervisor.get("tools", {}) if isinstance(supervisor, dict) else {}
    registry = tools_cfg.get("registry", {}) if isinstance(tools_cfg, dict) else {}
    profiles = tools_cfg.get("profiles", {}) if isinstance(tools_cfg, dict) else {}
    allowed_names = profiles.get(profile, [])
    if not isinstance(allowed_names, list):
        allowed_names = []
    tools: List[Dict[str, Any]] = []
    for name in allowed_names:
        if not isinstance(name, str):
            continue
        entry = registry.get(name)
        if not isinstance(entry, dict):
            continue
        item = {"name": name, **entry}
        tools.append(item)
    return ToolProfileResult(profile=profile, tools=tools)


def create_dgm_variant(
    db: SessionDB,
    *,
    kind: str,
    body: str,
    tenant_id: Optional[str] = None,
    repo_id: Optional[str] = None,
    parent_id: Optional[str] = None,
    tool_profile: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    config: Optional[Dict[str, Any]] = None,
) -> DgmVariantResult:
    cfg = config or load_config()
    dgm_cfg = cfg.get("supervisor", {}).get("dgm_h", {})
    if not isinstance(dgm_cfg, dict):
        dgm_cfg = {}
    selected_profile = tool_profile or dgm_cfg.get("default_tool_profile") or "repo_eval"
    variant_id = _new_id("dgmvar")
    db.upsert_dgm_variant(
        variant_id=variant_id,
        kind=kind,
        body=body,
        parent_id=parent_id,
        tool_profile=str(selected_profile),
        status="proposed",
        metadata_json={
            "created_by": "hermes.dgm_h",
            "created_at": time.time(),
            **(metadata or {}),
        },
        tenant_id=tenant_id,
        repo_id=repo_id,
    )
    return DgmVariantResult(
        variant_id=variant_id,
        status="proposed",
        kind=kind,
        tool_profile=str(selected_profile),
        parent_id=parent_id,
    )


def select_dgm_parents(
    db: SessionDB,
    *,
    tenant_id: Optional[str] = None,
    repo_id: Optional[str] = None,
    limit: int = 3,
) -> List[Dict[str, Any]]:
    selected: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for status in ("approved", "evaluated", "proposed"):
        rows = db.list_dgm_variants(
            tenant_id=tenant_id,
            repo_id=repo_id,
            status=status,
            limit=max(limit * 3, limit),
        )
        rows = sorted(
            rows,
            key=lambda row: (
                float(row.get("score") if row.get("score") is not None else -1.0),
                float(row.get("created_at") or 0.0),
            ),
            reverse=True,
        )
        for row in rows:
            variant_id = str(row.get("id") or "")
            if not variant_id or variant_id in seen:
                continue
            selected.append(row)
            seen.add(variant_id)
            if len(selected) >= limit:
                return selected
    return selected


def evolve_dgm_variants(
    db: SessionDB,
    *,
    objective: str,
    tenant_id: Optional[str] = None,
    repo_id: Optional[str] = None,
    kind: str = "playbook",
    children: int = 1,
    tool_profile: Optional[str] = None,
    dry_score: Optional[float] = None,
    config: Optional[Dict[str, Any]] = None,
) -> DgmEvolutionResult:
    cfg = config or load_config()
    dgm_cfg = cfg.get("supervisor", {}).get("dgm_h", {})
    if not isinstance(dgm_cfg, dict):
        dgm_cfg = {}
    max_parents = int(dgm_cfg.get("max_parents", 3) or 3)
    parent_limit = max(1, min(max_parents, max(1, children)))
    parents = select_dgm_parents(
        db,
        tenant_id=tenant_id,
        repo_id=repo_id,
        limit=parent_limit,
    )
    selected_profile = tool_profile or dgm_cfg.get("default_tool_profile") or "repo_eval"
    child_ids: List[str] = []
    evaluations: List[Dict[str, Any]] = []
    if not parents:
        seed = create_dgm_variant(
            db,
            kind=kind,
            body=f"Seed DGM-H variant for objective: {objective}",
            tenant_id=tenant_id,
            repo_id=repo_id,
            tool_profile=str(selected_profile),
            metadata={
                "objective": objective,
                "generation": 0,
                "evolution_role": "seed",
            },
            config=cfg,
        )
        parents = [db.get_dgm_variant(seed.variant_id) or {"id": seed.variant_id, "body": ""}]

    for index in range(max(1, children)):
        parent = parents[index % len(parents)]
        parent_id = str(parent.get("id") or "")
        parent_body = str(parent.get("body") or parent.get("kind") or "").strip()
        child_body = (
            f"Objective: {objective}\n"
            f"Parent: {parent_id}\n"
            f"Mutation: refine the parent guidance into a bounded, evidence-backed "
            f"{kind} variant for future sandbox evaluation.\n"
            f"Parent body: {parent_body[:1200]}"
        )
        child = create_dgm_variant(
            db,
            kind=kind,
            body=child_body,
            tenant_id=tenant_id or parent.get("tenant_id"),
            repo_id=repo_id or parent.get("repo_id"),
            parent_id=parent_id or None,
            tool_profile=str(selected_profile),
            metadata={
                "objective": objective,
                "generation": int((parent.get("metadata_json") or {}).get("generation", 0) or 0) + 1
                if isinstance(parent.get("metadata_json"), dict)
                else 1,
                "parent_score": parent.get("score"),
                "evolution_role": "child",
            },
            config=cfg,
        )
        child_ids.append(child.variant_id)
        if dry_score is not None:
            evaluation = record_dgm_evaluation(
                db,
                variant_id=child.variant_id,
                score=dry_score,
                tenant_id=tenant_id or parent.get("tenant_id"),
                repo_id=repo_id or parent.get("repo_id"),
                task_set="dry-evolution",
                tool_profile=str(selected_profile),
                metrics={
                    "dry_run": True,
                    "objective": objective,
                    "parent_id": parent_id,
                },
                artifact_uri=f"dgm://variant/{child.variant_id}/dry-evaluation",
                status="dry_evaluated",
                create_candidate=False,
            )
            evaluations.append(evaluation.to_dict())
    return DgmEvolutionResult(
        status="completed",
        objective=objective,
        parent_ids=[str(parent.get("id") or "") for parent in parents if parent],
        child_ids=child_ids,
        evaluations=evaluations,
    )


def record_dgm_evaluation(
    db: SessionDB,
    *,
    variant_id: str,
    score: Optional[float],
    tenant_id: Optional[str] = None,
    repo_id: Optional[str] = None,
    task_set: Optional[str] = None,
    tool_profile: Optional[str] = None,
    metrics: Optional[Dict[str, Any]] = None,
    artifact_uri: Optional[str] = None,
    status: str = "evaluated",
    create_candidate: bool = False,
) -> DgmEvaluationResult:
    variant = db.get_dgm_variant(variant_id)
    if variant is None:
        raise ValueError(f"unknown DGM-H variant: {variant_id}")
    selected_profile = tool_profile or variant.get("tool_profile") or "repo_eval"
    evaluation_id = _new_id("dgmeval")
    db.record_dgm_evaluation(
        evaluation_id=evaluation_id,
        variant_id=variant_id,
        tenant_id=tenant_id or variant.get("tenant_id"),
        repo_id=repo_id or variant.get("repo_id"),
        task_set=task_set,
        tool_profile=str(selected_profile),
        score=score,
        metrics_json=metrics or {},
        artifact_uri=artifact_uri,
        status=status,
    )
    meta_candidate_id = None
    if create_candidate:
        meta_candidate_id = f"metacand_{variant_id}"
        evidence = {
            "variant_id": variant_id,
            "evaluation_id": evaluation_id,
            "score": score,
            "tool_profile": selected_profile,
            "task_set": task_set,
            "artifact_uri": artifact_uri,
            "metrics": metrics or {},
        }
        claim = str(variant.get("body") or variant.get("kind") or variant_id)[:240]
        db.upsert_meta_candidate(
            candidate_id=meta_candidate_id,
            kind=str(variant.get("kind") or "playbook"),
            claim=claim,
            evidence_json=evidence,
            score=score,
            status="proposed",
            tenant_id=tenant_id or variant.get("tenant_id"),
            repo_id=repo_id or variant.get("repo_id"),
        )
    return DgmEvaluationResult(
        evaluation_id=evaluation_id,
        variant_id=variant_id,
        status=status,
        score=score,
        tool_profile=str(selected_profile),
        meta_candidate_id=meta_candidate_id,
    )


def parse_metrics_json(raw: str) -> Dict[str, Any]:
    if not raw:
        return {}
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("--metrics-json must decode to an object")
    return value
