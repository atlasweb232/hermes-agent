import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from hermes_cli.goal_allocator import (
    WorkerAllocationPlan,
    WorkerAttemptResult,
    WorkerHealth,
    load_worker_health,
    save_allocation_plan,
    save_worker_attempt,
    save_worker_health,
)
from hermes_cli.self_healing_workflow import (
    SupervisorContextGate,
    TaskGraph,
    TaskNode,
    complete_task_graph,
    create_task_graph,
    dispatch_ready_nodes,
    get_task_graph,
    list_worker_progress_events,
    list_recovery_actions,
    list_task_graphs,
    project_worker_progress_for_delivery,
    recovery_status,
    record_runtime_lease,
    run_progress_summarizer_sidecar,
    run_worker_with_progress_events,
    run_health_check_once,
    run_restart_recovery,
    update_task_node,
)
from hermes_cli.supervisor_control_plane import (
    create_task_ledger_entry,
    record_worker_heartbeat,
)
from hermes_state import SessionDB


def _db(tmp_path: Path) -> SessionDB:
    return SessionDB(db_path=tmp_path / "state.db")


def _graph(**overrides) -> TaskGraph:
    data = {
        "graph_id": "graph_1",
        "session_id": "session_1",
        "tenant_id": "atlas",
        "repo_id": "repo-a",
        "root_task_id": "task_root",
        "concurrency_limit": 2,
        "source": "chat",
    }
    data.update(overrides)
    return TaskGraph(**data)


def _node(task_id: str, **overrides) -> TaskNode:
    data = {
        "task_id": task_id,
        "graph_id": "graph_1",
        "title": task_id,
        "objective": f"finish {task_id}",
        "owned_paths": [f"hermes_cli/{task_id}.py"],
        "validation_required": True,
        "supervisor_accepted": True,
    }
    data.update(overrides)
    return TaskNode(**data)


def test_task_graph_and_node_schema_validate_status_dependencies_ownership_and_supervisor_acceptance():
    graph = _graph()
    first = _node("task_a", priority=2)
    second = _node("task_b", dependencies=["task_a"], priority=1)

    payload = TaskGraph.from_json(graph.to_json()).to_dict()
    assert payload["goal_key"] == "goal:session_1"
    assert payload["status"] == "active"
    assert [node.task_id for node in sorted([second, first], key=lambda item: (item.priority, item.task_id))] == [
        "task_b",
        "task_a",
    ]

    with pytest.raises(ValueError, match="invalid graph status"):
        _graph(status="running")
    with pytest.raises(ValueError, match="concurrency_limit"):
        _graph(concurrency_limit=0)
    with pytest.raises(ValueError, match="invalid task node status"):
        _node("task_x", status="done")
    with pytest.raises(ValueError, match="owned_paths"):
        _node("task_write", owned_paths=[], read_only=False)
    assert _node("task_read", owned_paths=[], read_only=True).read_only is True
    with pytest.raises(ValueError, match="supervisor_accepted"):
        _node("task_worker_proposed", proposed_by="worker", supervisor_accepted=False)


def test_task_graph_state_helpers_enforce_dependency_concurrency_conflict_and_validation_completion(tmp_path):
    db = _db(tmp_path)
    try:
        graph = create_task_graph(
            db,
            _graph(concurrency_limit=1),
            [
                _node("task_a", owned_paths=["hermes_cli/a.py"]),
                _node("task_b", dependencies=["task_a"], owned_paths=["hermes_cli/b.py"]),
                _node("task_conflict", owned_paths=["hermes_cli/a.py"]),
            ],
        )

        assert get_task_graph(db, "graph_1").graph_id == graph.graph_id
        assert list_task_graphs(db)[0].graph_id == "graph_1"
        assert dispatch_ready_nodes(db, "graph_1", now=100)["dispatched"][0]["task_id"] == "task_a"
        assert dispatch_ready_nodes(db, "graph_1", now=101)["skipped"][0]["reason"] == "concurrency_limit_reached"

        with pytest.raises(ValueError, match="validation_refs"):
            update_task_node(db, "graph_1", "task_a", status="completed")

        update_task_node(db, "graph_1", "task_a", status="validated", validation_refs=["test://a"])
        update_task_node(db, "graph_1", "task_a", status="completed")

        dispatch = dispatch_ready_nodes(db, "graph_1", now=102)
        assert dispatch["dispatched"][0]["task_id"] == "task_b"
        assert dispatch["skipped"][0]["reason"] == "concurrency_limit_reached"

        create_task_graph(
            db,
            _graph(graph_id="graph_conflict", concurrency_limit=2),
            [
                _node("task_c1", graph_id="graph_conflict", owned_paths=["shared/"]),
                _node("task_c2", graph_id="graph_conflict", owned_paths=["shared/file.py"]),
            ],
        )
        conflict_dispatch = dispatch_ready_nodes(db, "graph_conflict", now=103)
        assert conflict_dispatch["dispatched"][0]["task_id"] == "task_c1"
        assert conflict_dispatch["skipped"][0]["task_id"] == "task_c2"
        assert conflict_dispatch["skipped"][0]["reason"] == "owned_path_conflict"

        with pytest.raises(ValueError, match="not completeable"):
            complete_task_graph(db, "graph_1", session_summary_ref="summary://1")
    finally:
        db.close()


def test_ready_node_dispatch_uses_allocator_packets_without_overlapping_owned_paths(tmp_path):
    db = _db(tmp_path)
    try:
        create_task_graph(
            db,
            _graph(concurrency_limit=2, source="dashboard_api"),
            [
                _node("task_api", owned_paths=["api/"], priority=0),
                _node("task_cli", owned_paths=["cli/"], priority=1),
                _node("task_api_overlap", owned_paths=["api/routes.py"], priority=2),
            ],
        )

        payload = dispatch_ready_nodes(db, "graph_1", candidate_workers=["codex", "claude-code"], now=200)

        assert [item["task_id"] for item in payload["dispatched"]] == ["task_api", "task_cli"]
        assert payload["dispatched"][0]["source"] == "dashboard_api"
        assert payload["dispatched"][0]["allocation"]["decision"]["worker_id"] == "codex"
        assert payload["skipped"][0]["reason"] in {"concurrency_limit_reached", "owned_path_conflict"}
        assert all("raw stdout" not in json.dumps(item) for item in payload["dispatched"])
    finally:
        db.close()


def test_health_sidecar_detects_stale_missing_repeated_failures_no_progress_pause_and_is_idempotent(tmp_path):
    db = _db(tmp_path)
    try:
        create_task_graph(
            db,
            _graph(),
            [_node("task_stale"), _node("task_missing", owned_paths=["b/"]), _node("task_loop", owned_paths=["c/"])],
        )
        update_task_node(db, "graph_1", "task_stale", status="running", assigned_worker="codex", allocation_id="alloc_stale")
        update_task_node(db, "graph_1", "task_missing", status="running", assigned_worker="claude", allocation_id="alloc_missing")
        update_task_node(db, "graph_1", "task_loop", status="running", assigned_worker="deepseek", allocation_id="alloc_loop")
        create_task_ledger_entry(db, task_id="task_stale", worker_id="codex", lease_seconds=10, now=100)
        create_task_ledger_entry(db, task_id="task_missing", worker_id="claude", lease_seconds=500, now=100)
        create_task_ledger_entry(db, task_id="task_loop", worker_id="deepseek", lease_seconds=500, now=100)
        for idx in range(3):
            record_worker_heartbeat(
                db,
                task_id="task_loop",
                worker_id="deepseek",
                status="failed",
                progress_signature="same",
                command_signature="pytest",
                error_signature="TimeoutError",
                git_head="abc",
                test_signature="same",
                now=110 + idx,
            )
        plan = WorkerAllocationPlan(
            task_id="task_stale",
            session_id="session_1",
            objective="stale",
            candidate_workers=["codex"],
            primary_worker="codex",
            allocation_id="alloc_stale",
            cooldown_seconds=120,
        )
        save_allocation_plan(db, plan)
        save_worker_attempt(db, WorkerAttemptResult(allocation_id="alloc_stale", worker_id="codex", route="codex", status="timed_out", error_signature="timeout", started_at=120))
        save_worker_attempt(db, WorkerAttemptResult(allocation_id="alloc_stale", worker_id="codex", route="codex", status="empty_output", error_signature="empty", started_at=121))
        blocker = {"called": False}

        first = run_health_check_once(
            db,
            now=1_000,
            heartbeat_timeout_seconds=30,
            scan_limit=10,
            max_actions=20,
            foreground_blocking_callback=lambda: blocker.__setitem__("called", True),
        )
        second = run_health_check_once(db, now=1_000, heartbeat_timeout_seconds=30, scan_limit=10, max_actions=20)

        assert blocker["called"] is False
        assert first["status"] == "completed"
        assert first["stale_leases"] >= 1
        assert first["no_progress"] >= 1
        assert first["cooldowns_set"] >= 1
        assert first["recovery_candidates"] >= 3
        assert second["recovery_candidates"] == 0
        assert load_worker_health(db, "codex").cooldown_until == 1120
        assert get_task_graph(db, "graph_1").nodes["task_stale"].status in {"blocked", "needs_status"}
        actions = list_recovery_actions(db)
        assert actions
        assert "raw transcript" not in json.dumps([action.to_dict() for action in actions])
    finally:
        db.close()


def test_restart_recovery_reloads_active_state_preserves_cooldown_and_uses_approved_memory_only(tmp_path):
    db = _db(tmp_path)
    try:
        db.set_meta("goal:session_1", json.dumps({"status": "active", "goal": "finish"}))
        create_task_graph(db, _graph(), [_node("task_resume"), _node("task_unknown", owned_paths=["unknown/"])])
        update_task_node(db, "graph_1", "task_resume", status="assigned", assigned_worker="codex", allocation_id="alloc_resume")
        update_task_node(db, "graph_1", "task_unknown", status="running", assigned_worker="claude", allocation_id="alloc_unknown")
        save_allocation_plan(
            db,
            WorkerAllocationPlan(
                task_id="task_resume",
                session_id="session_1",
                objective="resume",
                candidate_workers=["codex", "claude"],
                primary_worker="codex",
                allocation_id="alloc_resume",
            ),
        )
        save_allocation_plan(
            db,
            WorkerAllocationPlan(
                task_id="task_unknown",
                session_id="session_1",
                objective="unknown",
                candidate_workers=["claude"],
                primary_worker="claude",
                allocation_id="alloc_unknown",
            ),
        )
        save_worker_health(db, WorkerHealth(worker_id="claude", cooldown_until=5_000))
        db.set_meta("runtime_hot_memory:approved", json.dumps({"status": "approved", "memory_packet_id": "mempkt_ok"}))
        db.set_meta("runtime_hot_memory:draft", json.dumps({"status": "draft", "memory_packet_id": "mempkt_bad"}))
        record_runtime_lease(db, lease_id="sidecar_1", owner="health", expires_at=900, status="active")
        expensive = {"called": False}

        payload = run_restart_recovery(
            db,
            now=1_000,
            expensive_sidecar=lambda: expensive.__setitem__("called", True),
        )

        assert expensive["called"] is False
        assert payload["active_goals"][0]["session_id"] == "session_1"
        assert payload["active_task_graphs"][0]["graph_id"] == "graph_1"
        assert payload["active_allocations"]
        assert payload["unhealthy_workers"][0]["worker_id"] == "claude"
        assert payload["hot_memory"] == [{"key": "runtime_hot_memory:approved", "memory_packet_id": "mempkt_ok"}]
        decisions = {item["task_id"]: item for item in payload["decisions"]}
        assert decisions["task_resume"]["decision"] == "resume"
        assert decisions["task_unknown"]["decision"] == "request_status"
        assert payload["stale_sidecar_leases"][0]["lease_id"] == "sidecar_1"
    finally:
        db.close()


def test_workflow_sources_share_allocator_health_and_recovery_vocabulary(tmp_path):
    db = _db(tmp_path)
    try:
        sources = ["chat", "goal", "dashboard_api", "worker_delegation"]
        for index, source in enumerate(sources):
            graph_id = f"graph_{source}"
            create_task_graph(
                db,
                _graph(graph_id=graph_id, source=source, root_task_id=f"root_{index}"),
                [_node(f"task_{source}", graph_id=graph_id, owned_paths=[f"{source}/"])],
            )
            payload = dispatch_ready_nodes(db, graph_id, candidate_workers=["codex"], now=100 + index)
            assert payload["dispatched"][0]["source"] == source
            assert payload["dispatched"][0]["allocation"]["decision"]["action"] == "dispatch"
            update_task_node(db, graph_id, f"task_{source}", status="running", assigned_worker="codex", allocation_id=payload["dispatched"][0]["allocation_id"])

        health = run_health_check_once(db, now=10_000, heartbeat_timeout_seconds=1, scan_limit=20, max_actions=20)
        status = recovery_status(db, now=10_000)

        assert {item["source"] for item in status["active_task_graphs"]} == set(sources)
        assert all(action["action"] in {"request_status", "request_reassignment", "emit_recovery_packet", "mark_node_blocked", "set_worker_cooldown", "pause_allocation"} for action in health["actions"])
    finally:
        db.close()


def test_supervisor_context_gate_rejects_raw_streams_and_accepts_bounded_typed_packets():
    gate = SupervisorContextGate(max_chars=80, max_evidence_refs=2)

    raw_cases = [
        {"event_type": "worker_stream_ref", "stream": "stdout", "summary": "raw stdout\n" * 20, "store_only": True},
        {"packet_type": "worker_checkpoint", "summary": "$ pytest\nfull terminal transcript\n" * 20, "evidence_refs": ["terminal://raw"]},
        {"packet_type": "worker_checkpoint", "summary": "worker watch stream chunk", "evidence_refs": ["watch://worker/1"]},
        {"packet_type": "worker_checkpoint", "summary": "raw log tail", "evidence_refs": ["logtail://agent.log"]},
        {"summary": "untyped worker prose says probably done"},
        {"packet_type": "curator_proposal", "summary": "dreamed next task"},
    ]
    for packet in raw_cases:
        result = gate.admit(packet)
        assert result.accepted is False
        assert result.context_packet is None

    accepted = gate.admit(
        {
            "packet_type": "worker_checkpoint",
            "task_id": "task_a",
            "summary": "Implemented helper and ran focused tests.",
            "status": "in_progress",
            "evidence_refs": ["log://worker/1", "test://pytest"],
            "artifact_refs": ["artifact://stdout/1"],
        }
    )
    assert accepted.accepted is True
    assert accepted.context_packet["packet_type"] == "worker_checkpoint"
    assert accepted.context_packet["artifact_refs"] == ["artifact://stdout/1"]

    oversized = gate.admit(
        {
            "packet_type": "worker_checkpoint",
            "task_id": "task_a",
            "summary": "bounded summary " * 20,
            "status": "in_progress",
            "evidence_refs": ["log://1", "log://2"],
        }
    )
    assert oversized.accepted is True
    assert oversized.context_packet["summary"].endswith("...")
    assert len(oversized.context_packet["summary"]) <= 80

    too_many_refs = gate.admit(
        {
            "packet_type": "worker_checkpoint",
            "summary": "ok",
            "evidence_refs": ["log://1", "log://2", "log://3"],
        }
    )
    assert too_many_refs.accepted is False


def test_worker_runtime_wrapper_emits_mandatory_events_for_success_degraded_timeout_and_empty_output(tmp_path):
    db = _db(tmp_path)
    base = {
        "task_id": "task_wrap",
        "allocation_id": "alloc_wrap",
        "attempt_id": "attempt_wrap",
        "worker_id": "codex",
        "repo_id": "repo-a",
        "branch": "132-learning-memory-runtime",
    }
    try:
        result = run_worker_with_progress_events(
            db,
            **base,
            worker_run=lambda: {
                "status": "blocked",
                "summary": "Need approval for migration.",
                "stdout_ref": "log://stdout/success",
                "validation_refs": ["test://unit"],
                "artifact_refs": ["git://diff"],
            },
            now=100,
        )
        assert result["status"] == "blocked"
        events = list_worker_progress_events(db, task_id="task_wrap")
        event_types = [event["event_type"] for event in events]
        assert event_types == [
            "worker_started",
            "worker_heartbeat",
            "worker_stream_ref",
            "worker_progress_checkpoint",
            "worker_blocked",
            "worker_validation",
            "worker_final",
        ]
        assert all(event["task_id"] == "task_wrap" for event in events)
        assert all(event["allocation_id"] == "alloc_wrap" for event in events)
        assert all(event["attempt_id"] == "attempt_wrap" for event in events)
        assert all(event["worker_id"] == "codex" for event in events)
        assert all(event["repo_id"] == "repo-a" for event in events)
        assert all(event["branch"] == "132-learning-memory-runtime" for event in events)
        assert [event for event in events if event["event_type"] == "worker_stream_ref"][0]["store_only"] is True

        for suffix, worker_run in [
            ("unavailable", lambda: (_ for _ in ()).throw(RuntimeError("model unavailable"))),
            ("timeout", lambda: (_ for _ in ()).throw(TimeoutError("worker timed out"))),
            ("empty", lambda: {"status": "completed", "summary": ""}),
        ]:
            payload = dict(base)
            payload.update(task_id=f"task_{suffix}", allocation_id=f"alloc_{suffix}", attempt_id=f"attempt_{suffix}")
            run_worker_with_progress_events(db, **payload, worker_run=worker_run, now=200)
            degraded_events = list_worker_progress_events(db, task_id=f"task_{suffix}")
            assert "worker_degraded" in [event["event_type"] for event in degraded_events]
            assert degraded_events[-1]["event_type"] == "worker_final"
            assert degraded_events[-1]["status"] == "degraded"
    finally:
        db.close()


def test_progress_summarizer_sidecar_is_bounded_low_cost_nonblocking_and_advisory_only(tmp_path):
    db = _db(tmp_path)
    called = {"foreground": False, "model": False}
    try:
        run_worker_with_progress_events(
            db,
            task_id="task_sum",
            allocation_id="alloc_sum",
            attempt_id="attempt_sum",
            worker_id="codex",
            repo_id="repo-a",
            branch="132-learning-memory-runtime",
            worker_run=lambda: {"status": "running", "summary": "edited files and ran tests", "stdout_ref": "log://stdout/sum"},
            now=300,
        )

        def low_cost(events, budget):
            called["model"] = True
            assert budget["tier"] == "low_cost_reasoning"
            assert budget["max_chars"] == 120
            return "low-cost checkpoint from event refs"

        payload = run_progress_summarizer_sidecar(
            db,
            task_id="task_sum",
            allocation_id="alloc_sum",
            low_cost_summarizer=low_cost,
            foreground_blocking_callback=lambda: called.__setitem__("foreground", True),
            max_chars=120,
            max_events=20,
            timeout_seconds=0.25,
            budget_tokens=256,
            now=400,
        )
        assert called == {"foreground": False, "model": True}
        assert payload["packet"]["packet_type"] == "worker_checkpoint"
        assert payload["packet"]["summary"] == "low-cost checkpoint from event refs"
        assert payload["tier"] == "low_cost_reasoning"
        assert payload["timeout_seconds"] == 0.25
        assert payload["budget_tokens"] == 256
        assert payload["authorities"] == {
            "complete_tasks": False,
            "approve_memory": False,
            "enforce_policy": False,
            "mutate_routing": False,
            "change_config": False,
        }

        fallback = run_progress_summarizer_sidecar(
            db,
            task_id="task_sum",
            allocation_id="alloc_sum",
            low_cost_summarizer=lambda events, budget: (_ for _ in ()).throw(RuntimeError("low-cost unavailable")),
            max_chars=90,
            now=401,
        )
        assert fallback["status"] == "degraded"
        assert fallback["fallback"] == "deterministic"
        assert len(fallback["packet"]["summary"]) <= 90
        assert "raw" not in json.dumps(fallback["supervisor_context"])
    finally:
        db.close()


def test_worker_progress_observability_projects_refs_without_supervisor_context_raw_append(tmp_path, monkeypatch, capsys):
    db = _db(tmp_path)
    try:
        run_worker_with_progress_events(
            db,
            task_id="task_obs",
            allocation_id="alloc_obs",
            attempt_id="attempt_obs",
            worker_id="codex",
            repo_id="repo-a",
            branch="132-learning-memory-runtime",
            worker_run=lambda: {"status": "completed", "summary": "done", "stdout_ref": "log://stdout/obs"},
            now=500,
        )
        projection = project_worker_progress_for_delivery(db, task_id="task_obs", channel="slack")
        assert projection["channel"] == "slack"
        assert projection["source"] == "worker_progress_events"
        assert projection["supervisor_context_appended"] is False
        assert projection["events"][2]["event_type"] == "worker_stream_ref"
        assert projection["events"][2]["store_only"] is True
        assert "raw stdout" not in json.dumps(projection["supervisor_context_packets"])
    finally:
        db.close()

    home = tmp_path / ".hermes"
    monkeypatch.setenv("HERMES_HOME", str(home))
    import hermes_state

    monkeypatch.setattr(hermes_state, "DEFAULT_DB_PATH", home / "state.db")
    cli_db = SessionDB(db_path=home / "state.db")
    try:
        run_worker_with_progress_events(
            cli_db,
            task_id="task_cli_progress",
            allocation_id="alloc_cli_progress",
            attempt_id="attempt_cli_progress",
            worker_id="codex",
            repo_id="repo-a",
            branch="132-learning-memory-runtime",
            worker_run=lambda: {"status": "completed", "summary": "cli done", "stdout_ref": "log://stdout/cli"},
            now=600,
        )
    finally:
        cli_db.close()

    from hermes_cli import main as hermes_main

    with patch.object(sys, "argv", ["hermes", "runtime", "worker-progress", "list", "--task-id", "task_cli_progress", "--json"]):
        hermes_main.main()
    listed = json.loads(capsys.readouterr().out)
    assert listed["source"] == "worker_progress_events"
    assert listed["events"][0]["event_type"] == "worker_started"

    with patch.object(sys, "argv", ["hermes", "runtime", "worker-progress", "context", "--task-id", "task_cli_progress", "--json"]):
        hermes_main.main()
    context = json.loads(capsys.readouterr().out)
    assert context["supervisor_context_appended"] is False
    assert all(packet["packet_type"] in {"worker_checkpoint", "worker_final"} for packet in context["supervisor_context_packets"])


def test_self_healing_runtime_cli_json_surfaces(tmp_path, monkeypatch, capsys):
    home = tmp_path / ".hermes"
    monkeypatch.setenv("HERMES_HOME", str(home))
    import hermes_state

    monkeypatch.setattr(hermes_state, "DEFAULT_DB_PATH", home / "state.db")
    from hermes_cli import main as hermes_main

    db = SessionDB(db_path=home / "state.db")
    try:
        create_task_graph(db, _graph(), [_node("task_cli")])
    finally:
        db.close()

    with patch.object(sys, "argv", ["hermes", "runtime", "task-graph", "list", "--json"]):
        hermes_main.main()
    listed = json.loads(capsys.readouterr().out)
    assert listed[0]["graph_id"] == "graph_1"

    with patch.object(sys, "argv", ["hermes", "runtime", "task-graph", "get", "graph_1", "--json"]):
        hermes_main.main()
    graph = json.loads(capsys.readouterr().out)
    assert graph["nodes"]["task_cli"]["task_id"] == "task_cli"

    with patch.object(sys, "argv", ["hermes", "runtime", "health", "check", "--once", "--json"]):
        hermes_main.main()
    health = json.loads(capsys.readouterr().out)
    assert health["status"] == "completed"

    with patch.object(sys, "argv", ["hermes", "runtime", "recovery", "status", "--json"]):
        hermes_main.main()
    status = json.loads(capsys.readouterr().out)
    assert status["active_task_graphs"][0]["graph_id"] == "graph_1"

    with patch.object(sys, "argv", ["hermes", "runtime", "recovery", "run", "--once", "--json"]):
        hermes_main.main()
    recovered = json.loads(capsys.readouterr().out)
    assert recovered["status"] == "completed"
