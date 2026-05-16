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
