"""Scripted runtime smoke helpers for allocator/degradation value checks."""

from __future__ import annotations

import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from hermes_cli.goal_allocator import (
    WorkerAllocationPlan,
    WorkerAttemptResult,
    choose_next_worker,
    update_worker_health_from_attempt,
    WorkerHealth,
)


@dataclass
class RuntimeSmokeResult:
    status: str
    scenario: str
    branch_ref: str
    upstream_ref: Optional[str]
    branch_capabilities: Dict[str, Any]
    upstream_capabilities: Dict[str, Any]
    allocator_decision: Dict[str, Any]
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
        "A live VM smoke should follow after allocator is wired into supervisor delegation.",
    ]
    branch_capabilities = _capabilities(repo, branch_ref)
    upstream_capabilities = _capabilities(repo, upstream_ref) if upstream_ref else {}
    status = "passed" if decision.action == "dispatch" and decision.worker_id == "codex" else "failed"
    return RuntimeSmokeResult(
        status=status,
        scenario="empty primary worker -> fallback worker",
        branch_ref=branch_ref,
        upstream_ref=upstream_ref,
        branch_capabilities=branch_capabilities,
        upstream_capabilities=upstream_capabilities,
        allocator_decision=decision.to_dict(),
        notes=notes,
    )
