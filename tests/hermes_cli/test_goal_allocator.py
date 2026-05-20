import json

import pytest

from hermes_cli.goal_allocator import (
    AllocationDecision,
    WorkerAllocationPlan,
    WorkerAttemptResult,
    WorkerHealth,
    choose_next_worker,
    load_allocation_runtime_advisory_packet,
    load_allocation_plan,
    load_worker_health,
    list_allocation_plans,
    list_worker_attempts,
    list_worker_health_records,
    allocation_status_payload,
    record_worker_attempt,
    resume_allocation_status_payload,
    save_allocation_plan,
    save_worker_health,
    save_worker_attempt,
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


def test_worker_attempts_persist_and_status_payload_explains_next_decision(tmp_path):
    db = _db(tmp_path)
    try:
        plan = _plan()
        save_allocation_plan(db, plan)
        attempt = _attempt(plan, worker_id="claude-code", status="empty_output")
        save_worker_attempt(db, attempt)

        attempts = list_worker_attempts(db, plan.allocation_id)
        payload = allocation_status_payload(db, plan, now=100)

        assert attempts[0].status == "empty_output"
        assert payload["plan"]["allocation_id"] == plan.allocation_id
        assert payload["attempts"][0]["worker_id"] == "claude-code"
        assert payload["decision"]["action"] == "dispatch"
        assert payload["decision"]["worker_id"] == "codex"
    finally:
        db.close()


def test_resume_allocation_status_payload_recovers_state_and_skips_unhealthy_primary(tmp_path):
    db = _db(tmp_path)
    try:
        plan = _plan(allocation_id="alloc_resume_1")
        save_allocation_plan(db, plan)
        save_worker_health(
            db,
            WorkerHealth(
                worker_id="claude-code",
                provider="anthropic",
                cooldown_until=500,
                failure_count=1,
                last_error_signature="timeout",
            ),
        )

        payload = resume_allocation_status_payload(db, "session_1", "task_1", now=100)

        assert payload["recovered"] is True
        assert payload["state_key"] == "allocation:session_1:task_1"
        assert payload["recovered_from"] == "SessionDB.state_meta"
        assert payload["session_id"] == "session_1"
        assert payload["task_id"] == "task_1"
        assert payload["allocation_id"] == "alloc_resume_1"
        assert payload["plan"]["allocation_id"] == "alloc_resume_1"
        assert payload["worker_health"]["claude-code"]["cooldown_until"] == 500
        assert payload["decision"]["action"] == "dispatch"
        assert payload["decision"]["worker_id"] == "codex"
        assert payload["decision"]["skipped_workers"] == [
            {
                "worker_id": "claude-code",
                "unavailable_until": 500,
                "retry_after_seconds": 400,
            }
        ]

        resumed_after_cooldown = resume_allocation_status_payload(db, "session_1", "task_1", now=501)

        assert resumed_after_cooldown["recovered"] is True
        assert resumed_after_cooldown["decision"]["action"] == "dispatch"
        assert resumed_after_cooldown["decision"]["worker_id"] == "claude-code"
        assert resumed_after_cooldown["decision"]["skipped_workers"] == []
    finally:
        db.close()


def test_list_allocation_plans_and_worker_health_records(tmp_path):
    db = _db(tmp_path)
    try:
        first = _plan(task_id="task_1", allocation_id="alloc_1")
        second = _plan(task_id="task_2", allocation_id="alloc_2", status="paused")
        save_allocation_plan(db, first)
        save_allocation_plan(db, second)
        save_worker_health(db, WorkerHealth(worker_id="claude-code", cooldown_until=200))

        assert [plan.task_id for plan in list_allocation_plans(db, status="paused")] == ["task_2"]
        assert list_allocation_plans(db, task_id="task_1")[0].allocation_id == "alloc_1"
        assert list_worker_health_records(db)[0].worker_id == "claude-code"
    finally:
        db.close()


def test_record_worker_attempt_updates_health_and_attempt_store(tmp_path):
    db = _db(tmp_path)
    try:
        plan = _plan(cooldown_seconds=60)
        save_allocation_plan(db, plan)
        attempt = _attempt(plan, status="timed_out", duration_seconds=20)

        health = record_worker_attempt(db, plan, attempt, now=100)

        assert health.timeout_count == 1
        assert health.cooldown_until == 160
        assert list_worker_attempts(db, plan.allocation_id)[0].attempt_id == attempt.attempt_id
        assert load_worker_health(db, "claude-code").timeout_count == 1
    finally:
        db.close()


def test_record_worker_attempt_captures_runtime_failure_before_sidecars(tmp_path):
    db = _db(tmp_path)
    try:
        plan = _plan(task_id="task_148", allocation_id="alloc_148")
        save_allocation_plan(db, plan)
        attempt = _attempt(
            plan,
            worker_id="claude-code",
            route="worker-router claude-code",
            status="empty_output",
            stdout_excerpt="token=sk-abc123456789XYZ\n" + "verbose worker log\n" * 200,
            validation_status="failed",
            error_signature="claimed_done_no_files",
            artifact_refs=["hermes:allocation:alloc_148:attempt_1"],
        )

        record_worker_attempt(db, plan, attempt, now=100)

        records = db.list_memory_records(kind="supervisor_runtime_failure", limit=1)
        assert len(records) == 1
        payload = records[0]["payload_json"]
        assert records[0]["task_id"] == "task_148"
        assert payload["task_id"] == "task_148"
        assert payload["worker_id"] == "claude-code"
        assert payload["route"] == "worker-router claude-code"
        assert payload["command_family"] == "worker-router"
        assert payload["status"] == "empty_output"
        assert payload["evidence_refs"] == ["hermes:allocation:alloc_148:attempt_1"]
        assert payload["validation_mismatch"]["validation_status"] == "failed"
        assert payload["validation_mismatch"]["error_signature"] == "claimed_done_no_files"
        assert payload["requires_judge"] is True
        assert payload["operator_approval_required"] is True
        serialized = json.dumps(payload)
        assert "sk-abc" not in serialized
        assert len(payload["output_excerpt"]) < 900
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


def test_allocator_loads_runtime_advisory_packet_without_changing_budgets(tmp_path):
    db = _db(tmp_path)
    try:
        plan = _plan(
            tenant_id="atlas",
            repo_id="hermes-agent",
            task_id="task-runtime",
            candidate_workers=["codex", "claude-code"],
            primary_worker="codex",
            fallback_order=["claude-code"],
            retry_same_worker=0,
            max_attempts=2,
            latency_budget_seconds=35,
            per_worker_timeout_seconds=20,
        )
        db.upsert_meta_candidate(
            candidate_id="metacand_timeout",
            kind="worker_health_rule",
            claim="Advisory timeout recovery for codex",
            evidence_json={
                "policy_type": "supervisor_runtime_failure_advisory",
                "mode": "advisory",
                "failure_classifications": ["timeout"],
                "payload": {
                    "tenant_id": "atlas",
                    "repo_id": "hermes-agent",
                    "task_id": "task-runtime",
                    "worker_id": "codex",
                    "route": "delegate_task:codex",
                    "command_family": "delegate_task",
                    "status": "timed_out",
                },
                "approved_for_enforcement": False,
            },
            score=0.9,
            status="approved",
            tenant_id="atlas",
            repo_id="hermes-agent",
        )
        attempts = [_attempt(plan, worker_id="codex", status="timed_out", duration_seconds=16)]
        packet = load_allocation_runtime_advisory_packet(db, plan, worker_id="codex")

        decision = choose_next_worker(plan, attempts, advisory_packet=packet, now=100)

        assert packet["count"] == 1
        assert decision.action == "pause"
        assert decision.reason == "latency budget exhausted"
        assert decision.attempts_used == 1
        assert decision.remaining_latency_budget_seconds == 19
    finally:
        db.close()


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
