"""Scripted runtime smoke helpers for allocator/degradation value checks."""

from __future__ import annotations

import subprocess
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from hermes_cli.goal_allocator import (
    WorkerAllocationPlan,
    WorkerAttemptResult,
    choose_next_worker,
    load_worker_health,
    save_allocation_plan,
    save_worker_attempt,
    save_worker_health,
    update_worker_health_from_attempt,
    WorkerHealth,
)
from hermes_cli.self_healing_workflow import (
    TaskGraph,
    TaskNode,
    create_task_graph,
    list_worker_progress_events,
    project_worker_progress_for_delivery,
    record_runtime_lease,
    run_health_check_once,
    run_progress_summarizer_sidecar,
    run_restart_recovery,
    run_worker_with_progress_events,
    update_task_node,
)
from hermes_state import SessionDB


@dataclass
class RuntimeSmokeResult:
    status: str
    scenario: str
    branch_ref: str
    upstream_ref: Optional[str]
    branch_capabilities: Dict[str, Any]
    upstream_capabilities: Dict[str, Any]
    allocator_decision: Dict[str, Any]
    repeated_failed_loop_result: Dict[str, Any]
    foreground_responsiveness_result: Dict[str, Any]
    restart_resume_result: Dict[str, Any]
    raw_worker_streams_result: Dict[str, Any]
    notes: list[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _git_ref_contains(repo: Path, ref: str, pattern: str) -> bool:
    try:
        proc = subprocess.run(
            ["git", "grep", "-q", pattern, ref, "--"],
            cwd=repo,
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except Exception:
        return False
    return proc.returncode == 0


def _capabilities(repo: Path, ref: str) -> Dict[str, Any]:
    return {
        "runtime_failure_gate": _git_ref_contains(repo, ref, "RuntimeFailureGate"),
        "empty_output_degraded": _git_ref_contains(repo, ref, "empty_output"),
        "goal_allocator": _git_ref_contains(repo, ref, "WorkerAllocationPlan"),
        "worker_health": _git_ref_contains(repo, ref, "worker_health:"),
    }


def _smoke_graph() -> TaskGraph:
    return TaskGraph(
        graph_id="smoke_graph",
        session_id="smoke_session",
        tenant_id="tenant-smoke",
        repo_id="repo-smoke",
        root_task_id="task_loop",
        concurrency_limit=3,
        source="runtime_smoke",
    )


def _smoke_node(task_id: str, *, owned_path: str, **overrides: Any) -> TaskNode:
    data = {
        "task_id": task_id,
        "graph_id": "smoke_graph",
        "title": task_id,
        "objective": f"finish {task_id}",
        "owned_paths": [owned_path],
        "validation_required": True,
    }
    data.update(overrides)
    return TaskNode(**data)


def _run_branch_owned_runtime_scenarios(branch_ref: str) -> Dict[str, Dict[str, Any]]:
    with tempfile.TemporaryDirectory(prefix="hermes-runtime-smoke-") as tmpdir:
        db = SessionDB(db_path=Path(tmpdir) / "state.db")
        try:
            create_task_graph(
                db,
                _smoke_graph(),
                [
                    _smoke_node("task_loop", owned_path="loop/"),
                    _smoke_node("task_resume", owned_path="resume/"),
                    _smoke_node("task_unknown", owned_path="unknown/"),
                    _smoke_node("task_cooling", owned_path="cooling/"),
                    _smoke_node("task_stream", owned_path="stream/"),
                ],
            )

            plan = WorkerAllocationPlan(
                task_id="task_loop",
                session_id="smoke_session",
                objective="prove repeated primary worker failures do not loop",
                candidate_workers=["claude-code", "codex"],
                primary_worker="claude-code",
                fallback_order=["codex"],
                allocation_id="alloc_loop",
                max_attempts=3,
                retry_same_worker=0,
                cooldown_seconds=120,
                retry_after_seconds=120,
            )
            save_allocation_plan(db, plan)
            update_task_node(
                db,
                "smoke_graph",
                "task_loop",
                status="running",
                assigned_worker="claude-code",
                allocation_id=plan.allocation_id,
            )
            first_attempt = WorkerAttemptResult(
                allocation_id=plan.allocation_id,
                worker_id="claude-code",
                route="worker-router claude",
                status="empty_output",
                duration_seconds=20,
                error_signature="worker-router claude empty output",
                started_at=1_000,
            )
            second_attempt = WorkerAttemptResult(
                allocation_id=plan.allocation_id,
                worker_id="claude-code",
                route="worker-router claude",
                status="timed_out",
                duration_seconds=20,
                error_signature="worker-router claude timeout",
                started_at=1_001,
            )
            save_worker_attempt(db, first_attempt)
            save_worker_attempt(db, second_attempt)
            primary_health = update_worker_health_from_attempt(
                WorkerHealth(worker_id="claude-code"),
                first_attempt,
                cooldown_seconds=plan.cooldown_seconds,
                now=1_000,
            )
            save_worker_health(db, primary_health)
            decision = choose_next_worker(plan, [first_attempt], {"claude-code": primary_health}, now=1_001)
            first_health = run_health_check_once(
                db,
                now=2_000,
                heartbeat_timeout_seconds=30,
                max_actions=8,
                foreground_blocking_callback=lambda: None,
            )
            second_health = run_health_check_once(db, now=2_000, heartbeat_timeout_seconds=30, max_actions=8)
            same_worker_retry_count = 1 if decision.worker_id == "claude-code" else 0
            repeated_result = {
                "status": "passed"
                if decision.action in {"dispatch", "pause"}
                and decision.worker_id != "claude-code"
                and same_worker_retry_count == 0
                and second_health["recovery_candidates"] == 0
                else "failed",
                "decision": decision.to_dict(),
                "primary_worker": "claude-code",
                "same_worker_retry_count": same_worker_retry_count,
                "primary_failed_attempts_recorded": 2,
                "cooldown_until": load_worker_health(db, "claude-code").cooldown_until if load_worker_health(db, "claude-code") else 0,
                "first_health_check_actions": len(first_health["actions"]),
                "second_health_check_recovery_candidates": second_health["recovery_candidates"],
            }

            foreground_called = {"health": False, "progress": False}
            start = time.monotonic()
            health_payload = run_health_check_once(
                db,
                now=2_100,
                heartbeat_timeout_seconds=30,
                max_actions=4,
                foreground_blocking_callback=lambda: foreground_called.__setitem__("health", True),
            )
            run_worker_with_progress_events(
                db,
                task_id="task_stream",
                allocation_id="alloc_stream",
                attempt_id="attempt_stream",
                worker_id="codex",
                repo_id="repo-smoke",
                branch=branch_ref,
                worker_run=lambda: {
                    "status": "running",
                    "summary": "edited smoke files",
                    "stdout_ref": "log://stdout/smoke",
                    "artifact_refs": ["git://diff/smoke"],
                },
                now=2_101,
            )
            progress_payload = run_progress_summarizer_sidecar(
                db,
                task_id="task_stream",
                allocation_id="alloc_stream",
                low_cost_summarizer=lambda events, budget: "bounded progress from event refs",
                foreground_blocking_callback=lambda: foreground_called.__setitem__("progress", True),
                timeout_seconds=0.25,
                budget_tokens=128,
                max_chars=120,
                now=2_102,
            )
            elapsed = time.monotonic() - start
            foreground_result = {
                "status": "passed"
                if not foreground_called["health"]
                and not foreground_called["progress"]
                and elapsed < 0.5
                and progress_payload["authorities"]["complete_tasks"] is False
                and progress_payload["authorities"]["mutate_routing"] is False
                else "failed",
                "elapsed_seconds": elapsed,
                "health_foreground_callback_called": foreground_called["health"],
                "progress_foreground_callback_called": foreground_called["progress"],
                "health_actions": len(health_payload["actions"]),
                "progress_sidecar_status": progress_payload["status"],
                "progress_sidecar_authorities": progress_payload["authorities"],
            }

            for task_id, worker_id, allocation_id, status in [
                ("task_resume", "codex", "alloc_resume", "assigned"),
                ("task_unknown", "deepseek", "alloc_unknown", "running"),
                ("task_cooling", "claude-code", "alloc_cooling", "assigned"),
            ]:
                save_allocation_plan(
                    db,
                    WorkerAllocationPlan(
                        task_id=task_id,
                        session_id="smoke_session",
                        objective=f"restart {task_id}",
                        candidate_workers=[worker_id, "codex"] if worker_id != "codex" else ["codex"],
                        primary_worker=worker_id,
                        allocation_id=allocation_id,
                    ),
                )
                update_task_node(
                    db,
                    "smoke_graph",
                    task_id,
                    status=status,
                    assigned_worker=worker_id,
                    allocation_id=allocation_id,
                )
            save_worker_health(db, WorkerHealth(worker_id="claude-code", cooldown_until=5_000))
            record_runtime_lease(db, lease_id="sidecar_smoke", owner="health", expires_at=2_500, status="active")
            expensive_called = {"called": False}
            restart_payload = run_restart_recovery(
                db,
                now=3_000,
                expensive_sidecar=lambda: expensive_called.__setitem__("called", True),
            )
            decisions = {item["task_id"]: item for item in restart_payload["decisions"]}
            cooldown = load_worker_health(db, "claude-code")
            restart_result = {
                "status": "passed"
                if not expensive_called["called"]
                and decisions["task_resume"]["decision"] == "resume"
                and decisions["task_unknown"]["decision"] == "request_status"
                and decisions["task_cooling"]["decision"] == "pause"
                and cooldown is not None
                and cooldown.cooldown_until == 5_000
                and decisions["task_unknown"]["safe_to_dispatch"] is False
                else "failed",
                "expensive_sidecar_called": expensive_called["called"],
                "decisions": decisions,
                "cooldown_preserved_until": cooldown.cooldown_until if cooldown else 0,
                "unknown_in_flight_safe_to_dispatch": decisions["task_unknown"]["safe_to_dispatch"],
                "stale_sidecar_leases": restart_payload["stale_sidecar_leases"],
            }

            projection = project_worker_progress_for_delivery(db, task_id="task_stream", channel="smoke")
            stream_events = [event for event in list_worker_progress_events(db, task_id="task_stream") if event["event_type"] == "worker_stream_ref"]
            raw_context = "raw stdout" in str(projection["supervisor_context_packets"]).lower() or "log://stdout/smoke" in str(
                projection["supervisor_context_packets"]
            )
            raw_result = {
                "status": "passed"
                if stream_events
                and stream_events[0]["store_only"] is True
                and projection["supervisor_context_appended"] is False
                and raw_context is False
                else "failed",
                "stream_event_store_only": stream_events[0]["store_only"] if stream_events else False,
                "supervisor_context_appended": projection["supervisor_context_appended"],
                "raw_stream_in_supervisor_context": raw_context,
                "context_packet_count": len(projection["supervisor_context_packets"]),
            }
            return {
                "repeated_failed_loop_result": repeated_result,
                "foreground_responsiveness_result": foreground_result,
                "restart_resume_result": restart_result,
                "raw_worker_streams_result": raw_result,
            }
        finally:
            db.close()


def run_allocator_comparison_smoke(
    *,
    repo_path: str = ".",
    branch_ref: str = "HEAD",
    upstream_ref: Optional[str] = "origin/main",
) -> RuntimeSmokeResult:
    repo = Path(repo_path).resolve()
    plan = WorkerAllocationPlan(
        task_id="smoke_task",
        session_id="smoke_session",
        objective="prove degraded primary worker falls back deterministically",
        candidate_workers=["claude-code", "codex", "deepseek"],
        primary_worker="claude-code",
        fallback_order=["codex", "deepseek"],
        latency_budget_seconds=90,
        per_worker_timeout_seconds=20,
        max_attempts=3,
        retry_same_worker=0,
    )
    failed_attempt = WorkerAttemptResult(
        allocation_id=plan.allocation_id,
        worker_id="claude-code",
        route="worker-router claude",
        status="empty_output",
        duration_seconds=20,
        error_signature="worker-router claude empty output",
    )
    health = update_worker_health_from_attempt(
        WorkerHealth(worker_id="claude-code"),
        failed_attempt,
        cooldown_seconds=plan.cooldown_seconds,
        now=1000,
    )
    decision = choose_next_worker(
        plan,
        [failed_attempt],
        {"claude-code": health},
        now=1001,
    )
    notes = [
        "This smoke is deterministic and does not call live workers.",
        "Upstream is comparison-only; branch-owned runtime logic supplies the smoke result.",
    ]
    branch_capabilities = _capabilities(repo, branch_ref)
    upstream_capabilities = _capabilities(repo, upstream_ref) if upstream_ref else {}
    scenario_results = _run_branch_owned_runtime_scenarios(branch_ref)
    status = (
        "passed"
        if decision.action == "dispatch"
        and decision.worker_id == "codex"
        and all(result["status"] == "passed" for result in scenario_results.values())
        else "failed"
    )
    return RuntimeSmokeResult(
        status=status,
        scenario="phase_13_self_healing_runtime_smoke",
        branch_ref=branch_ref,
        upstream_ref=upstream_ref,
        branch_capabilities=branch_capabilities,
        upstream_capabilities=upstream_capabilities,
        allocator_decision=decision.to_dict(),
        repeated_failed_loop_result=scenario_results["repeated_failed_loop_result"],
        foreground_responsiveness_result=scenario_results["foreground_responsiveness_result"],
        restart_resume_result=scenario_results["restart_resume_result"],
        raw_worker_streams_result=scenario_results["raw_worker_streams_result"],
        notes=notes,
    )
