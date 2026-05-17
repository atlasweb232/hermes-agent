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
    memory_tier_for_candidate,
    monitor_learning,
    reject_meta_candidate,
    reconcile_learning_candidates,
    retrieve_learning_context,
    run_candidate_housekeeping,
    run_learning_sidecar,
    rollup_learning_candidates,
)
from hermes_state import SessionDB


def _make_db(tmp_path: Path) -> SessionDB:
    return SessionDB(db_path=tmp_path / "state.db")


def _set_candidate_created_at(db: SessionDB, candidate_id: str, timestamp: float) -> None:
    def _do(conn):
        conn.execute(
            """
            UPDATE hermes_meta_candidates
               SET created_at = ?, updated_at = ?
             WHERE id = ?
            """,
            (timestamp, timestamp, candidate_id),
        )

    db._execute_write(_do)


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


def test_memory_tiers_use_age_and_confidence(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    monkeypatch.setenv("HERMES_HOME", str(home))
    now = 1_000_000.0
    config = {
        "supervisor": {
            "memory_tiers": {
                "enabled": True,
                "hot_ttl_seconds": 100,
                "warm_min_confidence": 0.6,
                "cold_min_confidence": 0.85,
            }
        }
    }

    assert memory_tier_for_candidate({"score": 0.7, "updated_at": now - 50}, config=config, now=now) == "hot"
    assert memory_tier_for_candidate({"score": 0.7, "updated_at": now - 500}, config=config, now=now) == "warm"
    assert memory_tier_for_candidate({"score": 0.9, "updated_at": now - 500}, config=config, now=now) == "cold"


def test_retrieve_learning_context_honors_tenant_repo_scope(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    monkeypatch.setenv("HERMES_HOME", str(home))
    db = _make_db(home)
    try:
        db.upsert_meta_candidate(
            candidate_id="metacand_good_scope",
            kind="routing_hint",
            claim="Use direct claude after worker-router claude failures",
            evidence_json={"failed_path": "worker-router claude", "working_path": "claude --model sonnet -p"},
            score=0.95,
            status="approved",
            tenant_id="atlas",
            repo_id="hermes-agent",
        )
        db.upsert_meta_candidate(
            candidate_id="metacand_bad_scope",
            kind="routing_hint",
            claim="Use unrelated claude memory",
            evidence_json={"failed_path": "worker-router claude", "working_path": "claude other"},
            score=0.99,
            status="approved",
            tenant_id="other",
            repo_id="other-repo",
        )

        result = retrieve_learning_context(
            db,
            query="worker-router claude failed",
            tenant_id="atlas",
            repo_id="hermes-agent",
            config={"supervisor": {"learning": {"injection": {"enabled": True, "min_score": 0.5}}}},
        )

        ids = [candidate["id"] for candidate in result["candidates"]]
        assert "metacand_good_scope" in ids
        assert "metacand_bad_scope" not in ids
        assert result["packet"]["header"].startswith("ADVISORY MEMORY ONLY")
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


def test_learning_rollup_skips_tool_routing_lessons_for_curator(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    monkeypatch.setenv("HERMES_HOME", str(home))
    db = _make_db(home)
    try:
        db.upsert_memory_record(
            record_id="memrec_tool_routing",
            kind="tool_routing_lesson",
            title="Claude Code direct invocation works after worker-router failures",
            body="worker-router claude failed and claude -p worked",
            payload_json={"failed_path": "worker-router claude"},
            status="active",
            score=0.9,
            tenant_id="atlas",
            repo_id="atlas-email-flutter",
        )

        result = rollup_learning_candidates(
            db,
            tenant_id="atlas",
            repo_id="atlas-email-flutter",
        )

        assert result.status == "completed"
        assert result.records_scanned == 1
        assert result.candidates_created == 0
        assert db.list_meta_candidates(repo_id="atlas-email-flutter", limit=10) == []
    finally:
        db.close()


def test_learning_rollup_does_not_resurrect_archived_candidate(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    monkeypatch.setenv("HERMES_HOME", str(home))
    db = _make_db(home)
    try:
        db.upsert_memory_record(
            record_id="rec-archived-source",
            kind="claim",
            title="Archived routing lesson",
            body="Use the old route",
            payload_json={"source": "test"},
            status="active",
            score=0.9,
            tenant_id="atlas",
            repo_id="atlas-email-flutter",
        )
        first = rollup_learning_candidates(
            db,
            tenant_id="atlas",
            repo_id="atlas-email-flutter",
        )
        assert first.candidates_created == 1
        candidate = db.list_meta_candidates(repo_id="atlas-email-flutter", limit=1)[0]
        db.update_meta_candidate_status(
            candidate["id"],
            status="archived",
            evidence_json={"reason": "operator cleanup"},
        )

        second = rollup_learning_candidates(
            db,
            tenant_id="atlas",
            repo_id="atlas-email-flutter",
        )

        row = db.get_meta_candidate(candidate["id"])
        assert row["status"] == "archived"
        assert second.candidates_updated == 0
        assert second.metrics["skipped"]["existing_candidate_status:archived"] == 1
    finally:
        db.close()


def test_learning_rollup_skips_noisy_kanban_task_outcomes(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    monkeypatch.setenv("HERMES_HOME", str(home))
    db = _make_db(home)
    try:
        db.upsert_memory_record(
            record_id="kanban_event_noise",
            kind="task_outcome",
            title="completed: prior #3",
            body="task completed",
            payload_json={
                "event_kind": "completed",
                "task_id": "t_noise",
                "memory_packet_id": "mempkt_noise",
            },
            status="active",
            score=0.8,
            tenant_id=None,
            repo_id=None,
            packet_id="mempkt_noise",
            evidence_uri="kanban://task/t_noise/event/1",
        )

        result = rollup_learning_candidates(db)

        assert result.candidates_created == 0
        assert result.metrics["skipped"]["synthetic_marker"] == 1
        assert db.list_meta_candidates(limit=10) == []
    finally:
        db.close()


def test_learning_rollup_requires_memory_packet_for_task_outcome(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    monkeypatch.setenv("HERMES_HOME", str(home))
    db = _make_db(home)
    try:
        db.upsert_memory_record(
            record_id="kanban_event_missing_packet",
            kind="task_outcome",
            title="completed: useful branch audit",
            body="task completed",
            payload_json={
                "event_kind": "completed",
                "task_id": "t_useful",
            },
            status="active",
            score=0.8,
            evidence_uri="kanban://task/t_useful/event/1",
        )

        result = rollup_learning_candidates(db)

        assert result.candidates_created == 0
        assert result.metrics["skipped"]["task_outcome_missing_memory_packet"] == 1
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


def test_reconcile_learning_candidates_promotes_threshold_hits(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    monkeypatch.setenv("HERMES_HOME", str(home))
    db = _make_db(home)
    try:
        db.upsert_memory_packet(
            packet_id="mempkt_ready",
            query="oauth callback",
            status="ready",
            tenant_id="atlas",
            repo_id="atlas-email-flutter",
            scopes=["atlas-email-flutter"],
            claims_json=[{"record_id": "rec-1", "title": "claim", "score": 0.9}],
            evidence_json=[{"uri": "artifact://evidence.txt"}],
            contradictions_json=[],
            freshness_json={"policy": "fresh"},
            confidence=0.9,
            source="test",
            expires_at=None,
        )
        db.upsert_meta_candidate(
            candidate_id="metacand_promote",
            kind="routing_hint",
            claim="Use aws oauth callback",
            evidence_json={
                "record_id": "rec-promote",
                "match": "oauth callback",
                "assignee": "jules",
                "workspace_kind": "scratch",
            },
            score=0.95,
            status="proposed",
            tenant_id="atlas",
            repo_id="atlas-email-flutter",
        )

        result = reconcile_learning_candidates(
            db,
            tenant_id="atlas",
            repo_id="atlas-email-flutter",
        )
        assert result.status == "completed"
        assert result.promoted >= 1
        row = db.get_meta_candidate("metacand_promote")
        assert row["status"] == "approved"
    finally:
        db.close()


def test_reconcile_does_not_promote_unvalidated_command_repair_policy(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    monkeypatch.setenv("HERMES_HOME", str(home))
    db = _make_db(home)
    try:
        db.upsert_memory_packet(
            packet_id="mempkt_ready",
            query="claude repair",
            status="ready",
            tenant_id="atlas",
            repo_id="atlas-email-flutter",
            scopes=["atlas-email-flutter"],
            claims_json=[{"record_id": "rec-1", "title": "claim", "score": 0.9}],
            evidence_json=[{"uri": "artifact://evidence.txt"}],
            contradictions_json=[],
            freshness_json={"policy": "fresh"},
            confidence=0.9,
            source="test",
            expires_at=None,
        )
        db.upsert_meta_candidate(
            candidate_id="curpol_no_validation",
            kind="command_repair_policy",
            claim="Prefer direct claude",
            evidence_json={"source_record_id": "memrec_1"},
            score=0.95,
            status="proposed",
            tenant_id="atlas",
            repo_id="atlas-email-flutter",
        )

        result = reconcile_learning_candidates(
            db,
            tenant_id="atlas",
            repo_id="atlas-email-flutter",
        )

        assert result.status == "completed"
        assert result.promoted == 0
        row = db.get_meta_candidate("curpol_no_validation")
        assert row["status"] == "proposed"
    finally:
        db.close()


def test_approve_meta_candidate_preserves_validation_payload(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    monkeypatch.setenv("HERMES_HOME", str(home))
    db = _make_db(home)
    try:
        evidence = {
            "source_record_id": "memrec_1",
            "validation": {
                "status": "valid",
                "eligible_for_approval": True,
                "approved_for_enforcement": False,
                "warnings": [],
                "errors": [],
            },
        }
        db.upsert_meta_candidate(
            candidate_id="curpol_validated",
            kind="command_repair_policy",
            claim="Prefer direct claude",
            evidence_json=evidence,
            score=0.95,
            status="proposed",
            tenant_id="atlas",
            repo_id="atlas-email-flutter",
        )

        result = approve_meta_candidate(db, candidate_id="curpol_validated")

        assert result.status == "approved"
        row = db.get_meta_candidate("curpol_validated")
        assert row["status"] == "approved"
        assert row["evidence_json"]["source_record_id"] == "memrec_1"
        assert row["evidence_json"]["validation"]["eligible_for_approval"] is True
        assert row["evidence_json"]["validation"]["approved_for_enforcement"] is False
        assert row["evidence_json"]["approved_at"]
        assert row["evidence_json"]["actions"]
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


def test_reconcile_learning_candidates_rolls_back_degraded_apply(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    monkeypatch.setenv("HERMES_HOME", str(home))
    db = _make_db(home)
    try:
        db.upsert_memory_packet(
            packet_id="mempkt_blocked",
            query="oauth callback",
            status="blocked",
            tenant_id="atlas",
            repo_id="atlas-email-flutter",
            scopes=["atlas-email-flutter"],
            claims_json=[],
            evidence_json=[],
            contradictions_json=[],
            freshness_json={"policy": "weak"},
            confidence=0.1,
            source="test",
            expires_at=None,
        )
        db.upsert_meta_candidate(
            candidate_id="metacand_rollback",
            kind="routing_hint",
            claim="Use oauth.atlasweb.info for AWS callbacks",
            evidence_json={
                "record_id": "rec-rollback",
                "match": "oauth callback",
                "assignee": "jules",
                "workspace_kind": "worktree",
            },
            score=0.9,
            status="proposed",
            tenant_id="atlas",
            repo_id="atlas-email-flutter",
        )
        approve_meta_candidate(
            db,
            candidate_id="metacand_rollback",
            apply=True,
            config={"supervisor": {"learning": {}}},
        )

        result = reconcile_learning_candidates(
            db,
            tenant_id="atlas",
            repo_id="atlas-email-flutter",
        )
        assert result.status == "completed"
        assert result.rolled_back >= 1
        row = db.get_meta_candidate("metacand_rollback")
        assert row["status"] == "rolled_back"
    finally:
        db.close()


def test_reconcile_learning_candidates_skips_noisy_kanban_candidate(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    monkeypatch.setenv("HERMES_HOME", str(home))
    db = _make_db(home)
    try:
        db.upsert_memory_packet(
            packet_id="mempkt_ready",
            query="ready",
            status="ready",
            tenant_id=None,
            repo_id=None,
            scopes=["global"],
            claims_json=[],
            evidence_json=[],
            contradictions_json=[],
            freshness_json={},
            confidence=0.9,
            source="test",
            expires_at=None,
        )
        db.upsert_meta_candidate(
            candidate_id="metacand_noisy_reconcile",
            kind="playbook",
            claim="completed: prior #3",
            evidence_json={
                "record_id": "kanban_event_12",
                "packet_id": None,
                "evidence_uri": "kanban://task/t_prior/event/12",
            },
            score=0.9,
            status="proposed",
        )

        result = reconcile_learning_candidates(
            db,
            config={
                "supervisor": {
                    "learning": {
                        "promotion": {"enabled": True, "min_score": 0.7, "min_ready_ratio": 0.1},
                        "rollback": {"enabled": False},
                        "rollup_filters": {},
                    },
                    "monitoring": {"enabled": True, "recent_runs": 20},
                }
            },
        )

        assert result.promoted == 0
        assert result.metrics["promotion_skipped"]["quality_gate:kanban_missing_memory_packet"] == 1
        assert db.get_meta_candidate("metacand_noisy_reconcile")["status"] == "proposed"
    finally:
        db.close()


def test_reconcile_learning_candidates_requires_evidence(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    monkeypatch.setenv("HERMES_HOME", str(home))
    db = _make_db(home)
    try:
        db.upsert_memory_packet(
            packet_id="mempkt_ready",
            query="ready",
            status="ready",
            scopes=["global"],
            claims_json=[],
            evidence_json=[],
            contradictions_json=[],
            freshness_json={},
            confidence=0.9,
            source="test",
            expires_at=None,
        )
        db.upsert_meta_candidate(
            candidate_id="metacand_no_evidence",
            kind="playbook",
            claim="active candidate",
            evidence_json={},
            score=0.9,
            status="proposed",
        )

        result = reconcile_learning_candidates(
            db,
            config={
                "supervisor": {
                    "learning": {
                        "promotion": {"enabled": True, "min_score": 0.7, "min_ready_ratio": 0.1},
                        "rollback": {"enabled": False},
                        "rollup_filters": {},
                    },
                    "monitoring": {"enabled": True, "recent_runs": 20},
                }
            },
        )

        assert result.promoted == 0
        assert result.metrics["promotion_skipped"]["quality_gate:missing_evidence"] == 1
    finally:
        db.close()


def test_retrieve_learning_context_returns_quality_gated_matches(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    monkeypatch.setenv("HERMES_HOME", str(home))
    db = _make_db(home)
    try:
        db.upsert_meta_candidate(
            candidate_id="curpol_claude",
            kind="command_repair_policy",
            claim="Prefer direct Claude Code invocation after wrapper failures",
            evidence_json={
                "policy_type": "command_repair",
                "mode": "advisory",
                "failed_path": "worker-router claude",
                "working_path": "claude --model sonnet -p",
                "source_record_id": "memrec_claude",
            },
            score=0.9,
            status="approved",
        )
        db.upsert_meta_candidate(
            candidate_id="metacand_noise",
            kind="playbook",
            claim="completed: prior #3",
            evidence_json={
                "record_id": "kanban_event_12",
                "packet_id": None,
                "evidence_uri": "kanban://task/t_prior/event/12",
            },
            score=0.9,
            status="approved",
        )

        result = retrieve_learning_context(db, query="ask claude code two plus two")

        assert result["status"] == "ready"
        assert [candidate["id"] for candidate in result["candidates"]] == ["curpol_claude"]
        assert result["metrics"]["skipped"]["quality_gate:synthetic_marker"] == 1
    finally:
        db.close()


def test_retrieve_learning_context_does_not_substring_match_unrelated_tokens(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    monkeypatch.setenv("HERMES_HOME", str(home))
    db = _make_db(home)
    try:
        db.upsert_meta_candidate(
            candidate_id="curpol_claude",
            kind="command_repair_policy",
            claim="Prefer direct Claude Code invocation after worker-router failures",
            evidence_json={
                "policy_type": "command_repair",
                "failed_path": "worker-router claude",
                "working_path": "claude --model sonnet -p",
                "source_record_id": "memrec_claude",
            },
            score=0.9,
            status="approved",
        )
        db.upsert_meta_candidate(
            candidate_id="metacand_oauth",
            kind="routing_hint",
            claim="Use Hermes on AWS callback routes",
            evidence_json={
                "match": "oauth callback",
                "assignee": "jules",
                "workspace_kind": "worktree",
            },
            score=0.8,
            status="approved",
        )

        result = retrieve_learning_context(db, query="oauth callback route")

        ids = [candidate["id"] for candidate in result["candidates"]]
        assert ids == ["metacand_oauth"]
    finally:
        db.close()


def test_learning_sidecar_runs_one_tick(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    monkeypatch.setenv("HERMES_HOME", str(home))
    db = _make_db(home)
    try:
        monitor_calls = []
        reconcile_calls = []
        rollup_calls = []

        def fake_rollup(db_obj, **kwargs):
            rollup_calls.append(kwargs)
            return rollup_learning_candidates(db_obj, **kwargs)

        def fake_monitor(db_obj, **kwargs):
            monitor_calls.append(kwargs)
            return monitor_learning(db_obj, **kwargs)

        def fake_reconcile(db_obj, **kwargs):
            reconcile_calls.append(kwargs)
            return reconcile_learning_candidates(db_obj, **kwargs)

        result = run_learning_sidecar(
            lambda: db,
            tenant_id="atlas",
            repo_id="atlas-email-flutter",
            once=True,
            interval_seconds=0.01,
            rollup_fn=fake_rollup,
            monitor_fn=fake_monitor,
            reconcile_fn=fake_reconcile,
            sleep_fn=lambda _s: None,
        )

        assert result.status in {"completed", "completed_with_errors"}
        assert result.ticks == 1
        assert len(rollup_calls) == 1
        assert len(monitor_calls) == 1
        assert len(reconcile_calls) == 1
        assert result.last_tick is not None
        assert result.last_tick.rollup["status"] in {"completed", "disabled"}
    finally:
        db.close()


def test_cli_learning_sidecar_once_smoke(tmp_path, monkeypatch, capsys):
    home = tmp_path / ".hermes"
    monkeypatch.setenv("HERMES_HOME", str(home))
    argv = [
        "hermes",
        "memory",
        "sidecar",
        "--tenant-id",
        "atlas",
        "--repo-id",
        "atlas-email-flutter",
        "--once",
        "--json",
    ]

    from hermes_cli import main as hermes_main

    with patch.object(sys, "argv", argv):
        hermes_main.main()

    out = capsys.readouterr().out.strip()
    data = json.loads(out)
    assert data["once"] is True
    assert data["ticks"] == 1


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
        assert row["evidence_json"]["record_id"] == "rec-reject"
        assert row["evidence_json"]["actions"]
    finally:
        db.close()


def test_candidate_housekeeping_archives_stale_proposed_candidate(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    monkeypatch.setenv("HERMES_HOME", str(home))
    db = _make_db(home)
    try:
        now = 1_778_000_000.0
        db.upsert_meta_candidate(
            candidate_id="metacand_stale",
            kind="playbook",
            claim="old noisy lesson",
            evidence_json={"record_id": "rec-stale"},
            score=0.3,
            status="proposed",
        )
        _set_candidate_created_at(db, "metacand_stale", now - 3 * 86400)

        result = run_candidate_housekeeping(
            db,
            config={"supervisor": {"learning": {"housekeeping": {"proposed_ttl_days": 1}}}},
            now=now,
        )

        assert result.status == "completed"
        assert result.archived == 1
        row = db.get_meta_candidate("metacand_stale")
        assert row["status"] == "archived"
        assert row["evidence_json"]["record_id"] == "rec-stale"
        assert row["evidence_json"]["previous_status"] == "proposed"
    finally:
        db.close()


def test_candidate_housekeeping_dry_run_does_not_mutate(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    monkeypatch.setenv("HERMES_HOME", str(home))
    db = _make_db(home)
    try:
        now = 1_778_000_000.0
        db.upsert_meta_candidate(
            candidate_id="metacand_preview",
            kind="recovery_hint",
            claim="old recovery hint",
            evidence_json={"record_id": "rec-preview"},
            score=0.2,
            status="proposed",
        )
        _set_candidate_created_at(db, "metacand_preview", now - 5 * 86400)

        result = run_candidate_housekeeping(
            db,
            config={"supervisor": {"learning": {"housekeeping": {"proposed_ttl_days": 1}}}},
            dry_run=True,
            now=now,
        )

        assert result.dry_run is True
        assert result.archived == 0
        assert len(result.items) == 1
        row = db.get_meta_candidate("metacand_preview")
        assert row["status"] == "proposed"
    finally:
        db.close()


def test_candidate_housekeeping_trims_excess_proposed_per_kind(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    monkeypatch.setenv("HERMES_HOME", str(home))
    db = _make_db(home)
    try:
        now = 1_778_000_000.0
        for idx in range(4):
            candidate_id = f"metacand_trim_{idx}"
            db.upsert_meta_candidate(
                candidate_id=candidate_id,
                kind="playbook",
                claim=f"candidate {idx}",
                evidence_json={"record_id": f"rec-{idx}"},
                score=0.4,
                status="proposed",
            )
            _set_candidate_created_at(db, candidate_id, now + idx)

        result = run_candidate_housekeeping(
            db,
            config={
                "supervisor": {
                    "learning": {
                        "housekeeping": {
                            "proposed_ttl_days": 0,
                            "max_candidates_per_kind": 2,
                        }
                    }
                }
            },
            now=now,
        )

        assert result.archived == 2
        assert db.get_meta_candidate("metacand_trim_3")["status"] == "proposed"
        assert db.get_meta_candidate("metacand_trim_2")["status"] == "proposed"
        assert db.get_meta_candidate("metacand_trim_1")["status"] == "archived"
        assert db.get_meta_candidate("metacand_trim_0")["status"] == "archived"
    finally:
        db.close()


def test_candidate_housekeeping_archives_invalid_proposed_kanban_candidate(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    monkeypatch.setenv("HERMES_HOME", str(home))
    db = _make_db(home)
    try:
        db.upsert_meta_candidate(
            candidate_id="metacand_invalid_kanban",
            kind="playbook",
            claim="timed_out: loop forever",
            evidence_json={
                "record_id": "kanban_event_3",
                "packet_id": None,
                "evidence_uri": "kanban://task/t_loop/event/3",
            },
            score=0.4,
            status="proposed",
        )

        result = run_candidate_housekeeping(
            db,
            config={"supervisor": {"learning": {"housekeeping": {}, "rollup_filters": {}}}},
        )

        assert result.archived == 1
        assert "quality gate failed" in result.items[0].reason
        assert db.get_meta_candidate("metacand_invalid_kanban")["status"] == "archived"
    finally:
        db.close()


def test_candidate_housekeeping_archives_invalid_approved_candidate(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    monkeypatch.setenv("HERMES_HOME", str(home))
    db = _make_db(home)
    try:
        db.upsert_meta_candidate(
            candidate_id="metacand_invalid_approved",
            kind="playbook",
            claim="active candidate",
            evidence_json={},
            score=0.8,
            status="approved",
        )

        result = run_candidate_housekeeping(
            db,
            config={"supervisor": {"learning": {"housekeeping": {}, "rollup_filters": {}}}},
        )

        assert result.archived == 1
        assert result.items[0].reason == "quality gate failed: missing_evidence"
        assert db.get_meta_candidate("metacand_invalid_approved")["status"] == "archived"
    finally:
        db.close()


def test_cli_candidates_prune_defaults_to_dry_run(tmp_path, monkeypatch, capsys):
    home = tmp_path / ".hermes"
    monkeypatch.setenv("HERMES_HOME", str(home))
    db = SessionDB()
    try:
        db.upsert_meta_candidate(
            candidate_id="metacand_cli_prune",
            kind="playbook",
            claim="cli prune preview",
            evidence_json={"record_id": "rec-cli-prune"},
            score=0.3,
            status="proposed",
        )
        _set_candidate_created_at(db, "metacand_cli_prune", 1_700_000_000.0)
    finally:
        db.close()

    argv = [
        "hermes",
        "memory",
        "candidates",
        "prune",
        "--proposed-ttl-days",
        "1",
        "--json",
    ]
    from hermes_cli import main as hermes_main

    with patch.object(sys, "argv", argv):
        hermes_main.main()

    data = json.loads(capsys.readouterr().out.strip())
    assert data["dry_run"] is True
    assert data["archived"] == 0
    assert data["items"]

    db = SessionDB()
    try:
        assert db.get_meta_candidate("metacand_cli_prune")["status"] == "proposed"
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


def test_cli_candidates_list_hides_archived_by_default(tmp_path, monkeypatch, capsys):
    home = tmp_path / ".hermes"
    monkeypatch.setenv("HERMES_HOME", str(home))
    db = SessionDB()
    try:
        db.upsert_meta_candidate(
            candidate_id="metacand_visible",
            kind="playbook",
            claim="active candidate",
            evidence_json={},
            score=0.7,
            status="proposed",
        )
        db.upsert_meta_candidate(
            candidate_id="metacand_archived",
            kind="playbook",
            claim="archived candidate",
            evidence_json={},
            score=0.1,
            status="archived",
        )
    finally:
        db.close()

    argv = ["hermes", "memory", "candidates", "list", "--json"]
    from hermes_cli import main as hermes_main

    with patch.object(sys, "argv", argv):
        hermes_main.main()

    rows = json.loads(capsys.readouterr().out.strip())
    ids = {row["id"] for row in rows}
    assert "metacand_visible" in ids
    assert "metacand_archived" not in ids


def test_learning_sidecar_records_jobs_and_metrics(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    monkeypatch.setenv("HERMES_HOME", str(home))

    def factory() -> SessionDB:
        return SessionDB(db_path=home / "state.db")

    result = run_learning_sidecar(
        factory,
        tenant_id="atlas",
        repo_id="hermes-agent",
        config={
            "supervisor": {
                "learning": {
                    "enabled": True,
                    "housekeeping": {"enabled": True, "interval_seconds": 1},
                },
                "monitoring": {"enabled": True, "recent_runs": 20},
                "dreaming": {"enabled": False},
            }
        },
        interval_seconds=1,
        once=True,
    )

    assert result.status == "completed"
    assert result.last_tick is not None
    assert result.last_tick.bus["status"] == "ok"
    assert result.last_tick.housekeeping["metrics"]["run_id"].startswith("hk_")
    assert result.metrics["ticks"] == 1

    from hermes_cli.learning_jobs import list_learning_jobs

    db = factory()
    try:
        jobs = list_learning_jobs(db, tenant_id="atlas", repo_id="hermes-agent", limit=20)
        job_types = {job.job_type for job in jobs}
        assert {
            "learning_sidecar",
            "learning_rollup",
            "learning_reconcile",
            "housekeeping",
        }.issubset(job_types)
        assert all(job.status == "completed" for job in jobs)
    finally:
        db.close()
