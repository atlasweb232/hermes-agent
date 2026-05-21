import json

from hermes_cli.azure_deployment import default_azure_profile, decide_deployment_action
from hermes_cli.platform_hardening import (
    ApprovalLedger,
    BudgetLimit,
    BudgetUsage,
    CanonicalBusEnvelope,
    DreamingBacklogPolicy,
    MemoryQualityRecord,
    SidecarBudgetRequest,
    WorkerContextGatePolicy,
    compact_memory_quality_records,
    create_bus_envelope,
    dead_letter_event,
    evaluate_azure_production_hardening,
    evaluate_sidecar_budget,
    inspect_worker_context_gates,
    redrive_event,
    resolve_effective_runtime_profile,
    run_platform_hardening_e2e_fixture,
    summarize_dreaming_backlog,
)


def test_t310_shared_approval_ledger_binds_expires_single_use_and_audits():
    ledger = ApprovalLedger()
    actions = [
        "memory.promote",
        "dreaming.convert",
        "deployment.apply",
        "deployment.promote",
        "deployment.destroy",
        "corpus.remit",
        "policy.enforce",
        "cicd.protected_action",
    ]
    approvals = [
        ledger.record(
            actor_id="operator-1",
            actor_role="tenant-admin",
            tenant_id="tenant-a",
            scope="production",
            action=action,
            target_ref=f"target://{index}",
            target_hash=f"hash-{index}",
            approval_channel="cli",
            audit_refs=[f"audit://{index}"],
            created_at=100.0,
            expires_at=200.0,
        )
        for index, action in enumerate(actions)
    ]

    for index, approval in enumerate(approvals):
        wrong_hash = ledger.consume(
            approval.approval_id,
            actor_id="operator-1",
            actor_role="tenant-admin",
            tenant_id="tenant-a",
            action=approval.action,
            target_hash="wrong-hash",
            now=110.0,
        )
        assert wrong_hash.allowed is False
        assert wrong_hash.reason == "target_hash_mismatch"

        accepted = ledger.consume(
            approval.approval_id,
            actor_id="operator-1",
            actor_role="tenant-admin",
            tenant_id="tenant-a",
            action=approval.action,
            target_hash=f"hash-{index}",
            now=110.0,
        )
        assert accepted.allowed is True
        assert accepted.audit_ref == f"audit://approval/{approval.approval_id}/consume"

        replay = ledger.consume(
            approval.approval_id,
            actor_id="operator-1",
            actor_role="tenant-admin",
            tenant_id="tenant-a",
            action=approval.action,
            target_hash=f"hash-{index}",
            now=111.0,
        )
        assert replay.allowed is False
        assert replay.reason == "approval_already_consumed"

    expired = ledger.record(
        actor_id="operator-1",
        actor_role="tenant-admin",
        tenant_id="tenant-a",
        scope="production",
        action="deployment.apply",
        target_ref="target://expired",
        target_hash="expired-hash",
        approval_channel="cli",
        audit_refs=["audit://expired"],
        created_at=100.0,
        expires_at=101.0,
    )
    assert ledger.consume(
        expired.approval_id,
        actor_id="operator-1",
        actor_role="tenant-admin",
        tenant_id="tenant-a",
        action="deployment.apply",
        target_hash="expired-hash",
        now=102.0,
    ).reason == "approval_expired"

    payload = json.dumps(ledger.inspect_json())
    assert "target://0" not in payload
    assert "target_ref_hash" in payload
    assert "raw" not in payload.lower()


def test_t311_effective_runtime_profile_merges_inputs_into_read_only_explained_view():
    profile = resolve_effective_runtime_profile(
        tenant_id="tenant-a",
        repo_id="repo-a",
        feature_toggles={"runtime.health_sidecar": True, "dreaming": False},
        sidecar_tiers={"judge": "cheap", "dreaming": "disabled"},
        tenant_policy={"max_daily_cost": 10, "deployment_allowed": True},
        repo_policy={"protected_branch": True, "deployment_allowed": False},
        toolset_profile={"enabled": ["terminal", "patch"], "disabled": ["browser"]},
        deployment_profile={"environment": "production", "live_apply": False},
        worker_health={"codex": "healthy", "claude": "degraded"},
        budgets={"tenant_remaining_cost": 3.5, "task_remaining_tokens": 1000},
        memory_retrieval_mode="approved_only",
    )

    data = profile.to_dict()
    assert data["read_only"] is True
    assert data["decisions"]["deployment_allowed"]["enabled"] is False
    assert "repo_policy" in data["decisions"]["deployment_allowed"]["explanation"]
    assert data["decisions"]["sidecar.dreaming"]["enabled"] is False
    assert data["toolset_profile"]["enabled"] == ["terminal", "patch"]
    assert data["memory_retrieval_mode"] == "approved_only"
    assert data["worker_health"]["claude"] == "degraded"
    assert profile.with_update(feature_toggles={"dreaming": True}).to_dict()["feature_toggles"]["dreaming"] is False


def test_t312_canonical_bus_envelope_redrive_dlq_and_consumer_idempotency():
    sqlite_event = create_bus_envelope(
        event_type="memory.promoted",
        tenant_id="tenant-a",
        repo_id="repo-a",
        source_subsystem="memory",
        payload={"ref": "memory://1"},
        idempotency_key="memory:1",
        partition_key="tenant-a",
        adapter="sqlite",
        created_at=100.0,
    )
    kafka_event = create_bus_envelope(
        event_type="memory.promoted",
        tenant_id="tenant-a",
        repo_id="repo-a",
        source_subsystem="memory",
        payload_ref="blob://bounded/1",
        idempotency_key="memory:1",
        partition_key="tenant-a",
        adapter="kafka",
        created_at=100.0,
    )

    for event in (sqlite_event, kafka_event):
        assert event.event_id
        assert event.idempotency_key == "memory:1"
        assert event.redaction_state == "redacted"
        assert event.replay_attempt == 0
        assert event.consumer_key("consumer-a") == f"consumer-a:{event.event_id}:memory:1"

    redriven = redrive_event(sqlite_event, reason="lease_expired")
    assert redriven.replay_attempt == 1
    assert redriven.dead_letter_reason is None
    dead = dead_letter_event(redriven, reason="max_attempts_exceeded")
    assert dead.dead_letter_reason == "max_attempts_exceeded"
    assert CanonicalBusEnvelope.from_dict(dead.to_dict()).consumer_key("consumer-a") == dead.consumer_key("consumer-a")


def test_t313_sidecar_budget_governor_denies_or_degrades_llm_but_allows_exact_memory_hits():
    limits = BudgetLimit(tenant_cost=5, task_cost=2, daily_cost=10, tenant_tokens=1000, task_tokens=500)
    usage = BudgetUsage(tenant_cost=4.75, task_cost=1.5, daily_cost=8, tenant_tokens=950, task_tokens=450)

    denied = evaluate_sidecar_budget(
        SidecarBudgetRequest(
            tenant_id="tenant-a",
            task_id="task-a",
            sidecar_role="judge",
            llm_backed=True,
            estimated_tokens=100,
            estimated_cost=1.0,
            escalation_reason="quality_check",
        ),
        limits=limits,
        usage=usage,
    )
    assert denied.allowed is False
    assert denied.status == "skipped"
    assert "tenant_cost" in denied.reasons
    assert denied.foreground_blocking is False

    degraded = evaluate_sidecar_budget(
        SidecarBudgetRequest(
            tenant_id="tenant-a",
            task_id="task-a",
            sidecar_role="dreaming",
            llm_backed=True,
            estimated_tokens=60,
            estimated_cost=0.1,
            escalation_reason="proposal",
            degrade_tier="programmatic_summary",
        ),
        limits=limits,
        usage=usage,
    )
    assert degraded.allowed is False
    assert degraded.status == "degraded"
    assert degraded.degraded_to == "programmatic_summary"

    exact_hit = evaluate_sidecar_budget(
        SidecarBudgetRequest(
            tenant_id="tenant-a",
            task_id="task-a",
            sidecar_role="memory_lookup",
            llm_backed=False,
            exact_memory_hit=True,
            estimated_tokens=0,
            estimated_cost=0,
            escalation_reason="exact_memory_hit",
        ),
        limits=limits,
        usage=usage,
    )
    assert exact_hit.allowed is True
    assert exact_hit.status == "allowed_programmatic"


def test_t314_worker_context_gate_checks_all_worker_families_for_raw_stream_leaks():
    wrappers = {
        "claude": {"typed_events": True, "final_packet": True, "raw_stdout": False, "raw_stderr": False},
        "codex": {"typed_events": True, "final_packet": True, "watch_tail": False, "log_tail": False},
        "deepseek": {"typed_events": True, "final_packet": True, "raw_stdout": False},
        "browser_tinyfish": {"typed_events": True, "final_packet": True, "terminal_tail": False},
        "generic": {"typed_events": True, "final_packet": True, "raw_logs": False},
    }
    report = inspect_worker_context_gates(wrappers, policy=WorkerContextGatePolicy.default())
    assert report.compliant is True
    assert set(report.checked_families) == {"claude", "codex", "deepseek", "browser_tinyfish", "generic"}

    leaking = {**wrappers, "codex": {**wrappers["codex"], "raw_stdout": True}}
    blocked = inspect_worker_context_gates(leaking, policy=WorkerContextGatePolicy.default())
    assert blocked.compliant is False
    assert blocked.fail_closed is True
    assert blocked.violations[0]["family"] == "codex"
    assert blocked.violations[0]["field"] == "raw_stdout"


def test_t315_memory_quality_lifecycle_demotes_suppresses_retires_compacts_and_preserves_audit():
    records = [
        MemoryQualityRecord(
            memory_id="fresh",
            tenant_id="tenant-a",
            repo_id="repo-a",
            scope="tenant",
            confidence=0.8,
            updated_at=95.0,
            audit_history=["audit://fresh/created"],
            feedback=["helpful"],
        ),
        MemoryQualityRecord(
            memory_id="stale",
            tenant_id="tenant-a",
            repo_id="repo-a",
            scope="tenant",
            confidence=0.6,
            updated_at=10.0,
            audit_history=["audit://stale/created"],
            feedback=["ignored", "harmful"],
        ),
    ]
    result = compact_memory_quality_records(records, now=100.0, stale_after_seconds=50, retire_below=0.35)
    fresh = result.records["fresh"]
    stale = result.records["stale"]
    assert fresh.confidence > 0.8
    assert stale.suppressed is True
    assert stale.retired is True
    assert stale.confidence < 0.35
    assert result.compacted_count == 1
    assert "audit://stale/created" in stale.audit_history
    assert any(ref.startswith("audit://memory/stale/") for ref in stale.audit_history)


def test_t316_dreaming_backlog_controls_quota_dedupe_age_and_summary():
    proposals = [
        {"proposal_id": "p1", "tenant_id": "tenant-a", "proposal_type": "test_gap", "risk": "low", "signature": "same", "created_at": 30.0},
        {"proposal_id": "p2", "tenant_id": "tenant-a", "proposal_type": "test_gap", "risk": "low", "signature": "same", "created_at": 35.0},
        {"proposal_id": "p3", "tenant_id": "tenant-a", "proposal_type": "ci_cd_hardening", "risk": "high", "signature": "unique-3", "created_at": 40.0},
        {"proposal_id": "p4", "tenant_id": "tenant-a", "proposal_type": "ci_cd_hardening", "risk": "high", "signature": "unique-4", "created_at": 50.0},
        {"proposal_id": "p5", "tenant_id": "tenant-a", "proposal_type": "routing", "risk": "medium", "signature": "old", "created_at": 1.0},
    ]
    summary = summarize_dreaming_backlog(
        proposals,
        policy=DreamingBacklogPolicy(
            tenant_quota=3,
            proposal_type_quota={"test_gap": 1, "ci_cd_hardening": 1},
            risk_quota={"high": 1},
            max_age_seconds=80,
        ),
        now=100.0,
    )
    assert summary.visible_count == 2
    assert summary.archived_count == 1
    assert summary.duplicate_count == 1
    assert summary.quota_blocked_count == 1
    assert summary.by_tenant["tenant-a"]["visible"] == 2
    assert summary.operator_summary["fail_closed"] is True


def test_t317_azure_hardening_blocks_live_production_without_every_required_control():
    missing = evaluate_azure_production_hardening(
        {
            "managed_identity": True,
            "rbac": True,
            "private_endpoints": False,
            "vnet_integration": True,
            "ingress": "frontdoor_private",
            "diagnostics": True,
            "storage_lifecycle_policy": True,
            "key_vault_access": True,
            "rollback_artifacts": True,
            "explicit_approval": True,
        }
    )
    assert missing.allowed is False
    assert missing.fail_closed is True
    assert "private_endpoints" in missing.blockers

    profile = default_azure_profile("production")
    blocked = decide_deployment_action(
        profile,
        action="apply",
        approval={"approved": True, "approval_id": "approval-1"},
        live=True,
        hardening_evidence=missing.to_dict(),
    )
    assert blocked.allowed is False
    assert blocked.reason == "azure_production_hardening_blocked"

    valid = evaluate_azure_production_hardening(
        {
            "managed_identity": True,
            "rbac": True,
            "private_endpoints": True,
            "vnet_integration": True,
            "ingress": "frontdoor_private",
            "diagnostics": True,
            "storage_lifecycle_policy": True,
            "key_vault_access": True,
            "rollback_artifacts": True,
            "explicit_approval": True,
        }
    )
    assert valid.allowed is True
    promoted = decide_deployment_action(
        profile,
        action="promote",
        approval={"approved": True, "approval_id": "approval-2"},
        live=True,
        hardening_evidence=valid.to_dict(),
    )
    assert promoted.allowed is False
    assert promoted.status == "blocked"
    assert promoted.reason == "live_promote_not_implemented"


def test_t326_e2e_hardening_fixture_fails_closed_without_foreground_blocking():
    fixture = run_platform_hardening_e2e_fixture()
    sections = fixture["sections"]
    assert fixture["read_only"] is True
    assert sections["approval"]["allowed"] is False
    assert sections["budget"]["status"] == "skipped"
    assert sections["context_gate"]["compliant"] is False
    assert sections["memory"]["retired_count"] == 1
    assert sections["dreaming"]["quota_blocked_count"] == 1
    assert sections["azure"]["allowed"] is False
    assert sections["foreground"]["blocked"] is False
    assert sections["foreground"]["sidecars_non_blocking"] is True
    assert "unbounded model prose" not in json.dumps(fixture).lower()
