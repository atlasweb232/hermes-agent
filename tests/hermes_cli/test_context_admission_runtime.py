import json

from hermes_state import SessionDB


def test_t346a_context_admission_rejects_raw_streams_and_repeated_status():
    from hermes_cli.context_admission import ContextItem, ContextAdmissionPolicy, decide_context_admission, text_hash

    long_stream = "preparing terminal\nworker-router watch claude\n" + ("stdout line\n" * 800)
    decision = decide_context_admission(
        ContextItem(kind="worker_stream", source="worker", text=long_stream),
        policy=ContextAdmissionPolicy(direct_token_budget=100, summary_token_budget=300),
    )
    assert decision.action == "store_only"
    assert decision.ref_recommended is True
    assert decision.elapsed_ms <= decision.foreground_budget_ms

    status = "Still working; no validated output yet."
    repeated = decide_context_admission(
        ContextItem(kind="status", source="slack_mirror", text=status),
        recent_hashes=[text_hash(status), text_hash(status), text_hash(status)],
    )
    assert repeated.action == "store_only"
    assert repeated.reason == "repeated_status"


def test_t346a_decision_critical_small_context_is_admitted():
    from hermes_cli.context_admission import ContextItem, decide_context_admission

    decision = decide_context_admission(
        ContextItem(kind="validation_result", source="supervisor", text="pytest passed; git diff clean")
    )
    assert decision.action == "admit"
    assert decision.estimated_tokens < 50


def test_t346b_worker_event_store_persists_redacted_refs(tmp_path):
    from hermes_cli.worker_event_store import list_worker_events, store_worker_event

    db = SessionDB(db_path=tmp_path / "state.db")
    try:
        event = store_worker_event(
            db,
            kind="worker_stream",
            source="claude",
            tenant_id="tenant-a",
            repo_id="repo-a",
            task_id="task-a",
            worker_id="claude-1",
            content="stdout password=hunter2 api_key=sk-testsecret123456789\n" + ("line\n" * 200),
            payload={"raw_command": "do not include raw secret token=sk-testsecret123456789"},
            now=100.0,
        )
        assert event.ref.startswith("event://worker/")
        assert event.raw_size_bytes > 0
        payload = json.dumps(event.to_dict())
        assert "hunter2" not in payload
        assert "sk-testsecret" not in payload
        assert event.foreground_admitted is False

        listed = list_worker_events(db, tenant_id="tenant-a", repo_id="repo-a", task_id="task-a")
        assert [item.id for item in listed] == [event.id]
    finally:
        db.close()


def test_t346c_progress_checkpoint_is_bounded_and_ref_only(tmp_path):
    from hermes_cli.progress_checkpoint import build_progress_checkpoint, build_supervisor_context_packet
    from hermes_cli.worker_event_store import store_worker_event

    db = SessionDB(db_path=tmp_path / "state.db")
    try:
        events = [
            store_worker_event(
                db,
                kind="worker_stream",
                source="codex",
                task_id="task-a",
                content=f"large worker update {idx}\n" + ("details\n" * 500),
                now=100.0 + idx,
            )
            for idx in range(4)
        ]
        checkpoint = build_progress_checkpoint(
            task_id="task-a",
            events=events,
            task_state={"status": "running", "summary": "Implement production context gate"},
            validation_refs=["pytest://context-admission"],
            memory_refs=["memory://relevant-lesson"],
            token_budget=200,
            now=200.0,
        )
        assert checkpoint.estimated_tokens <= checkpoint.token_budget
        assert checkpoint.event_refs
        assert "details\ndetails" not in checkpoint.latest_progress

        packet = build_supervisor_context_packet(checkpoint=checkpoint, memory_packet={"id": "mem-a", "items": [{"claim": "x"}]})
        assert packet["raw_worker_updates_included"] is False
        assert packet["context_policy"] == "checkpoint_and_refs_only"
        dumped = json.dumps(packet)
        assert "large worker update" in dumped
        assert dumped.count("details") < 3
    finally:
        db.close()


def test_t346d_long_worker_updates_do_not_enter_supervisor_packet(tmp_path):
    from hermes_cli.context_admission import ContextItem, decide_context_admission
    from hermes_cli.progress_checkpoint import build_progress_checkpoint, build_supervisor_context_packet
    from hermes_cli.worker_event_store import store_worker_event

    db = SessionDB(db_path=tmp_path / "state.db")
    try:
        raw = "worker update\n" + ("very verbose log body\n" * 3000)
        decision = decide_context_admission(ContextItem(kind="worker_stream", source="claude", text=raw))
        assert decision.action == "store_only"

        event = store_worker_event(db, kind="worker_stream", source="claude", task_id="task-b", content=raw)
        checkpoint = build_progress_checkpoint(task_id="task-b", events=[event], token_budget=250)
        packet = build_supervisor_context_packet(checkpoint=checkpoint)

        payload = json.dumps(packet)
        assert len(payload) < len(raw) / 10
        assert packet["raw_worker_updates_included"] is False
        assert event.ref in payload
    finally:
        db.close()

