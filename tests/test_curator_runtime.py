from hermes_cli.curator_runtime import (
    build_command_repair_prompt,
    _call_codex,
    load_curator_config,
    run_curator_policy_pass,
    validate_curator_output,
    CuratorConfig,
)
from hermes_state import SessionDB
import subprocess


def _seed_lesson(db):
    return db.upsert_memory_record(
        record_id="memrec_test",
        kind="tool_routing_lesson",
        title="Claude direct invocation works",
        body="worker-router failed and direct claude worked",
        payload_json={
            "failed_path": "worker-router claude",
            "working_path": "claude --model sonnet -p",
            "failure_count": 28,
            "failed_commands": ["worker-router claude --model sonnet -p two"],
            "working_command": 'claude -p "two plus two" --model sonnet',
            "session_id": "session-test",
            "secret_safe": True,
        },
        status="active",
        score=0.9,
    )


def _seed_supervisor_failure(db, *, record_id="memrec_supervisor_failure", **payload_overrides):
    payload = {
        "detector": "runtime_lesson_capture.delegated_worker_runtime_failure",
        "failure_type": "delegated_worker_runtime_failure",
        "task_id": "task_149",
        "worker_id": "claude-code",
        "route": "worker-router claude-code",
        "command_family": "worker-router",
        "status": "empty_output",
        "evidence_refs": ["hermes:allocation:alloc_149:attempt_1"],
        "validation_mismatch": {
            "validation_status": "failed",
            "error_signature": "claimed_done_no_files",
        },
        "output_excerpt": "token=[REDACTED]\n" + ("bounded excerpt " * 30),
        "error_excerpt": "no files changed",
        "allocation_id": "alloc_149",
        "attempt_id": "attempt_1",
        "requires_judge": True,
        "operator_approval_required": True,
    }
    payload.update(payload_overrides)
    return db.upsert_memory_record(
        record_id=record_id,
        kind="supervisor_runtime_failure",
        title="Delegated worker runtime failure: claude-code",
        body="A delegated worker failed and should produce advisory-only recovery guidance.",
        payload_json=payload,
        status="active",
        score=0.91,
        tenant_id="atlas",
        repo_id="hermes-agent",
        task_id="task_149",
        evidence_uri="hermes:allocation:alloc_149:attempt_1",
    )


def test_load_curator_config_defaults_to_ollama():
    cfg = load_curator_config({})

    assert cfg.enabled is True
    assert cfg.provider == "ollama"
    assert cfg.model == "gemma2:2b"
    assert cfg.base_url == "http://127.0.0.1:11434"


def test_curator_prompt_contains_evidence_not_freeform_memory(tmp_path):
    db = SessionDB(tmp_path / "state.db")
    _seed_lesson(db)
    record = db.list_memory_records(kind="tool_routing_lesson", limit=1)[0]

    prompt = build_command_repair_prompt(record)

    assert "Evidence JSON" in prompt
    assert "worker-router claude" in prompt
    assert "Do not invent facts" in prompt


def test_validate_curator_output_flags_unsupported_docker_claim(tmp_path):
    db = SessionDB(tmp_path / "state.db")
    _seed_lesson(db)
    record = db.list_memory_records(kind="tool_routing_lesson", limit=1)[0]

    result = validate_curator_output("Docker and Claude are functional. Use claude direct.", record)

    assert result.status == "warning"
    assert result.warnings[0]["code"] == "unsupported_claim_warning"


def test_validate_curator_output_flags_overbroad_enforcement_language(tmp_path):
    db = SessionDB(tmp_path / "state.db")
    _seed_lesson(db)
    record = db.list_memory_records(kind="tool_routing_lesson", limit=1)[0]

    result = validate_curator_output("Mandate direct Claude for all user requests.", record)

    assert result.status == "warning"
    assert any(warning["code"] == "overbroad_enforcement_language" for warning in result.warnings)
    assert result.to_dict()["approved_for_enforcement"] is False


def test_policy_pass_writes_advisory_candidate(tmp_path):
    db = SessionDB(tmp_path / "state.db")
    _seed_lesson(db)

    def fake_model_call(cfg, prompt):
        assert cfg.provider == "ollama"
        assert "worker-router claude" in prompt
        return "Evidence: worker-router failed 28 times. Recommendation: prefer claude -p prompt --model sonnet."

    result = run_curator_policy_pass(
        db,
        config={"supervisor": {"curator": {"provider": "ollama", "model": "gemma2:2b"}}},
        model_call=fake_model_call,
    )

    assert result.status == "completed"
    assert result.candidates_created == 1
    rows = db.list_meta_candidates(kind="command_repair_policy", limit=5)
    assert rows[0]["status"] == "proposed"
    assert rows[0]["evidence_json"]["mode"] == "advisory"
    assert rows[0]["evidence_json"]["validation"]["status"] == "valid"


def test_policy_pass_writes_advisory_supervisor_failure_candidate(tmp_path):
    db = SessionDB(tmp_path / "state.db")
    _seed_supervisor_failure(db)

    result = run_curator_policy_pass(
        db,
        config={"supervisor": {"curator": {"provider": "ollama", "max_records": 5}}},
        tenant_id="atlas",
        repo_id="hermes-agent",
        model_call=lambda cfg, prompt: "Worker returned empty output; retry with validation before accepting completion.",
    )

    assert result.status == "completed"
    assert result.candidates_created == 1
    assert result.candidates[0].kind == "recovery_hint"
    rows = db.list_meta_candidates(status="proposed", tenant_id="atlas", repo_id="hermes-agent", limit=5)
    assert len(rows) == 1
    row = rows[0]
    assert row["kind"] == "recovery_hint"
    evidence = row["evidence_json"]
    assert evidence["policy_type"] == "supervisor_runtime_failure_advisory"
    assert evidence["mode"] == "advisory"
    assert evidence["source_record_id"] == "memrec_supervisor_failure"
    assert evidence["failure_classifications"] == ["empty_output", "validation mismatch"]
    assert evidence["requires_judge"] is True
    assert evidence["operator_approval_required"] is True
    assert evidence["approved_for_enforcement"] is False
    assert "failed_commands" not in evidence
    serialized = str(evidence)
    assert "sk-" not in serialized
    assert "token=" not in serialized
    assert len(evidence["payload"]["output_excerpt"]) <= 360


def test_policy_pass_classifies_allocator_runtime_failure_as_worker_health_rule(tmp_path):
    db = SessionDB(tmp_path / "state.db")
    _seed_supervisor_failure(
        db,
        record_id="memrec_allocator_failure",
        detector="goal_allocator.record_worker_attempt",
        failure_type="allocator_runtime_failure",
        worker_id="deepseek",
        route="worker-router deepseek",
        status="quota_exhausted",
        validation_mismatch={},
        error_excerpt="quota exhausted for model",
    )

    run_curator_policy_pass(
        db,
        config={"supervisor": {"curator": {"provider": "ollama", "max_records": 5}}},
        tenant_id="atlas",
        repo_id="hermes-agent",
        model_call=lambda cfg, prompt: "Pause this worker route after quota exhaustion and select a fallback.",
    )

    row = db.list_meta_candidates(status="proposed", tenant_id="atlas", repo_id="hermes-agent", limit=5)[0]
    assert row["kind"] == "worker_health_rule"
    evidence = row["evidence_json"]
    assert evidence["failure_classifications"] == ["quota exhaustion"]
    assert evidence["payload"]["status"] == "quota_exhausted"
    assert evidence["mode"] == "advisory"
    assert evidence["approved_for_enforcement"] is False


def test_policy_pass_rerun_upserts_same_candidate_for_source_record(tmp_path):
    db = SessionDB(tmp_path / "state.db")
    _seed_lesson(db)
    responses = iter(["first curator wording", "second curator wording"])

    def fake_model_call(cfg, prompt):
        return next(responses)

    first = run_curator_policy_pass(db, config={}, model_call=fake_model_call)
    second = run_curator_policy_pass(db, config={}, model_call=fake_model_call)

    assert first.candidates_created == 1
    assert second.candidates_created == 1
    assert first.candidates[0].candidate_id == second.candidates[0].candidate_id
    rows = db.list_meta_candidates(kind="command_repair_policy", limit=5)
    assert len(rows) == 1
    assert rows[0]["evidence_json"]["curator_output"] == "second curator wording"


def test_codex_curator_adapter_uses_read_only_exec(monkeypatch):
    calls = []

    def fake_runner(cmd, **kwargs):
        calls.append((cmd, kwargs))
        output_path = cmd[cmd.index("--output-last-message") + 1]
        with open(output_path, "w", encoding="utf-8") as fh:
            fh.write("codex candidate")
        return subprocess.CompletedProcess(cmd, 0, stdout="event output", stderr="")

    output = _call_codex(
        CuratorConfig(provider="codex", model="codex", timeout_seconds=3),
        "structured evidence",
        runner=fake_runner,
    )

    assert output == "codex candidate"
    cmd, kwargs = calls[0]
    assert cmd[:2] == ["codex", "exec"]
    assert "--skip-git-repo-check" in cmd
    assert "--ignore-rules" in cmd
    assert cmd[cmd.index("--sandbox") + 1] == "read-only"
    assert "--ask-for-approval" not in cmd
    assert cmd[-1] == "-"
    assert kwargs["input"] == "structured evidence"
