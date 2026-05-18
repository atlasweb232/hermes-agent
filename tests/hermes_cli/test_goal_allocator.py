import pytest

from hermes_cli.goal_allocator import (
    AllocationDecision,
    WorkerAllocationPlan,
    WorkerAttemptResult,
    WorkerHealth,
    choose_next_worker,
    load_allocation_plan,
    load_worker_health,
    save_allocation_plan,
    save_worker_health,
    update_worker_health_from_attempt,
)
from hermes_state import SessionDB


def _db(tmp_path):
    return SessionDB(db_path=tmp_path / "state.db")


def _plan(**overrides):
    data = {
        "task_id": "task_1",
        "session_id": "session_1",
        "objective": "run bounded worker task",
        "candidate_workers": ["claude-code", "codex", "deepseek"],
        "primary_worker": "claude-code",
        "fallback_order": ["codex", "deepseek"],
        "memory_packet_id": "mempkt_1",
        "latency_budget_seconds": 90,
        "per_worker_timeout_seconds": 20,
        "max_attempts": 3,
        "retry_same_worker": 0,
        "cooldown_seconds": 300,
        "retry_after_seconds": 120,
        "validation_required": True,
    }
    data.update(overrides)
    return WorkerAllocationPlan(**data)


def _attempt(plan, worker_id="claude-code", status="timed_out", **overrides):
    data = {
        "allocation_id": plan.allocation_id,
        "worker_id": worker_id,
        "route": f"worker-router {worker_id}",
        "status": status,
        "duration_seconds": 20,
        "error_signature": f"{worker_id}:{status}",
        "validation_status": "skipped",
        "fallback_allowed": True,
    }
    data.update(overrides)
    return WorkerAttemptResult(**data)


def test_worker_allocation_plan_validates_required_fields_and_status():
    plan = _plan()

    assert plan.goal_key == "goal:session_1"
    assert plan.worker_order == ["claude-code", "codex", "deepseek"]

    with pytest.raises(ValueError, match="latency_budget_seconds"):
        _plan(latency_budget_seconds=0)
    with pytest.raises(ValueError, match="primary_worker"):
        _plan(primary_worker="missing")
    with pytest.raises(ValueError, match="validation_required"):
        _plan(validation_required="yes")
    with pytest.raises(ValueError, match="invalid allocation status"):
        _plan(status="unknown")


def test_worker_attempt_result_validates_status_and_fallback_type():
    plan = _plan()
    attempt = _attempt(plan, status="empty_output")

    assert attempt.status == "empty_output"

    with pytest.raises(ValueError, match="invalid attempt status"):
        _attempt(plan, status="mystery")
    with pytest.raises(ValueError, match="fallback_allowed"):
        _attempt(plan, fallback_allowed="yes")
    with pytest.raises(ValueError, match="invalid validation status"):
        _attempt(plan, validation_status="maybe")


def test_worker_health_validates_and_tracks_availability():
    health = WorkerHealth(worker_id="claude-code", cooldown_until=200, confidence=0.5)

    assert health.is_available(now=100) is False
    assert health.is_available(now=250) is True

    with pytest.raises(ValueError, match="worker_id"):
        WorkerHealth(worker_id="")
    with pytest.raises(ValueError, match="confidence"):
        WorkerHealth(worker_id="codex", confidence=1.5)


def test_allocation_plan_and_worker_health_persist_to_state_meta(tmp_path):
    db = _db(tmp_path)
    try:
        plan = _plan()
        health = WorkerHealth(worker_id="claude-code", provider="anthropic")

        save_allocation_plan(db, plan)
        save_worker_health(db, health)

        loaded_plan = load_allocation_plan(db, "session_1", "task_1")
        loaded_health = load_worker_health(db, "claude-code")

        assert loaded_plan is not None
        assert loaded_plan.allocation_id == plan.allocation_id
        assert loaded_plan.memory_packet_id == "mempkt_1"
        assert loaded_health is not None
        assert loaded_health.provider == "anthropic"
    finally:
        db.close()


def test_choose_next_worker_selects_primary_before_attempts():
    plan = _plan()

    decision = choose_next_worker(plan, [], now=100)

    assert decision == AllocationDecision(
        action="dispatch",
        worker_id="claude-code",
        reason="worker selected",
        remaining_latency_budget_seconds=90,
        attempts_used=0,
    )


def test_choose_next_worker_falls_back_after_degraded_primary():
    plan = _plan()
    attempts = [_attempt(plan, worker_id="claude-code", status="empty_output")]

    decision = choose_next_worker(plan, attempts, now=100)

    assert decision.action == "dispatch"
    assert decision.worker_id == "codex"
    assert decision.attempts_used == 1


def test_choose_next_worker_suppresses_repeated_same_route():
    plan = _plan(retry_same_worker=0)
    attempts = [_attempt(plan, worker_id="claude-code", status="timed_out")]

    decision = choose_next_worker(plan, attempts, now=100)

    assert decision.worker_id == "codex"


def test_choose_next_worker_honors_worker_cooldown():
    plan = _plan()
    health = {
        "claude-code": WorkerHealth(worker_id="claude-code", cooldown_until=500),
    }

    decision = choose_next_worker(plan, [], health, now=100)

    assert decision.action == "dispatch"
    assert decision.worker_id == "codex"


def test_choose_next_worker_pauses_when_all_workers_unhealthy():
    plan = _plan()
    health = {
        "claude-code": WorkerHealth(worker_id="claude-code", cooldown_until=400),
        "codex": WorkerHealth(worker_id="codex", cooldown_until=300),
        "deepseek": WorkerHealth(worker_id="deepseek", cooldown_until=350),
    }

    decision = choose_next_worker(plan, [], health, now=100)

    assert decision.action == "pause"
    assert decision.reason == "no healthy fallback worker available"
    assert decision.retry_after_seconds == 200


def test_choose_next_worker_pauses_on_attempt_and_latency_budget():
    plan = _plan(max_attempts=1)
    attempts = [_attempt(plan, worker_id="claude-code", status="timed_out")]

    decision = choose_next_worker(plan, attempts, now=100)

    assert decision.action == "pause"
    assert decision.reason == "max attempts exhausted"

    budget_plan = _plan(latency_budget_seconds=30, per_worker_timeout_seconds=20, max_attempts=3)
    budget_attempts = [_attempt(budget_plan, duration_seconds=15)]

    budget_decision = choose_next_worker(budget_plan, budget_attempts, now=100)

    assert budget_decision.action == "pause"
    assert budget_decision.reason == "latency budget exhausted"


def test_update_worker_health_from_attempt_sets_counters_and_cooldowns():
    health = WorkerHealth(worker_id="claude-code", confidence=0.8)
    attempt = WorkerAttemptResult(
        allocation_id="alloc_1",
        worker_id="claude-code",
        route="worker-router claude",
        status="network_degraded",
        error_signature="network timeout",
    )

    updated = update_worker_health_from_attempt(
        health,
        attempt,
        cooldown_seconds=300,
        now=1000,
    )

    assert updated.failure_count == 1
    assert updated.network_degraded_until == 1300
    assert updated.last_error_signature == "network timeout"
    assert updated.confidence < 0.8
    degraded_confidence = updated.confidence

    success = WorkerAttemptResult(
        allocation_id="alloc_1",
        worker_id="claude-code",
        route="claude",
        status="success",
    )
    after_success = update_worker_health_from_attempt(updated, success, cooldown_seconds=300, now=1400)

    assert after_success.last_success_at == 1400
    assert after_success.confidence > degraded_confidence
