"""Tests for the first Hermes supervisor-memory implementation slice."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

from hermes_cli.supervisor_memory import (
    approve_meta_candidate,
    create_memory_packet,
    evaluate_memory_readiness,
    monitor_learning,
    reject_meta_candidate,
    rollup_learning_candidates,
)
from hermes_state import SessionDB


def _make_db(tmp_path: Path) -> SessionDB:
    return SessionDB(db_path=tmp_path / "state.db")


def test_evaluate_memory_readiness_marks_empty_and_persists(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    monkeypatch.setenv("HERMES_HOME", str(home))
    db = _make_db(home)
    try:
        result = evaluate_memory_readiness(
            db,
            query="oauth callback",
            tenant_id="atlas",
            repo_id="atlas-email-flutter",
            required=True,
        )
        assert result.status in {"blocked", "empty"}
        rows = db.list_memory_readiness(repo_id="atlas-email-flutter", limit=5)
        assert rows
        assert rows[0]["reason"] in {"required_packet_missing", "required_packet_missing_but_fallback_allowed"}
    finally:
        db.close()


def test_create_memory_packet_round_trip(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    monkeypatch.setenv("HERMES_HOME", str(home))
    db = _make_db(home)
    try:
        db.upsert_memory_record(
            record_id="rec-1",
            kind="claim",
            title="OAuth callback uses AWS endpoint",
            body="OAuth callback should point at https://oauth.atlasweb.info/auth/microsoft/start",
            payload_json={"source": "repo-note"},
            status="active",
            score=0.9,
            tenant_id="atlas",
            repo_id="atlas-email-flutter",
            evidence_uri="artifact://build-17/log.txt",
            evidence_sha256="abc123",
        )

        packet = create_memory_packet(
            db,
            query="oauth callback",
            tenant_id="atlas",
            repo_id="atlas-email-flutter",
            required=True,
        )

        assert packet.status == "ready"
        assert packet.claims
        assert packet.evidence
        packets = db.list_memory_packets(repo_id="atlas-email-flutter", limit=5)
        assert packets
        assert packets[0]["id"] == packet.packet_id
        assert packets[0]["claims_json"]
    finally:
        db.close()


def test_cli_memory_readiness_json_smoke(tmp_path, monkeypatch, capsys):
    home = tmp_path / ".hermes"
    monkeypatch.setenv("HERMES_HOME", str(home))
    argv = [
        "hermes",
        "memory",
        "readiness",
        "--query",
        "oauth callback",
        "--repo-id",
        "atlas-email-flutter",
        "--required",
        "--json",
    ]

    from hermes_cli import main as hermes_main

    with patch.object(sys, "argv", argv):
        hermes_main.main()

    out = capsys.readouterr().out.strip()
    data = json.loads(out)
    assert data["status"] in {"blocked", "empty"}
    assert data["query"] == "oauth callback"
    assert data["required"] is True


def test_learning_rollup_creates_candidates(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    monkeypatch.setenv("HERMES_HOME", str(home))
    db = _make_db(home)
    try:
        db.upsert_memory_record(
            record_id="rec-learn-1",
            kind="claim",
            title="AWS OAuth redirect routing",
            body="Keep oauth callback on oauth.atlasweb.info and validate redirects",
            payload_json={"source": "task-summary"},
            status="active",
            score=0.9,
            tenant_id="atlas",
            repo_id="atlas-email-flutter",
            evidence_uri="artifact://job-1/log.txt",
        )

        result = rollup_learning_candidates(
            db,
            tenant_id="atlas",
            repo_id="atlas-email-flutter",
        )

        assert result.status == "completed"
        assert result.records_scanned >= 1
        assert result.candidates_created >= 1
        candidates = db.list_meta_candidates(repo_id="atlas-email-flutter", limit=10)
        assert candidates
        assert candidates[0]["kind"] in {"routing_hint", "validation_recipe", "hook_rule", "memory_rule", "recovery_hint", "playbook"}
        runs = db.list_learning_runs(repo_id="atlas-email-flutter", limit=10)
        assert runs
        assert runs[0]["status"] == "completed"
    finally:
        db.close()


def test_learning_monitor_reports_metrics(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    monkeypatch.setenv("HERMES_HOME", str(home))
    db = _make_db(home)
    try:
        db.record_learning_run(
            run_id="learn_test",
            tenant_id="atlas",
            repo_id="atlas-email-flutter",
            status="completed",
            metrics_json={"ready_ratio": 1.0},
            notes="test",
        )
        db.upsert_meta_candidate(
            candidate_id="metacand_test",
            kind="routing_hint",
            claim="Use aws oauth callback",
            evidence_json={"record_id": "rec-1"},
            score=0.8,
            status="proposed",
            tenant_id="atlas",
            repo_id="atlas-email-flutter",
        )
        result = monitor_learning(
            db,
            tenant_id="atlas",
            repo_id="atlas-email-flutter",
        )
        assert result.status in {"healthy", "degraded"}
        assert result.runs_observed >= 1
        assert result.candidates_observed >= 1
    finally:
        db.close()


def test_approve_meta_candidate_applies_to_config(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    monkeypatch.setenv("HERMES_HOME", str(home))
    db = _make_db(home)
    try:
        db.upsert_meta_candidate(
            candidate_id="metacand_apply",
            kind="routing_hint",
            claim="Use oauth.atlasweb.info for AWS callbacks",
            evidence_json={
                "record_id": "rec-apply",
                "match": "oauth callback",
                "assignee": "jules",
                "workspace_kind": "worktree",
            },
            score=0.8,
            status="proposed",
            tenant_id="atlas",
            repo_id="atlas-email-flutter",
        )

        result = approve_meta_candidate(
            db,
            candidate_id="metacand_apply",
            apply=True,
            config={"supervisor": {"learning": {}}},
        )

        assert result.status == "applied"
        assert result.applied is True
        assert "supervisor.learning.routing_hints" in result.config_targets
        row = db.get_meta_candidate("metacand_apply")
        assert row["status"] == "applied"

        from hermes_cli.config import load_config

        cfg = load_config()
        learning = cfg["supervisor"]["learning"]
        assert learning["approved_candidates"]
        assert learning["applied_candidates"]
        assert learning["routing_hints"]
        hint = learning["routing_hints"][0]
        assert hint["match"] == "oauth callback"
        assert hint["assignee"] == "jules"
        assert hint["workspace_kind"] == "worktree"
        assert hint["evidence_json"]["record_id"] == "rec-apply"
    finally:
        db.close()


def test_reject_meta_candidate_marks_status(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    monkeypatch.setenv("HERMES_HOME", str(home))
    db = _make_db(home)
    try:
        db.upsert_meta_candidate(
            candidate_id="metacand_reject",
            kind="validation_recipe",
            claim="Run pytest before deploy",
            evidence_json={"record_id": "rec-reject"},
            score=0.4,
            status="proposed",
            tenant_id="atlas",
            repo_id="atlas-email-flutter",
        )

        result = reject_meta_candidate(db, candidate_id="metacand_reject")
        assert result.status == "rejected"
        row = db.get_meta_candidate("metacand_reject")
        assert row["status"] == "rejected"
    finally:
        db.close()


def test_cli_candidates_list_renders_structured_fields(tmp_path, monkeypatch, capsys):
    home = tmp_path / ".hermes"
    monkeypatch.setenv("HERMES_HOME", str(home))
    db = SessionDB()
    try:
        db.upsert_meta_candidate(
            candidate_id="metacand_list",
            kind="routing_hint",
            claim="Use Hermes on AWS callback routes",
            evidence_json={
                "match": "oauth callback",
                "assignee": "jules",
                "workspace_kind": "worktree",
            },
            score=0.7,
            status="approved",
            tenant_id="atlas",
            repo_id="atlas-email-flutter",
        )
    finally:
        db.close()

    argv = [
        "hermes",
        "memory",
        "candidates",
        "list",
        "--repo-id",
        "atlas-email-flutter",
    ]
    from hermes_cli import main as hermes_main

    with patch.object(sys, "argv", argv):
        hermes_main.main()

    out = capsys.readouterr().out
    assert "metacand_list" in out
    assert "match=oauth callback" in out
    assert "assignee=jules" in out
    assert "workspace=worktree" in out
