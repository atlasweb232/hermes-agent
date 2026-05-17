import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from hermes_cli.learning_judge import (
    LearningJudgeConfig,
    LearningJudgeParseError,
    parse_learning_judge_decision,
    run_learning_judge,
)
from hermes_state import SessionDB


def _make_db(tmp_path: Path) -> SessionDB:
    return SessionDB(db_path=tmp_path / "state.db")


def _candidate_json(candidate_id: str, decision: str = "approve", confidence: float = 0.9) -> str:
    return json.dumps(
        {
            "candidate_id": candidate_id,
            "decision": decision,
            "confidence": confidence,
            "rationale": "evidence-backed advisory candidate",
            "risk_flags": [],
            "allow_enforcement": False,
        }
    )


def _seed_candidate(
    db: SessionDB,
    candidate_id: str,
    *,
    claim: str = "Prefer direct Claude invocation after wrapper failure",
    score: float = 0.9,
) -> None:
    db.upsert_meta_candidate(
        candidate_id=candidate_id,
        kind="routing_hint",
        claim=claim,
        evidence_json={"evidence_uri": "artifact://judge-test/log.txt", "status": "ready"},
        score=score,
        status="proposed",
        tenant_id="atlas",
        repo_id="hermes-agent",
    )


def test_parse_learning_judge_decision_accepts_strict_schema():
    decision = parse_learning_judge_decision(
        _candidate_json("metacand_1"),
        expected_candidate_id="metacand_1",
    )

    assert decision.candidate_id == "metacand_1"
    assert decision.decision == "approve"
    assert decision.confidence == 0.9
    assert decision.allow_enforcement is False


@pytest.mark.parametrize(
    "payload,error",
    [
        ("not json", "JSON object"),
        ({"candidate_id": "metacand_1", "decision": "approve"}, "missing judge fields"),
        (
            {
                "candidate_id": "metacand_1",
                "decision": "approved",
                "confidence": 0.9,
                "rationale": "ok",
                "risk_flags": [],
                "allow_enforcement": False,
            },
            "invalid decision",
        ),
        (
            {
                "candidate_id": "metacand_1",
                "decision": "approve",
                "confidence": 1.2,
                "rationale": "ok",
                "risk_flags": [],
                "allow_enforcement": False,
            },
            "between 0 and 1",
        ),
        (
            {
                "candidate_id": "metacand_1",
                "decision": "approve",
                "confidence": 0.9,
                "rationale": "ok",
                "risk_flags": [],
                "allow_enforcement": False,
                "extra": "nope",
            },
            "unexpected judge fields",
        ),
    ],
)
def test_parse_learning_judge_decision_rejects_invalid_schema(payload, error):
    raw = payload if isinstance(payload, str) else json.dumps(payload)

    with pytest.raises(LearningJudgeParseError) as exc:
        parse_learning_judge_decision(raw, expected_candidate_id="metacand_1")

    assert error in str(exc.value)


def test_parse_learning_judge_decision_rejects_candidate_mismatch():
    with pytest.raises(LearningJudgeParseError) as exc:
        parse_learning_judge_decision(
            _candidate_json("metacand_other"),
            expected_candidate_id="metacand_1",
        )

    assert "candidate_id mismatch" in str(exc.value)


def test_learning_judge_approves_and_rejects_candidates(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    monkeypatch.setenv("HERMES_HOME", str(home))
    db = _make_db(home)
    try:
        _seed_candidate(db, "metacand_approve", claim="Low-risk advisory routing hint")
        _seed_candidate(db, "metacand_reject", claim="Unsupported dangerous enforcement")

        def fake_model_call(_cfg: LearningJudgeConfig, prompt: str) -> str:
            if "metacand_reject" in prompt:
                return _candidate_json("metacand_reject", decision="reject", confidence=0.95)
            return _candidate_json("metacand_approve", decision="approve", confidence=0.9)

        result = run_learning_judge(
            db,
            tenant_id="atlas",
            repo_id="hermes-agent",
            config={"supervisor": {"learning_judge": {"max_candidates": 10}}},
            model_call=fake_model_call,
        )

        assert result.status == "completed"
        assert result.approved == 1
        assert result.rejected == 1
        assert db.get_meta_candidate("metacand_approve")["status"] == "approved"
        rejected = db.get_meta_candidate("metacand_reject")
        assert rejected["status"] == "rejected"
        assert "learning judge rejected" in rejected["evidence_json"]["reason"]
    finally:
        db.close()


def test_learning_judge_fail_closed_rejects_malformed_output(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    monkeypatch.setenv("HERMES_HOME", str(home))
    db = _make_db(home)
    try:
        _seed_candidate(db, "metacand_bad_output")

        result = run_learning_judge(
            db,
            tenant_id="atlas",
            repo_id="hermes-agent",
            config={"supervisor": {"learning_judge": {"max_candidates": 1, "fail_closed": True}}},
            model_call=lambda _cfg, _prompt: "not-json",
        )

        assert result.status == "completed_with_errors"
        assert result.rejected == 1
        row = db.get_meta_candidate("metacand_bad_output")
        assert row["status"] == "rejected"
        assert "malformed_judge_output" in row["evidence_json"]["judge_risk_flags"]
    finally:
        db.close()


def test_learning_judge_timeout_escalates_to_human(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    monkeypatch.setenv("HERMES_HOME", str(home))
    db = _make_db(home)
    try:
        _seed_candidate(db, "metacand_timeout")

        def timeout_call(_cfg: LearningJudgeConfig, _prompt: str) -> str:
            raise TimeoutError("slow judge")

        result = run_learning_judge(
            db,
            tenant_id="atlas",
            repo_id="hermes-agent",
            config={"supervisor": {"learning_judge": {"max_candidates": 1, "fail_closed": True}}},
            model_call=timeout_call,
        )

        assert result.status == "completed_with_errors"
        assert result.needs_human == 1
        row = db.get_meta_candidate("metacand_timeout")
        assert row["status"] == "needs_human"
        assert "judge_unavailable" in row["evidence_json"]["judge_risk_flags"]
    finally:
        db.close()


def test_learning_judge_low_confidence_approval_escalates_to_human(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    monkeypatch.setenv("HERMES_HOME", str(home))
    db = _make_db(home)
    try:
        _seed_candidate(db, "metacand_low_confidence")

        result = run_learning_judge(
            db,
            tenant_id="atlas",
            repo_id="hermes-agent",
            config={"supervisor": {"learning_judge": {"max_candidates": 1, "min_confidence": 0.8}}},
            model_call=lambda _cfg, _prompt: _candidate_json("metacand_low_confidence", confidence=0.5),
        )

        assert result.status == "completed"
        assert result.needs_human == 1
        row = db.get_meta_candidate("metacand_low_confidence")
        assert row["status"] == "needs_human"
        assert "low_judge_confidence" in row["evidence_json"]["judge_risk_flags"]
    finally:
        db.close()


def test_learning_judge_cli_json_smoke(tmp_path, monkeypatch, capsys):
    home = tmp_path / ".hermes"
    monkeypatch.setenv("HERMES_HOME", str(home))
    db = SessionDB()
    try:
        _seed_candidate(db, "metacand_cli")
    finally:
        db.close()

    from hermes_cli import learning_judge
    from hermes_cli import main as hermes_main

    monkeypatch.setattr(
        learning_judge,
        "call_learning_judge_model",
        lambda _cfg, _prompt: _candidate_json("metacand_cli"),
    )
    argv = [
        "hermes",
        "memory",
        "judge-run",
        "--tenant-id",
        "atlas",
        "--repo-id",
        "hermes-agent",
        "--json",
    ]

    with patch.object(sys, "argv", argv):
        hermes_main.main()

    data = json.loads(capsys.readouterr().out)
    assert data["status"] == "completed"
    assert data["approved"] == 1
    assert data["results"][0]["candidate_id"] == "metacand_cli"
