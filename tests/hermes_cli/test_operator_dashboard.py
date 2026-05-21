import json

import pytest

from hermes_cli.platform_hardening import ApprovalLedger


FORBIDDEN_SUBSTRINGS = (
    "raw_stdout",
    "raw_stderr",
    "provider_log",
    "connector_credential",
    "password",
    "api_key",
    "token=",
)


def _payload(value):
    return json.dumps(value, sort_keys=True).casefold()


def _assert_redacted(value):
    payload = _payload(value)
    for forbidden in FORBIDDEN_SUBSTRINGS:
        assert forbidden not in payload


def _actor(tenant_id="tenant-a", role="tenant-admin", cross_tenant=False):
    return {
        "actor_id": "operator-a",
        "role": role,
        "tenant_id": tenant_id,
        "cross_tenant": cross_tenant,
    }


def test_t329_dashboard_seed_fixture_covers_all_operator_domains():
    from hermes_cli.operator_dashboard import seed_operator_dashboard_fixture

    state = seed_operator_dashboard_fixture()
    data = state.to_dict()

    assert data["tenants"]
    assert data["repos"]
    assert data["jobs"]
    assert data["worker_attempts"]
    assert data["sidecars"]
    assert data["memory_packets"]
    assert data["approval_requests"]
    assert data["corpus_exports"]
    assert data["bus_events"]
    assert data["benchmarks"]
    assert data["azure_deployments"]
    assert {job["tenant_id"] for job in data["jobs"]} == {"tenant-a", "tenant-b"}
    _assert_redacted(data)


def test_t330_jobs_table_filters_and_redacted_summaries():
    from hermes_cli.operator_dashboard import OperatorDashboardFilters, list_operator_jobs, seed_operator_dashboard_fixture

    state = seed_operator_dashboard_fixture()
    actor = _actor()

    rows = list_operator_jobs(
        state,
        actor=actor,
        filters=OperatorDashboardFilters(
            tenant_id="tenant-a",
            repo_id="repo-a",
            date_from=1000.0,
            date_to=2000.0,
            status="blocked",
            worker_family="codex",
            model="gpt-5",
            blocked=True,
            blocker="approval",
            max_cost_usd=1.0,
            deployment_id="deploy-a",
        ),
    )

    assert [row["job_id"] for row in rows] == ["job-a"]
    row = rows[0]
    assert row["tenant_id"] == "tenant-a"
    assert row["repo_id"] == "repo-a"
    assert row["worker"]["family"] == "codex"
    assert row["model"]["name"] == "gpt-5"
    assert row["deployment"]["deployment_id"] == "deploy-a"
    assert row["raw_transcripts_included"] is False
    assert row["evidence_refs"]
    _assert_redacted(row)

    with pytest.raises(PermissionError):
        list_operator_jobs(state, actor=actor, filters=OperatorDashboardFilters(tenant_id="tenant-b"))
    cross_tenant = list_operator_jobs(
        state,
        actor=_actor(cross_tenant=True),
        filters=OperatorDashboardFilters(tenant_id="tenant-b"),
    )
    assert [row["tenant_id"] for row in cross_tenant] == ["tenant-b"]


def test_t331_job_detail_tabs_are_lazy_bounded_and_redacted():
    from hermes_cli.operator_dashboard import JOB_DETAIL_TABS, build_job_detail_tab, seed_operator_dashboard_fixture

    state = seed_operator_dashboard_fixture()
    actor = _actor()

    for tab in JOB_DETAIL_TABS:
        dto = build_job_detail_tab(state, actor=actor, job_id="job-a", tab=tab)
        assert dto["job_id"] == "job-a"
        assert dto["tab"] == tab
        assert dto["lazy_loaded"] is True
        assert dto["raw_transcripts_included"] is False
        assert dto["bounded"] is True
        assert dto["evidence_refs"]
        _assert_redacted(dto)

    with pytest.raises(PermissionError):
        build_job_detail_tab(state, actor=actor, job_id="job-b", tab="Overview")


def test_t332_approval_inbox_uses_shared_ledger_for_all_dangerous_actions():
    from hermes_cli.operator_dashboard import (
        APPROVAL_ACTIONS,
        consume_dashboard_approval,
        list_approval_inbox,
        request_dashboard_approval,
        seed_operator_dashboard_fixture,
    )

    ledger = ApprovalLedger()
    state = seed_operator_dashboard_fixture(approval_ledger=ledger)
    actor = _actor()

    approvals = [
        request_dashboard_approval(
            state,
            actor=actor,
            action=action,
            target_ref=f"target://{index}",
            target_hash=f"target-hash-{index}",
            evidence_refs=[f"evidence://{index}"],
            expires_at=2000.0,
            now=1500.0,
        )
        for index, action in enumerate(APPROVAL_ACTIONS)
    ]

    inbox = list_approval_inbox(state, actor=actor)
    assert {item["action"] for item in inbox} == set(APPROVAL_ACTIONS)
    assert all(item["approval_ledger_id"].startswith("approval_") for item in inbox)

    denied = consume_dashboard_approval(
        state,
        actor=actor,
        approval_ledger_id=approvals[0]["approval_ledger_id"],
        action=approvals[0]["action"],
        target_hash="wrong-target-hash",
        now=1510.0,
    )
    assert denied["allowed"] is False
    assert denied["reason"] == "target_hash_mismatch"

    accepted = consume_dashboard_approval(
        state,
        actor=actor,
        approval_ledger_id=approvals[0]["approval_ledger_id"],
        action=approvals[0]["action"],
        target_hash="target-hash-0",
        now=1511.0,
    )
    assert accepted["allowed"] is True

    replay = consume_dashboard_approval(
        state,
        actor=actor,
        approval_ledger_id=approvals[0]["approval_ledger_id"],
        action=approvals[0]["action"],
        target_hash="target-hash-0",
        now=1512.0,
    )
    assert replay["allowed"] is False
    assert replay["reason"] == "approval_already_consumed"
    _assert_redacted(ledger.inspect_json())


def test_t333_sidecar_and_bus_health_panels_have_no_secrets():
    from hermes_cli.operator_dashboard import build_sidecar_bus_health, seed_operator_dashboard_fixture

    panel = build_sidecar_bus_health(seed_operator_dashboard_fixture(), actor=_actor())

    assert panel["sidecars"][0].keys() >= {
        "role",
        "tier",
        "model",
        "state",
        "budget_decision",
        "queue",
        "last_run_at",
        "failure_reason",
        "next_eligible_run_at",
    }
    assert panel["bus"]["backend"] == "sqlite"
    assert panel["bus"]["lag"] >= 0
    assert panel["bus"]["dead_letter_count"] >= 0
    assert panel["bus"]["spool_state"] in {"healthy", "degraded"}
    _assert_redacted(panel)


def test_t334_cost_context_panel_attributes_runtime_costs():
    from hermes_cli.operator_dashboard import build_cost_context_panel, seed_operator_dashboard_fixture

    panel = build_cost_context_panel(seed_operator_dashboard_fixture(), actor=_actor(), tenant_id="tenant-a", repo_id="repo-a")

    assert panel["tenant_id"] == "tenant-a"
    assert panel["repo_id"] == "repo-a"
    assert panel["totals"]["input_tokens"] > 0
    assert panel["totals"]["output_tokens"] > 0
    assert panel["totals"]["estimated_cost_usd"] > 0
    assert panel["totals"]["latency_ms"] > 0
    assert panel["attribution"]["context_admitted_tokens"] > 0
    assert panel["attribution"]["sidecar_calls"] > 0
    assert panel["attribution"]["memory_hits"] > 0
    assert panel["attribution"]["worker_attempts"] > 0
    assert panel["benchmarks"][0]["benchmark_id"] == "bench-a"
    _assert_redacted(panel)


def test_t335_scoped_ask_uses_read_only_bounded_evidence_and_no_mutation_tools():
    from hermes_cli.operator_dashboard import build_scoped_ask_bundle, seed_operator_dashboard_fixture

    prompts = []

    def fake_model(prompt, bundle):
        prompts.append(prompt)
        assert bundle["read_only"] is True
        assert bundle["mutation_tools"] == []
        assert bundle["bounded"] is True
        _assert_redacted(bundle)
        return {"answer": "Job is blocked on approval.", "citations": bundle["evidence_refs"][:2]}

    result = build_scoped_ask_bundle(
        seed_operator_dashboard_fixture(),
        actor=_actor(),
        job_id="job-a",
        question="Why is this blocked?",
        model_call=fake_model,
    )

    assert result["mutation_allowed"] is False
    assert result["tool_policy"]["mutation_tools"] == []
    assert result["evidence_bundle"]["read_only"] is True
    assert result["answer"]["citations"]
    assert len(prompts) == 1
    _assert_redacted(result)


def test_t336_azure_deployment_panel_is_gated_and_redacted():
    from hermes_cli.operator_dashboard import build_azure_deployment_panel, seed_operator_dashboard_fixture

    panel = build_azure_deployment_panel(seed_operator_dashboard_fixture(), actor=_actor(), deployment_id="deploy-a")

    assert panel["deployment_id"] == "deploy-a"
    assert panel["plan"]["environment"] == "staging"
    assert panel["preflight"]["ok"] is True
    assert panel["apply"]["state"] == "blocked"
    assert panel["smoke"]["state"] == "passed"
    assert panel["soak"]["state"] == "running"
    assert panel["promote"]["state"] == "blocked"
    assert panel["rollback"]["available"] is True
    assert panel["hardening_failures"] == []
    assert panel["costs"]["estimated_cost_usd"] > 0
    assert "operator_approval_required" in panel["required_operator_actions"]
    _assert_redacted(panel)


def test_t343_operator_dashboard_smoke_fixture_is_safe_by_default():
    from hermes_cli.operator_dashboard import run_operator_dashboard_smoke_fixture

    result = run_operator_dashboard_smoke_fixture()

    assert result["seeded_state_visible"] is True
    assert result["dangerous_action_without_approval"]["allowed"] is False
    assert result["dangerous_action_without_approval"]["fail_closed"] is True
    assert result["raw_logs_loaded"] is False
    assert result["raw_transcripts_loaded"] is False
    _assert_redacted(result)
