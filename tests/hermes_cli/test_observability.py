import json
import sys
from pathlib import Path
from unittest.mock import patch

from hermes_cli.learning_jobs import record_learning_job
from hermes_cli.observability import (
    ObservabilityFilters,
    build_evidence_bundle,
    list_observability_items,
    scoped_analysis,
)
from hermes_state import SessionDB


def _make_db(tmp_path: Path) -> SessionDB:
    return SessionDB(db_path=tmp_path / "state.db")


def test_observability_lists_jobs_and_candidates_by_tenant_scope(tmp_path):
    db = _make_db(tmp_path)
    try:
        job = record_learning_job(
            db,
            job_type="judge",
            status="running",
            owner="codex",
            tenant_id="atlas",
            repo_id="repo-a",
            task_id="task-1",
            metrics={
                "title": "Review migration task",
                "task_description": "Review a tenant migration task",
                "initial_assignment": {"worker": "codex"},
                "validation_refs": [{"id": "val-1", "status": "pending"}],
            },
        )
        record_learning_job(
            db,
            job_type="judge",
            status="running",
            owner="codex",
            tenant_id="other",
            repo_id="repo-a",
            task_id="task-1",
            metrics={"title": "Wrong tenant"},
        )
        db.upsert_meta_candidate(
            candidate_id="metacand_policy",
            tenant_id="atlas",
            repo_id="repo-a",
            kind="routing_hint",
            claim="Prefer direct Claude for this tenant scope",
            status="proposed",
            score=0.8,
            evidence_json={"task_id": "task-1", "validation": {"status": "valid"}},
        )

        rows = list_observability_items(
            db,
            ObservabilityFilters(tenant_id="atlas", repo_id="repo-a", limit=10),
        )

        assert {row.id for row in rows} == {f"obs_job_{job.id}", "obs_candidate_metacand_policy"}
        assert all(row.tenant_id == "atlas" for row in rows)
    finally:
        db.close()


def test_observability_detail_and_ask_are_scoped_and_read_only(tmp_path):
    db = _make_db(tmp_path)
    try:
        job = record_learning_job(
            db,
            job_type="wiki",
            status="completed",
            owner="codex",
            tenant_id="atlas",
            repo_id="repo-a",
            task_id="task-1",
            metrics={
                "task_description": "Compile memory wiki for migration task",
                "initial_assignment": {"worker": "codex", "role": "curator"},
                "speckit_refs": ["specs/132-learning-memory-runtime/tasks.md"],
                "branch_refs": ["132-learning-memory-runtime"],
                "validation_refs": [{"id": "pytest", "status": "passed"}],
                "memory_packet_id": "mempkt_1",
            },
        )
        line_item_id = f"obs_job_{job.id}"

        bundle = build_evidence_bundle(
            db,
            line_item_id=line_item_id,
            tenant_id="atlas",
            repo_id="repo-a",
        )
        assert bundle.task_description == "Compile memory wiki for migration task"
        assert bundle.raw_transcript_included is False
        assert bundle.secret_safe is True
        assert bundle.initial_assignment["worker"] == "codex"

        result = scoped_analysis(
            db,
            line_item_id=line_item_id,
            question="What is blocked?",
            tenant_id="atlas",
            repo_id="repo-a",
            repo_query_allowed=True,
            repo_path=str(tmp_path),
        )
        assert result.mutation_allowed is False
        assert result.repo_query_mode == "read_only"
        assert line_item_id in result.citations
        assert "Mutation authority: disabled" in result.answer
    finally:
        db.close()


def test_observability_rejects_cross_tenant_detail(tmp_path):
    db = _make_db(tmp_path)
    try:
        job = record_learning_job(
            db,
            job_type="judge",
            status="running",
            tenant_id="atlas",
            repo_id="repo-a",
        )
        try:
            build_evidence_bundle(db, line_item_id=f"obs_job_{job.id}", tenant_id="other")
            assert False, "expected scope rejection"
        except PermissionError:
            pass
    finally:
        db.close()


def test_observability_cli_list_detail_and_ask_json(tmp_path, monkeypatch, capsys):
    home = tmp_path / ".hermes"
    monkeypatch.setenv("HERMES_HOME", str(home))
    import hermes_state

    monkeypatch.setattr(hermes_state, "DEFAULT_DB_PATH", home / "state.db")
    db = SessionDB()
    try:
        job = record_learning_job(
            db,
            job_type="judge",
            status="running",
            owner="codex",
            tenant_id="atlas",
            repo_id="repo-a",
            task_id="task-1",
            metrics={"title": "CLI observable job"},
        )
    finally:
        db.close()

    from hermes_cli import main as hermes_main

    with patch.object(
        sys,
        "argv",
        ["hermes", "memory", "observe", "list", "--tenant-id", "atlas", "--repo-id", "repo-a", "--json"],
    ):
        hermes_main.main()
    rows = json.loads(capsys.readouterr().out)
    assert rows[0]["id"] == f"obs_job_{job.id}"

    with patch.object(
        sys,
        "argv",
        ["hermes", "memory", "observe", "detail", f"obs_job_{job.id}", "--tenant-id", "atlas", "--json"],
    ):
        hermes_main.main()
    detail = json.loads(capsys.readouterr().out)
    assert detail["line_item_id"] == f"obs_job_{job.id}"

    with patch.object(
        sys,
        "argv",
        [
            "hermes",
            "memory",
            "observe",
            "ask",
            f"obs_job_{job.id}",
            "--question",
            "What is this?",
            "--tenant-id",
            "atlas",
            "--json",
        ],
    ):
        hermes_main.main()
    answer = json.loads(capsys.readouterr().out)
    assert answer["mutation_allowed"] is False
