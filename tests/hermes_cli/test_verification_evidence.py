"""Tests for the verifiable-reward bridge (teacher-independence loop).

Covers: gate→record conversion + content hashing, evidence persistence, candidate
evidence attachment, the fail-closed promotion predicate, and the end-to-end
approve_meta_candidate gate (judge say-so alone cannot promote without a passing,
model-independent verification).
"""

from __future__ import annotations

import pytest

from hermes_cli.verification_evidence import (
    VerificationRecord,
    attach_verification_to_candidate_evidence,
    capture_held_out_verification_for_task,
    capture_verification_for_task,
    evidence_has_passing_verification,
    load_verification_gate_config,
    record_verification_evidence,
    verification_record_from_gate,
)


# ── fixtures ────────────────────────────────────────────────────────────────

def _passing_gate_dict():
    return {
        "enabled": True,
        "status": "passed",
        "repo_path": "/repo",
        "reason": "",
        "passed": True,
        "checks": [
            {"name": "build_command", "passed": True, "skipped": False,
             "command": ["npm", "test"], "stdout": "ok", "stderr": "", "returncode": 0},
            {"name": "diff_check", "passed": True, "skipped": False, "command": []},
        ],
    }


def _blocked_gate_dict():
    d = _passing_gate_dict()
    d["status"] = "blocked"
    d["passed"] = False
    d["checks"][0]["passed"] = False
    d["checks"][0]["returncode"] = 1
    return d


# ── record construction + hashing ──────────────────────────────────────────

def test_record_from_gate_passing():
    rec = verification_record_from_gate(
        _passing_gate_dict(), task_id="task-1", tenant_id="A", repo_id="r"
    )
    assert rec.status == "passed"
    assert rec.passed is True
    assert rec.evidence_sha256 and len(rec.evidence_sha256) == 64
    assert rec.evidence_uri.startswith("verification://A/r/task-1/")
    assert "2 passed, 0 failed" in rec.summary


def test_record_hash_is_deterministic_and_content_addressed():
    a = verification_record_from_gate(_passing_gate_dict(), task_id="t")
    b = verification_record_from_gate(_passing_gate_dict(), task_id="t")
    c = verification_record_from_gate(_blocked_gate_dict(), task_id="t")
    assert a.evidence_sha256 == b.evidence_sha256  # same content → same hash
    assert a.evidence_sha256 != c.evidence_sha256  # different outcome → different hash


def test_record_accepts_dataclass_gate():
    from hermes_cli.completion_gate import CompletionGateResult, CheckResult

    gate = CompletionGateResult(
        enabled=True, status="passed",
        checks=[CheckResult(name="x", passed=True, command=["true"])],
    )
    rec = verification_record_from_gate(gate, task_id="t")
    assert rec.passed is True


def test_held_out_flag_in_summary_and_block():
    rec = verification_record_from_gate(
        _passing_gate_dict(), task_id="t", held_out=True
    )
    assert rec.held_out is True
    assert "held-out" in rec.summary
    assert rec.to_evidence_block()["held_out"] is True


# ── promotion predicate (fail-closed) ───────────────────────────────────────

def test_predicate_true_for_passing_verification():
    rec = verification_record_from_gate(_passing_gate_dict(), task_id="t")
    evidence = attach_verification_to_candidate_evidence({}, rec)
    assert evidence_has_passing_verification(evidence) is True


def test_predicate_false_for_blocked_verification():
    rec = verification_record_from_gate(_blocked_gate_dict(), task_id="t")
    evidence = attach_verification_to_candidate_evidence({}, rec)
    assert evidence_has_passing_verification(evidence) is False


def test_predicate_fails_closed_on_missing_block():
    assert evidence_has_passing_verification({}) is False
    assert evidence_has_passing_verification(None) is False
    assert evidence_has_passing_verification({"verification": "nope"}) is False
    assert evidence_has_passing_verification({"verification": {}}) is False


def test_predicate_require_held_out():
    rec = verification_record_from_gate(_passing_gate_dict(), task_id="t", held_out=False)
    evidence = attach_verification_to_candidate_evidence({}, rec)
    # passes when held-out not required, fails when it is (global promotion rule)
    assert evidence_has_passing_verification(evidence, require_held_out=False) is True
    assert evidence_has_passing_verification(evidence, require_held_out=True) is False

    rec_ho = verification_record_from_gate(_passing_gate_dict(), task_id="t", held_out=True)
    evidence_ho = attach_verification_to_candidate_evidence({}, rec_ho)
    assert evidence_has_passing_verification(evidence_ho, require_held_out=True) is True


# ── config defaults ─────────────────────────────────────────────────────────

def test_config_defaults_preserve_advisory_posture():
    cfg = load_verification_gate_config(None)
    assert cfg["require_verification_for_approval"] is False  # enforcement off by default
    assert cfg["require_held_out_for_global"] is True

    cfg2 = load_verification_gate_config(
        {"learning": {"verification_gate": {"require_verification_for_approval": True}}}
    )
    assert cfg2["require_verification_for_approval"] is True


# ── persistence + end-to-end capture ────────────────────────────────────────

def test_record_verification_evidence_persists_row(tmp_path):
    from hermes_state import SessionDB

    db = SessionDB(tmp_path / "state.db")
    rec = verification_record_from_gate(
        _passing_gate_dict(), task_id="t", tenant_id="A", repo_id="r"
    )
    evidence_id = record_verification_evidence(db, rec)
    assert isinstance(evidence_id, int) and evidence_id > 0
    db.close()


def test_capture_attaches_verification_to_candidate(tmp_path):
    from hermes_state import SessionDB

    db = SessionDB(tmp_path / "state.db")
    db.upsert_meta_candidate(
        candidate_id="cand-1", kind="runtime_lesson", claim="prefer X",
        tenant_id="A", repo_id="r", status="proposed",
    )
    capture_verification_for_task(
        db, _passing_gate_dict(), task_id="t",
        tenant_id="A", repo_id="r", candidate_id="cand-1",
    )
    candidate = db.get_meta_candidate("cand-1")
    assert evidence_has_passing_verification(candidate.get("evidence_json")) is True
    db.close()


# ── the actual promotion gate ───────────────────────────────────────────────

def test_approve_blocked_without_verification_when_required(tmp_path):
    """With the gate enabled, judge approval alone cannot promote a candidate."""
    from hermes_state import SessionDB
    from hermes_cli.supervisor_memory import approve_meta_candidate

    db = SessionDB(tmp_path / "state.db")
    db.upsert_meta_candidate(
        candidate_id="cand-noverify", kind="runtime_lesson", claim="prefer X",
        tenant_id="A", repo_id="r", status="proposed",
    )
    result = approve_meta_candidate(
        db, candidate_id="cand-noverify", config={}, require_verification=True
    )
    assert result.status == "blocked"
    assert "verification" in result.notes.lower()
    db.close()


def test_approve_succeeds_with_passing_verification(tmp_path):
    """A candidate carrying passing verification evidence promotes normally."""
    from hermes_state import SessionDB
    from hermes_cli.supervisor_memory import approve_meta_candidate

    db = SessionDB(tmp_path / "state.db")
    db.upsert_meta_candidate(
        candidate_id="cand-ok", kind="runtime_lesson", claim="prefer X",
        tenant_id="A", repo_id="r", status="proposed",
    )
    capture_verification_for_task(
        db, _passing_gate_dict(), task_id="t",
        tenant_id="A", repo_id="r", candidate_id="cand-ok",
    )
    result = approve_meta_candidate(
        db, candidate_id="cand-ok", config={}, require_verification=True
    )
    assert result.status == "approved"
    db.close()


def test_approve_unaffected_when_gate_disabled(tmp_path):
    """Default posture (gate off): approval works without verification evidence."""
    from hermes_state import SessionDB
    from hermes_cli.supervisor_memory import approve_meta_candidate

    db = SessionDB(tmp_path / "state.db")
    db.upsert_meta_candidate(
        candidate_id="cand-legacy", kind="runtime_lesson", claim="prefer X",
        tenant_id="A", repo_id="r", status="proposed",
    )
    result = approve_meta_candidate(
        db, candidate_id="cand-legacy", config={}, require_verification=False
    )
    assert result.status == "approved"
    db.close()


# ── held-out runner (earned, not asserted) ──────────────────────────────────

def _git_repo(tmp_path):
    import subprocess
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    return repo


def _held_out_config(commands):
    return {"supervisor": {"completion_gate": {"held_out_commands": commands}}}


def test_run_held_out_gate_skipped_without_commands(tmp_path):
    from hermes_cli.completion_gate import run_held_out_gate
    repo = _git_repo(tmp_path)
    gate = run_held_out_gate(repo_path=str(repo), config=_held_out_config([]))
    assert gate.status == "skipped"


def test_run_held_out_gate_passes_and_fails(tmp_path):
    from hermes_cli.completion_gate import run_held_out_gate
    repo = _git_repo(tmp_path)
    ok = run_held_out_gate(repo_path=str(repo), config=_held_out_config([["true"]]))
    assert ok.status == "passed" and ok.passed is True
    assert ok.checks[0].name == "held_out"

    bad = run_held_out_gate(repo_path=str(repo), config=_held_out_config([["false"]]))
    assert bad.status == "blocked" and bad.passed is False


def test_held_out_capture_returns_none_without_commands(tmp_path):
    from hermes_state import SessionDB
    repo = _git_repo(tmp_path)
    db = SessionDB(tmp_path / "state.db")
    rec = capture_held_out_verification_for_task(
        db, repo_path=str(repo), task_id="t", config=_held_out_config([])
    )
    assert rec is None  # cannot mint held-out without checks
    db.close()


def test_held_out_capture_earns_held_out_flag_and_satisfies_global_rule(tmp_path):
    """A passing held-out run yields held_out=True that satisfies require_held_out."""
    from hermes_state import SessionDB
    repo = _git_repo(tmp_path)
    db = SessionDB(tmp_path / "state.db")
    db.upsert_meta_candidate(
        candidate_id="cand-ho", kind="runtime_lesson", claim="prefer X",
        tenant_id="A", repo_id="r", status="proposed",
    )
    rec = capture_held_out_verification_for_task(
        db, repo_path=str(repo), task_id="t",
        tenant_id="A", repo_id="r", candidate_id="cand-ho",
        config=_held_out_config([["true"]]),
    )
    assert rec is not None and rec.held_out is True and rec.passed is True
    candidate = db.get_meta_candidate("cand-ho")
    evidence = candidate.get("evidence_json")
    # the global/cross-tenant promotion rule (require_held_out) is now satisfiable
    assert evidence_has_passing_verification(evidence, require_held_out=True) is True
    db.close()


def test_held_out_capture_blocked_run_does_not_satisfy_global_rule(tmp_path):
    from hermes_state import SessionDB
    repo = _git_repo(tmp_path)
    db = SessionDB(tmp_path / "state.db")
    db.upsert_meta_candidate(
        candidate_id="cand-ho-bad", kind="runtime_lesson", claim="prefer X",
        tenant_id="A", repo_id="r", status="proposed",
    )
    rec = capture_held_out_verification_for_task(
        db, repo_path=str(repo), task_id="t",
        tenant_id="A", repo_id="r", candidate_id="cand-ho-bad",
        config=_held_out_config([["false"]]),
    )
    assert rec is not None and rec.held_out is True and rec.passed is False
    candidate = db.get_meta_candidate("cand-ho-bad")
    assert evidence_has_passing_verification(
        candidate.get("evidence_json"), require_held_out=True
    ) is False
    db.close()
