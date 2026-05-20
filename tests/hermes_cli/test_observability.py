import json
import sys
from pathlib import Path
from unittest.mock import patch

from hermes_cli.learning_jobs import record_learning_job
from hermes_cli.observability import (
    ObservabilityFilters,
    build_observability_detail,
    build_evidence_bundle,
    list_observability_items,
    list_runtime_observability_snapshot,
    resolve_observability_line_item_id,
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


def test_observability_lists_and_details_supervisor_task_ledger(tmp_path):
    db = _make_db(tmp_path)
    try:
        from hermes_cli.supervisor_control_plane import (
            create_task_ledger_entry,
            record_worker_heartbeat,
        )

        create_task_ledger_entry(
            db,
            task_id="task_supervisor",
            tenant_id="atlas",
            repo_id="repo-a",
            task_description="Recover a delegated migration task",
            worker_id="codex",
            spec_kit_refs=["specs/001-learning-memory-runtime/tasks.md"],
            git_refs=["branch:132-learning-memory-runtime"],
            goal="recover delegated migration with validation evidence",
            metadata={"supervisor_packet_ref": "packet_1"},
        )
        record_worker_heartbeat(
            db,
            task_id="task_supervisor",
            worker_id="codex",
            status="failed",
            progress_signature="same",
            command_signature="pytest",
            error_signature="AssertionError",
        )

        rows = list_observability_items(
            db,
            ObservabilityFilters(tenant_id="atlas", repo_id="repo-a", item_type="supervisor_task"),
        )
        assert [row.id for row in rows] == ["obs_supervisor_task_task_supervisor"]
        assert rows[0].worker_id == "codex"
        assert rows[0].summary_json["goal"]["status"] == "active"

        bundle = build_evidence_bundle(
            db,
            line_item_id="obs_supervisor_task_task_supervisor",
            tenant_id="atlas",
            repo_id="repo-a",
        )
        assert bundle.supervisor_packet_ref == "packet_1"
        assert bundle.speckit_refs == ["specs/001-learning-memory-runtime/tasks.md"]
        assert bundle.branch_refs == ["branch:132-learning-memory-runtime"]
        assert bundle.event_refs[0]["kind"] == "worker_heartbeat"
        assert bundle.validation_refs[0]["kind"] == "task_goal"
        assert bundle.validation_refs[1]["kind"] == "convergence_assessment"
        assert bundle.raw_transcript_included is False
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


def test_runtime_observability_snapshot_filters_rich_fields_and_redacts(tmp_path):
    db = _make_db(tmp_path)
    try:
        active = record_learning_job(
            db,
            job_id="job_active",
            job_type="sidecar",
            status="running",
            owner="worker-a",
            tenant_id="atlas",
            repo_id="repo-a",
            task_id="task-active",
            metrics={
                "title": "Active runtime learning task",
                "task_description": "Summarize runtime learning metadata",
                "worker_status": "running",
                "worker_kind": "codex",
                "model": "gpt-5",
                "provider": "openai",
                "route": "cheap_reasoning",
                "speckit_refs": ["specs/001-learning-memory-runtime/spec.md"],
                "architecture_refs": ["docs/runtime-learning-enforcement.md"],
                "task_list_refs": ["specs/001-learning-memory-runtime/tasks.md#T101"],
                "memory_refs": [{"id": "mem-active", "kind": "wiki_claim"}],
                "cost_summary": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15, "cost_usd": 0.02},
                "latency_summary": {"wall_time_ms": 1200, "duration_ms": 1200},
                "raw_transcript": "operator pasted password=super-secret-value",
                "api_key": "sk-thisShouldNeverLeak1234567890",
            },
        )
        historical = record_learning_job(
            db,
            job_id="job_historical",
            job_type="judge",
            status="blocked",
            owner="worker-b",
            tenant_id="atlas",
            repo_id="repo-a",
            task_id="task-historical",
            metrics={
                "title": "Historical blocked task",
                "worker_status": "blocked",
                "worker_kind": "sidecar",
                "model": "local-detector",
                "provider": "none",
                "blocker_status": "blocked",
                "completion_status": "blocked",
                "blocker": "waiting for validation evidence",
            },
            error={"message": "blocked because validation evidence is missing"},
        )
        record_learning_job(
            db,
            job_id="job_other_repo",
            job_type="judge",
            status="completed",
            owner="worker-a",
            tenant_id="atlas",
            repo_id="repo-b",
            task_id="task-other",
            metrics={"title": "Wrong repo", "worker_status": "running"},
        )
        db._execute_write(
            lambda conn: conn.execute(
                "UPDATE hermes_learning_jobs SET created_at = ?, updated_at = ? WHERE id = ?",
                (1000.0, 1010.0, "job_active"),
            )
        )
        db._execute_write(
            lambda conn: conn.execute(
                "UPDATE hermes_learning_jobs SET created_at = ?, updated_at = ? WHERE id = ?",
                (2000.0, 2010.0, "job_historical"),
            )
        )

        snapshot = list_runtime_observability_snapshot(
            db,
            ObservabilityFilters(
                tenant_id="atlas",
                repo_id="repo-a",
                worker_status="running",
                date_from=900.0,
                date_to=1500.0,
                limit=10,
            ),
        )

        assert [item["job_id"] for item in snapshot["items"]] == [active.id]
        item = snapshot["items"][0]
        assert item["tenant_id"] == "atlas"
        assert item["repo_id"] == "repo-a"
        assert item["task_id"] == "task-active"
        assert item["task_description"] == "Summarize runtime learning metadata"
        assert item["worker"]["id"] == "worker-a"
        assert item["worker"]["kind"] == "codex"
        assert item["worker"]["status"] == "running"
        assert item["model"]["provider"] == "openai"
        assert item["model"]["model"] == "gpt-5"
        assert item["spec_kit_refs"] == ["specs/001-learning-memory-runtime/spec.md"]
        assert item["architecture_refs"] == ["docs/runtime-learning-enforcement.md"]
        assert item["task_list_refs"] == ["specs/001-learning-memory-runtime/tasks.md#T101"]
        assert item["memory_refs"] == [{"id": "mem-active", "kind": "wiki_claim"}]
        assert item["completion_status"] == "running"
        assert item["blocker_status"] == "none"
        assert item["cost_summary"]["total_tokens"] == 15
        assert item["latency_summary"]["wall_time_ms"] == 1200
        assert "super-secret-value" not in json.dumps(item)
        assert "raw_transcript" not in json.dumps(item)
        assert "sk-thisShouldNeverLeak" not in json.dumps(item)

        blocked = list_runtime_observability_snapshot(
            db,
            ObservabilityFilters(
                tenant_id="atlas",
                repo_id="repo-a",
                completion_status="blocked",
                blocker="validation evidence",
                limit=10,
            ),
        )
        assert [item["job_id"] for item in blocked["items"]] == [historical.id]
        assert blocked["items"][0]["blocker_status"] == "blocked"
        assert blocked["items"][0]["completion_status"] == "blocked"
    finally:
        db.close()


def test_runtime_observability_drilldown_by_job_and_task_id_redacts_bundle(tmp_path):
    db = _make_db(tmp_path)
    try:
        from hermes_cli.supervisor_control_plane import create_task_ledger_entry, record_worker_heartbeat

        job = record_learning_job(
            db,
            job_id="job_detail",
            job_type="wiki",
            status="failed",
            owner="worker-detail",
            tenant_id="atlas",
            repo_id="repo-a",
            task_id="task-detail",
            metrics={
                "task_description": "Build detail DTO",
                "artifact_refs": [{"id": "artifact-1", "raw_transcript": "token=secret-token-value"}],
                "memory_refs": [{"id": "mem-detail"}],
            },
            error={"message": "provider token leaked: sk-thisShouldNeverLeak1234567890"},
        )
        create_task_ledger_entry(
            db,
            task_id="task-ledger",
            tenant_id="atlas",
            repo_id="repo-a",
            task_description="Ledger detail DTO",
            worker_id="worker-ledger",
            worker_kind="codex",
            spec_kit_refs=["specs/001-learning-memory-runtime/plan.md"],
            git_refs=["branch:132-learning-memory-runtime"],
            metadata={
                "architecture_refs": ["docs/curator-policy-framework-architecture.md"],
                "task_list_refs": ["specs/001-learning-memory-runtime/tasks.md#T108"],
                "raw_transcript": "password=ledger-secret",
            },
        )
        record_worker_heartbeat(
            db,
            task_id="task-ledger",
            worker_id="worker-ledger",
            status="blocked",
            error_signature="validation failed",
            metadata={"memory_packet_id": "mempkt-ledger", "api_key": "sk-thisShouldNeverLeak1234567890"},
        )

        assert resolve_observability_line_item_id(db, job_id=job.id) == f"obs_job_{job.id}"
        assert resolve_observability_line_item_id(db, task_id="task-ledger") == "obs_supervisor_task_task-ledger"

        job_detail = build_observability_detail(db, job_id=job.id, tenant_id="atlas", repo_id="repo-a").to_dict()
        task_detail = build_observability_detail(db, task_id="task-ledger", tenant_id="atlas", repo_id="repo-a").to_dict()

        assert job_detail["line_item"]["job_id"] == job.id
        assert job_detail["evidence_bundle"]["line_item_id"] == f"obs_job_{job.id}"
        assert task_detail["line_item"]["task_id"] == "task-ledger"
        assert task_detail["line_item"]["worker"]["status"] == "running"
        assert task_detail["evidence_bundle"]["speckit_refs"] == ["specs/001-learning-memory-runtime/plan.md"]
        assert task_detail["evidence_bundle"]["memory_refs"][0]["id"] == "mempkt-ledger"
        combined = json.dumps([job_detail, task_detail], sort_keys=True)
        assert "secret-token-value" not in combined
        assert "ledger-secret" not in combined
        assert "sk-thisShouldNeverLeak" not in combined
        assert '"raw_transcript":' not in combined
        assert job_detail["evidence_bundle"]["raw_transcript_included"] is False
        assert task_detail["evidence_bundle"]["secret_safe"] is True
    finally:
        db.close()


def test_runtime_scoped_ask_is_deterministic_metadata_only(tmp_path):
    db = _make_db(tmp_path)
    try:
        job = record_learning_job(
            db,
            job_id="job_ask",
            job_type="judge",
            status="blocked",
            owner="worker-ask",
            tenant_id="atlas",
            repo_id="repo-a",
            task_id="task-ask",
            metrics={
                "task_description": "Explain blocked runtime job",
                "blocker": "validation gate blocked",
                "worker_status": "blocked",
                "completion_status": "blocked",
                "cost_summary": {"total_tokens": 42, "cost_usd": 0.5},
                "latency_summary": {"duration_ms": 321},
                "memory_refs": [{"id": "mem-ask", "kind": "candidate"}],
            },
        )

        result = scoped_analysis(
            db,
            job_id=job.id,
            question="Why is this blocked and what evidence exists?",
            tenant_id="atlas",
            repo_id="repo-a",
        ).to_dict()

        assert result["llm_calls"] == []
        assert result["mutation_allowed"] is False
        assert f"obs_job_{job.id}" in result["citations"]
        assert "validation gate blocked" in result["answer"]
        assert "completion=blocked" in result["answer"]
        assert "total_tokens=42" in result["answer"]
        assert "duration_ms=321" in result["answer"]
        assert "mem-ask" in result["answer"]
    finally:
        db.close()


def test_observability_cli_rich_json_filters_and_direct_drilldown(tmp_path, monkeypatch, capsys):
    home = tmp_path / ".hermes"
    monkeypatch.setenv("HERMES_HOME", str(home))
    import hermes_state

    monkeypatch.setattr(hermes_state, "DEFAULT_DB_PATH", home / "state.db")
    db = SessionDB()
    try:
        job = record_learning_job(
            db,
            job_id="job_cli_rich",
            job_type="sidecar",
            status="running",
            owner="worker-cli",
            tenant_id="atlas",
            repo_id="repo-a",
            task_id="task-cli-rich",
            metrics={
                "title": "CLI rich observable job",
                "worker_status": "running",
                "model": "gpt-5",
                "provider": "openai",
                "completion_status": "running",
                "cost_summary": {"total_tokens": 9},
            },
        )
        db._execute_write(
            lambda conn: conn.execute(
                "UPDATE hermes_learning_jobs SET created_at = ?, updated_at = ? WHERE id = ?",
                (1000.0, 1001.0, job.id),
            )
        )
    finally:
        db.close()

    from hermes_cli import main as hermes_main

    with patch.object(
        sys,
        "argv",
        [
            "hermes",
            "memory",
            "observe",
            "list",
            "--tenant-id",
            "atlas",
            "--repo-id",
            "repo-a",
            "--worker-status",
            "running",
            "--date-from",
            "900",
            "--date-to",
            "1200",
            "--json",
        ],
    ):
        hermes_main.main()
    rows = json.loads(capsys.readouterr().out)
    assert rows[0]["job_id"] == job.id
    assert rows[0]["worker"]["status"] == "running"
    assert rows[0]["model"]["model"] == "gpt-5"

    with patch.object(
        sys,
        "argv",
        ["hermes", "memory", "observe", "detail", "--job-id", job.id, "--tenant-id", "atlas", "--json"],
    ):
        hermes_main.main()
    detail = json.loads(capsys.readouterr().out)
    assert detail["line_item"]["job_id"] == job.id
    assert detail["evidence_bundle"]["line_item_id"] == f"obs_job_{job.id}"

    with patch.object(
        sys,
        "argv",
        [
            "hermes",
            "memory",
            "observe",
            "ask",
            "--job-id",
            job.id,
            "--question",
            "Summarize cost",
            "--tenant-id",
            "atlas",
            "--json",
        ],
    ):
        hermes_main.main()
    answer = json.loads(capsys.readouterr().out)
    assert answer["llm_calls"] == []
    assert "total_tokens=9" in answer["answer"]
