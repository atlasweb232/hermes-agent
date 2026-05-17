from __future__ import annotations

import json

from hermes_cli.policy_engine import evaluate_command_policy
from hermes_state import SessionDB
from tools.terminal_tool import terminal_tool


def _insert_claude_policy(db: SessionDB) -> None:
    db.upsert_meta_candidate(
        candidate_id="curpol_claude",
        kind="command_repair_policy",
        claim="Prefer direct Claude Code invocation after worker-router failures",
        evidence_json={
            "policy_version": "2026.05.16",
            "policy_type": "command_repair",
            "mode": "advisory",
            "source_record_id": "memrec_claude",
            "failed_path": "worker-router claude",
            "working_path": "claude --model sonnet -p",
        },
        score=0.9,
        status="approved",
    )


def test_evaluate_command_policy_audits_matching_command(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    monkeypatch.setenv("HERMES_HOME", str(home))
    db = SessionDB(db_path=home / "state.db")
    try:
        _insert_claude_policy(db)

        decision = evaluate_command_policy(
            'worker-router claude "two plus two"',
            db=db,
            config={"supervisor": {"policy_engine": {"enabled": True, "mode": "audit"}}},
        )

        assert decision.status == "matched"
        assert decision.mode == "audit"
        assert decision.effective_command == decision.original_command
        assert decision.matches[0]["policy_id"] == "curpol_claude"
        assert decision.matches[0]["action"] == "would_rewrite"
    finally:
        db.close()


def test_evaluate_command_policy_skips_secret_like_command(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    monkeypatch.setenv("HERMES_HOME", str(home))
    db = SessionDB(db_path=home / "state.db")
    try:
        _insert_claude_policy(db)

        decision = evaluate_command_policy(
            'worker-router claude "token=sk-1234567890abcdef"',
            db=db,
            config={"supervisor": {"policy_engine": {"enabled": True, "mode": "audit"}}},
        )

        assert decision.status == "skipped"
        assert "secret" in decision.notes
        assert decision.matches == []
    finally:
        db.close()


def test_terminal_tool_attaches_policy_audit_without_rewriting(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("TERMINAL_ENV", "local")
    monkeypatch.setenv("TERMINAL_CWD", str(tmp_path))
    db = SessionDB(db_path=home / "state.db")
    try:
        _insert_claude_policy(db)
    finally:
        db.close()

    result = json.loads(terminal_tool('worker-router claude "two plus two"', timeout=1))

    assert "runtime_policy_audit" in result
    audit = result["runtime_policy_audit"]
    assert audit["status"] == "matched"
    assert audit["effective_command"] == audit["original_command"]
    assert audit["matches"][0]["policy_id"] == "curpol_claude"
