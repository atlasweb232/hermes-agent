import json
from pathlib import Path

import pytest

from hermes_cli.runtime_benchmark import (
    REQUIRED_TELEMETRY_ROLES,
    BenchmarkEnvironment,
    BenchmarkEnvironmentPair,
    BenchmarkWorkload,
    GateThresholds,
    ModelToolProfile,
    ProductionGateInput,
    RepoRef,
    TelemetryRecord,
    ValidationCommand,
    WorkloadPack,
    load_workload_pack,
    validate_environment_pair,
    validate_production_gate,
)


def _workload(workload_id: str, workload_class: str = "review") -> BenchmarkWorkload:
    return BenchmarkWorkload(
        workload_id=workload_id,
        workload_class=workload_class,
        repo_refs=[RepoRef(repo_id="hermes-agent", snapshot_ref="abc123", branch_ref="main")],
        prompt="Review the branch and report actionable regressions.",
        model_profile=ModelToolProfile(
            provider="openai",
            model="gpt-5.4",
            allowed_workers=["codex"],
            allowed_tools=["terminal", "read_file", "patch"],
            max_prompt_tokens=1000,
            max_cost_usd=1.0,
        ),
        expected_artifacts=["review.md"],
        validation_commands=[ValidationCommand(command="pytest -q", timeout_seconds=120)],
        pass_fail_rubric={"pass": ["finds real regressions"], "fail": ["fabricates files"]},
    )


def test_benchmark_environment_pair_requires_isolated_homes_and_artifacts(tmp_path):
    workload_path = tmp_path / "workloads" / "suite.json"
    workload_path.parent.mkdir()
    workload_path.write_text("{}", encoding="utf-8")
    pair = BenchmarkEnvironmentPair(
        upstream=BenchmarkEnvironment(
            name="upstream",
            hermes_home=tmp_path / "homes" / "upstream",
            artifact_root=tmp_path / "artifacts" / "upstream",
            checkout_path=tmp_path / "checkouts" / "upstream",
            workload_definition=workload_path,
        ),
        branch=BenchmarkEnvironment(
            name="branch",
            hermes_home=tmp_path / "homes" / "branch",
            artifact_root=tmp_path / "artifacts" / "branch",
            checkout_path=tmp_path / "checkouts" / "branch",
            workload_definition=workload_path,
        ),
    )

    result = validate_environment_pair(pair)

    assert result.valid is True
    assert pair.upstream.hermes_home != pair.branch.hermes_home
    assert pair.upstream.artifact_root != pair.branch.artifact_root
    assert pair.upstream.workload_definition == pair.branch.workload_definition


def test_benchmark_environment_pair_rejects_cross_contamination(tmp_path):
    shared_home = tmp_path / "home"
    shared_artifacts = tmp_path / "artifacts"
    upstream = BenchmarkEnvironment(
        name="upstream",
        hermes_home=shared_home,
        artifact_root=shared_artifacts,
        checkout_path=tmp_path / "upstream",
        workload_definition=tmp_path / "suite.json",
    )
    branch = BenchmarkEnvironment(
        name="branch",
        hermes_home=shared_home,
        artifact_root=shared_artifacts / "branch",
        checkout_path=tmp_path / "branch",
        workload_definition=tmp_path / "other-suite.json",
    )

    result = validate_environment_pair(BenchmarkEnvironmentPair(upstream=upstream, branch=branch))

    assert result.valid is False
    assert "hermes_home" in result.errors[0]
    assert any("workload_definition" in err for err in result.errors)


def test_telemetry_schema_covers_required_roles_and_redacted_evidence():
    for role in REQUIRED_TELEMETRY_ROLES:
        record = TelemetryRecord(
            environment="branch",
            session_id=f"session-{role}",
            task_id="task-1",
            workload_id="review-1",
            tenant_id="tenant-a",
            repo_id="hermes-agent",
            role=role,
            provider="openai",
            model="gpt-5.4",
            worker_id=f"{role}-worker",
            prompt_tokens=100,
            completion_tokens=25,
            cached_tokens=10,
            input_tokens=100,
            output_tokens=25,
            token_usage_estimated=False,
            estimated_cost_usd=0.02,
            wall_latency_ms=500,
            queue_latency_ms=20,
            context_tokens_admitted=300,
            context_bytes_admitted=1200,
            raw_bytes_stored_out_of_context=4096,
            memory_packet_ids=["mempkt-1"],
            sidecars_triggered=["curator"] if role == "curator" else [],
            sidecars_skipped=[],
            judge_decisions=["approved"] if role == "judge" else [],
            worker_attempts=1,
            fallback_reasons=[],
            validation_result="passed",
            notification_counts={"slack": 1, "dashboard": 1},
            operator_intervention_count=0,
            path_attribution={"surface": "runtime-benchmark", "role": role},
            evidence_refs=["artifact://branch/review-1/telemetry.jsonl"],
            evidence_excerpt="bounded redacted summary only",
        )

        validation = record.validate()

        assert validation.valid is True, (role, validation.errors)
        data = record.to_dict()
        assert data["role"] == role
        assert data["estimated_cost_usd"] > 0
        assert "raw_transcript" not in data
        assert "secret" not in data


def test_telemetry_rejects_missing_path_attribution_and_unbounded_transcripts():
    record = TelemetryRecord(
        environment="branch",
        session_id="session-1",
        task_id="task-1",
        workload_id="review-1",
        tenant_id="tenant-a",
        repo_id="hermes-agent",
        role="worker",
        provider="openai",
        model="gpt-5.4",
        prompt_tokens=1,
        completion_tokens=1,
        input_tokens=1,
        output_tokens=1,
        estimated_cost_usd=0.01,
        wall_latency_ms=1,
        queue_latency_ms=1,
        context_tokens_admitted=1,
        context_bytes_admitted=1,
        raw_bytes_stored_out_of_context=1,
        validation_result="passed",
        evidence_refs=[],
        raw_transcript="do not store this",
        path_attribution={},
    )

    result = record.validate()

    assert result.valid is False
    assert "path_attribution" in result.missing
    assert any("raw_transcript" in err for err in result.errors)


def test_production_gate_fails_closed_for_regression_and_safety_violations():
    gate = validate_production_gate(
        ProductionGateInput(
            upstream_success_rate=0.9,
            branch_success_rate=0.8,
            upstream_false_completion_rate=0.2,
            branch_false_completion_rate=0.2,
            upstream_repeated_error_rate=0.1,
            branch_repeated_error_rate=0.2,
            cost_per_success_ratio=1.5,
            foreground_latency_ratio=1.0,
            sidecar_blocked_foreground=True,
            urgent_alerts_expected=3,
            urgent_alerts_sent=2,
            memory_approval_boundary_preserved=False,
            judge_operator_boundary_preserved=False,
            operator_overrode_failed_validation=True,
        ),
        GateThresholds(max_cost_regression_ratio=1.2, max_latency_regression_ratio=1.25),
    )

    assert gate.allowed is False
    assert "branch_success_rate_regressed" in gate.blockers
    assert "sidecar_blocked_foreground" in gate.blockers
    assert "urgent_alerts_missing" in gate.blockers
    assert "memory_approval_boundary_violated" in gate.blockers
    assert "judge_operator_boundary_violated" in gate.blockers
    assert "cost_threshold_exceeded" in gate.blockers


def test_production_gate_passes_when_branch_improves_within_thresholds():
    gate = validate_production_gate(
        ProductionGateInput(
            upstream_success_rate=0.7,
            branch_success_rate=0.8,
            upstream_false_completion_rate=0.3,
            branch_false_completion_rate=0.1,
            upstream_repeated_error_rate=0.25,
            branch_repeated_error_rate=0.1,
            cost_per_success_ratio=1.05,
            foreground_latency_ratio=1.1,
            sidecar_blocked_foreground=False,
            urgent_alerts_expected=2,
            urgent_alerts_sent=2,
            memory_approval_boundary_preserved=True,
            judge_operator_boundary_preserved=True,
        ),
        GateThresholds(max_cost_regression_ratio=1.2, max_latency_regression_ratio=1.25),
    )

    assert gate.allowed is True
    assert gate.blockers == []


def test_workload_pack_fixture_covers_required_classes(tmp_path):
    workloads = [
        _workload("review-1", "review"),
        _workload("implementation-1", "implementation"),
        _workload("qa-1", "qa"),
        _workload("deployment-1", "deployment"),
        _workload("goal-1", "long_running_goal"),
        _workload("fallback-1", "fallback"),
        _workload("stale-1", "stale_worker"),
        _workload("failure-1", "repeated_failure"),
        _workload("multi-1", "multi_repo_decomposition"),
        _workload("hallucinated-1", "hallucinated_completion"),
    ]
    pack = WorkloadPack(
        pack_id="phase14-smoke",
        version="1",
        workloads=workloads,
        immutable=True,
    )
    path = tmp_path / "pack.json"
    path.write_text(json.dumps(pack.to_dict()), encoding="utf-8")

    loaded = load_workload_pack(path)

    result = loaded.validate()
    assert result.valid is True
    assert {item.workload_class for item in loaded.workloads} == {
        "review",
        "implementation",
        "qa",
        "deployment",
        "long_running_goal",
        "fallback",
        "stale_worker",
        "repeated_failure",
        "multi_repo_decomposition",
        "hallucinated_completion",
    }


def test_workload_loader_accepts_yaml_and_validates_required_fields(tmp_path):
    pytest.importorskip("yaml")
    path = tmp_path / "pack.yaml"
    path.write_text(
        """
pack_id: phase14-yaml
version: "1"
immutable: true
workloads:
  - workload_id: review-1
    workload_class: review
    repo_refs:
      - repo_id: hermes-agent
        snapshot_ref: abc123
        branch_ref: main
    prompt: Review this branch.
    model_profile:
      provider: openai
      model: gpt-5.4
      allowed_workers: [codex]
      allowed_tools: [terminal, read_file]
      max_prompt_tokens: 1000
      max_cost_usd: 1.0
    expected_artifacts: [review.md]
    validation_commands:
      - command: pytest -q
        timeout_seconds: 120
    pass_fail_rubric:
      pass: [validated findings]
      fail: [hallucinated files]
""",
        encoding="utf-8",
    )

    pack = load_workload_pack(path)

    assert pack.validate().valid is True
    workload = pack.workloads[0]
    assert workload.repo_refs[0].repo_id == "hermes-agent"
    assert workload.model_profile.allowed_tools == ["terminal", "read_file"]
    assert workload.validation_commands[0].command == "pytest -q"


def test_workload_rejects_missing_prompt_validation_and_rubric():
    workload = BenchmarkWorkload(
        workload_id="bad-1",
        workload_class="review",
        repo_refs=[],
        prompt="",
        model_profile=ModelToolProfile(provider="", model="", allowed_workers=[], allowed_tools=[]),
        expected_artifacts=[],
        validation_commands=[],
        pass_fail_rubric={},
    )

    result = workload.validate()

    assert result.valid is False
    assert "prompt" in result.missing
    assert "repo_refs" in result.missing
    assert "validation_commands" in result.missing
    assert "pass_fail_rubric" in result.missing
