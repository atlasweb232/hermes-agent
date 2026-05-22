"""Production-closure smoke runner for runtime learning.

The default mode is deterministic and local: it exercises the closure gates
without calling live providers, starting daemons, or enabling enforcement.
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any, Mapping, Optional

from hermes_cli.curator_runtime import run_curator_policy_pass
from hermes_cli.goal_allocator import (
    WorkerAllocationPlan,
    WorkerAttemptResult,
    WorkerHealth,
    choose_next_worker,
    update_worker_health_from_attempt,
)
from hermes_cli.learning_judge import run_learning_judge
from hermes_cli.model_roles import doctor_model_roles
from hermes_cli.operator_dashboard import build_runtime_impact_panel, seed_operator_dashboard_fixture
from hermes_cli.redaction_guard import redact_value
from hermes_cli.runtime_urgent_notify import UrgentNotification, send_urgent_notification
from hermes_cli.sidecar_readiness import run_sidecar_readiness
from hermes_cli.skill_memory import (
    SkillMemoryRegistry,
    apply_skill_feedback,
    build_bounded_skill_packet,
    build_skill_candidate_from_memory,
    build_skill_feedback,
    build_skill_retrieval_query,
    publish_skill_candidate,
    record_skill_feedback,
    retrieve_skills,
    stable_json,
)
from hermes_state import SessionDB


SECRET_SENTINELS = ("sk-", "xoxb-", "ghp_", "password=", "api_key=", "token=")


def _now() -> float:
    return time.time()


def _gate(name: str, passed: bool, **details: Any) -> dict[str, Any]:
    return redact_value({"name": name, "status": "passed" if passed else "failed", **details})


def _seed_runtime_failure(db: SessionDB, *, tenant_id: str, repo_id: str, task_id: str) -> str:
    record_id = f"prodsmoke_failure_{uuid.uuid4().hex[:12]}"
    db.upsert_memory_record(
        record_id=record_id,
        kind="supervisor_runtime_failure",
        title="Production smoke delegated worker empty output",
        body="Delegated worker returned empty output; bounded evidence should become advisory learning.",
        payload_json={
            "detector": "production_runtime_smoke",
            "failure_type": "delegated_worker_runtime_failure",
            "task_id": task_id,
            "worker_id": "claude-code",
            "worker_family": "claude",
            "requested_route": "claude primary",
            "actual_route": "worker-router claude",
            "route": "worker-router claude",
            "command_family": "worker-router",
            "status": "empty_output",
            "latency_ms": 120000,
            "allocation_id": "alloc_prodsmoke",
            "attempt_id": "attempt_prodsmoke_1",
            "evidence_refs": ["event://worker/prodsmoke-empty-output"],
            "validation_mismatch": {
                "validation_status": "failed",
                "error_signature": "empty_worker_output",
            },
            "output_excerpt": "",
            "error_excerpt": "worker returned no validated output",
            "requires_judge": True,
            "operator_approval_required": True,
            "secret_safe": True,
        },
        status="active",
        score=0.91,
        tenant_id=tenant_id,
        repo_id=repo_id,
        task_id=task_id,
        evidence_uri="event://worker/prodsmoke-empty-output",
    )
    return record_id


def _run_curator_and_judge(db: SessionDB, *, tenant_id: str, repo_id: str) -> dict[str, Any]:
    curator = run_curator_policy_pass(
        db,
        config={"supervisor": {"curator": {"provider": "codex", "max_records": 5}}},
        tenant_id=tenant_id,
        repo_id=repo_id,
        model_call=lambda _cfg, _prompt: "Empty worker output requires validation before accepting completion.",
    )
    proposed = [candidate for candidate in curator.candidates if candidate.status == "proposed"]

    def _judge_call(_cfg: Any, prompt: str) -> str:
        candidate_id = proposed[0].candidate_id if proposed else ""
        return json.dumps(
            {
                "candidate_id": candidate_id,
                "decision": "approve",
                "confidence": 0.91,
                "rationale": "Bounded runtime failure evidence supports advisory recovery only.",
                "risk_flags": [],
                "allow_enforcement": False,
            },
            sort_keys=True,
        )

    judge = run_learning_judge(
        db,
        tenant_id=tenant_id,
        repo_id=repo_id,
        config={"supervisor": {"learning_judge": {"provider": "codex", "max_candidates": 5}}},
        model_call=_judge_call,
    )
    return {"curator": curator.to_dict(), "judge": judge.to_dict(), "proposed_candidates": proposed}


def _run_skill_evolution(db: SessionDB, *, tenant_id: str, repo_id: str, task_id: str, source_candidate_id: str) -> dict[str, Any]:
    registry = SkillMemoryRegistry(db)
    candidate = registry.save_candidate(
        build_skill_candidate_from_memory(
            tenant_id=tenant_id,
            repo_id=repo_id,
            name="production smoke worker validation recovery",
            version="1.0.0",
            summary="Validate delegated worker output and preserve evidence before accepting completion.",
            source_candidate_refs=[{"candidate_id": source_candidate_id, "status": "approved"}],
            toolset="terminal",
            worker_role="worker",
            validation_refs=["pytest://production-runtime-smoke"],
            approval_refs=["approval://operator/production-smoke"],
        )
    )
    publication = publish_skill_candidate(
        registry,
        candidate,
        judge_ref="judge://learning_judge/production-smoke",
        operator_approval_ref="approval://operator/production-smoke",
        published_by="production-smoke",
    )
    query = build_skill_retrieval_query(
        raw_query="delegated worker empty output validation recovery",
        tenant_id=tenant_id,
        repo_id=repo_id,
        task_id=task_id,
        toolset="terminal",
        worker_role="worker",
        feature_state={"skills_enabled": True},
    )
    retrieval = retrieve_skills(registry, query)
    packet = build_bounded_skill_packet(query=query, skills=registry, worker_role="worker")
    feedback = record_skill_feedback(
        registry,
        build_skill_feedback(
            tenant_id=tenant_id,
            repo_id=repo_id,
            task_id=task_id,
            session_id="production-smoke-session",
            skill_id=publication["skill"]["skill_id"],
            skill_version=publication["skill"]["version"],
            worker_role="worker",
            impact="harmful",
            evidence_refs=["validation://production-smoke/harmful"],
            validation_refs=["pytest://production-runtime-smoke/harmful"],
            reason="Synthetic harmful feedback proves demotion and repair candidate path.",
        ),
    )
    updated = apply_skill_feedback(registry, feedback)
    repair_candidates = [
        item
        for item in registry.list_candidates(tenant_id=tenant_id)
        if item.get("source_feedback_refs") == [feedback["feedback_id"]]
    ]
    return {
        "publication": publication,
        "retrieval": retrieval,
        "packet": packet,
        "feedback": feedback,
        "updated_skill": updated,
        "repair_candidates": repair_candidates,
    }


def _write_artifact(artifact_root: Optional[str | Path], run_id: str, payload: Mapping[str, Any]) -> Optional[str]:
    if not artifact_root:
        return None
    root = Path(artifact_root)
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{run_id}.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return str(path)


def _run_claude_to_codex_fallback() -> dict[str, Any]:
    plan = WorkerAllocationPlan(
        task_id="production_smoke_worker_task",
        session_id="production_smoke_session",
        objective="prove degraded Claude primary falls back to Codex",
        candidate_workers=["claude-code", "codex"],
        primary_worker="claude-code",
        fallback_order=["codex"],
        max_attempts=2,
        retry_same_worker=0,
        cooldown_seconds=300,
    )
    attempt = WorkerAttemptResult(
        allocation_id=plan.allocation_id,
        worker_id="claude-code",
        route="worker-router claude",
        status="empty_output",
        duration_seconds=60,
        error_signature="worker-router claude empty output",
    )
    health = update_worker_health_from_attempt(
        WorkerHealth(worker_id="claude-code"),
        attempt,
        cooldown_seconds=plan.cooldown_seconds,
        now=1_000,
    )
    decision = choose_next_worker(plan, [attempt], {"claude-code": health}, now=1_001)
    return {
        "primary_worker": "claude-code",
        "failed_status": "empty_output",
        "fallback_worker": decision.worker_id,
        "decision": decision.to_dict(),
        "passed": decision.action == "dispatch" and decision.worker_id == "codex",
    }


def run_production_runtime_smoke(
    db: SessionDB,
    *,
    config: Optional[dict[str, Any]] = None,
    tenant_id: str = "production-smoke-tenant",
    repo_id: str = "hermes-agent",
    artifact_root: Optional[str | Path] = None,
    require_urgent_channel: bool = False,
    env: Optional[dict[str, str]] = None,
) -> dict[str, Any]:
    run_id = f"prodsmoke_{uuid.uuid4().hex[:16]}"
    task_id = f"task_{run_id}"
    started = _now()
    cfg = dict(config or {})
    _seed_runtime_failure(db, tenant_id=tenant_id, repo_id=repo_id, task_id=task_id)
    fallback = _run_claude_to_codex_fallback()
    curator_judge = _run_curator_and_judge(db, tenant_id=tenant_id, repo_id=repo_id)
    proposed = curator_judge["proposed_candidates"]
    approved_id = proposed[0].candidate_id if proposed else ""
    skill = _run_skill_evolution(db, tenant_id=tenant_id, repo_id=repo_id, task_id=task_id, source_candidate_id=approved_id)
    sidecars = run_sidecar_readiness(
        db,
        config=cfg,
        mode="oneshot",
        run_once=True,
        sidecars=["curator", "learning_judge", "progress_summarizer", "bus_consumer"],
    ).to_dict()
    model_doctor = doctor_model_roles(cfg, roles=["curator", "learning_judge", "goal_judge"], env=env)
    notification = send_urgent_notification(
        UrgentNotification(
            severity="degraded",
            title="production smoke runtime degradation",
            message="Dry-run notification for production closure smoke.",
            task_id=task_id,
            repo_id=repo_id,
            worker_id="claude-code",
            event_kind="supervisor_runtime_failure",
            source="production_smoke",
        ),
        platform="slack",
        dry_run=True,
    )
    impact = build_runtime_impact_panel(
        seed_operator_dashboard_fixture(),
        actor={"actor_id": "production-smoke", "role": "platform-admin", "cross_tenant": True},
        tenant_id="tenant-a",
        repo_id="repo-a",
        worker_event_db=db,
    )
    elapsed_ms = int((_now() - started) * 1000)

    gates = [
        _gate("runtime_failure_capture", bool(approved_id), candidate_id=approved_id),
        _gate("codex_fallback_path", fallback["passed"], fallback_worker=fallback["fallback_worker"]),
        _gate("curator_candidate_creation", curator_judge["curator"]["candidates_created"] >= 1),
        _gate("learning_judge_decision", curator_judge["judge"]["approved"] >= 1),
        _gate("operator_approval_boundary", skill["publication"]["gate"]["requires_operator_approval"] is True),
        _gate("skill_publication", skill["publication"]["status"] == "published"),
        _gate("bounded_skill_packet", skill["packet"]["status"] == "ok" and bool(skill["packet"]["skills"])),
        _gate("harmful_feedback_demotes", skill["updated_skill"].get("retrieval_demoted") is True and bool(skill["repair_candidates"])),
        _gate("sidecars_non_blocking", sidecars["foreground_blocking"] is False),
        _gate("model_roles_structured", model_doctor["status"] in {"ready", "degraded"} and model_doctor["secrets_printed"] is False),
        _gate("notification_route", notification["status"] in {"dry_run", "skipped"} and (not require_urgent_channel or notification["status"] == "dry_run")),
        _gate("runtime_impact", impact["kind"] == "runtime_impact" and impact["raw_logs_loaded"] is False),
    ]
    payload: dict[str, Any] = redact_value(
        {
            "schema_version": 1,
            "run_id": run_id,
            "status": "passed" if all(gate["status"] == "passed" for gate in gates) else "failed",
            "tenant_id": tenant_id,
            "repo_id": repo_id,
            "task_id": task_id,
            "execution_mode": "deterministic_local",
            "enforcement_enabled": False,
            "foreground_blocking": False,
            "elapsed_ms": elapsed_ms,
            "gates": gates,
            "curator": curator_judge["curator"],
            "judge": curator_judge["judge"],
            "worker_fallback": fallback,
            "skill_evolution": {
                "publication": skill["publication"],
                "packet": skill["packet"],
                "feedback": skill["feedback"],
                "repair_candidates": skill["repair_candidates"],
            },
            "sidecars": sidecars,
            "model_roles": model_doctor,
            "notification": notification,
            "runtime_impact": {
                "kind": impact["kind"],
                "foreground": impact["foreground"],
                "latency_attribution": impact["latency_attribution"],
                "cost_attribution": impact["cost_attribution"],
                "context_attribution": impact["context_attribution"],
                "raw_logs_loaded": impact["raw_logs_loaded"],
                "raw_transcripts_loaded": impact["raw_transcripts_loaded"],
            },
            "safety": {
                "raw_transcripts_stored": False,
                "raw_logs_loaded": False,
                "secrets_printed": False,
                "live_provider_calls": False,
            },
        }
    )
    dumped = stable_json(payload).casefold()
    secret_leak = any(sentinel in dumped for sentinel in SECRET_SENTINELS)
    payload["safety"]["secret_sentinel_detected"] = secret_leak
    if secret_leak:
        payload["status"] = "failed"
        payload["gates"].append(_gate("secret_sentinel_scan", False))
    else:
        payload["gates"].append(_gate("secret_sentinel_scan", True))
    artifact_path = _write_artifact(artifact_root, run_id, payload)
    if artifact_path:
        payload["artifact_ref"] = artifact_path
    return payload
