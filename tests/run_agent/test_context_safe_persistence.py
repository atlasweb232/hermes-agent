from hermes_state import SessionDB


def _agent_with_db(tmp_path):
    from run_agent import AIAgent

    agent = AIAgent.__new__(AIAgent)
    agent._session_db = SessionDB(db_path=tmp_path / "state.db")
    agent.session_id = "session-context-safe"
    agent.task_id = "task-context-safe"
    return agent


def test_persisted_transcript_offloads_long_tool_output(tmp_path):
    from hermes_cli.worker_event_store import list_worker_events

    agent = _agent_with_db(tmp_path)
    try:
        raw = "1|import os\n" + ("2|very verbose source line\n" * 800)
        messages = [
            {"role": "user", "content": "inspect this file"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": "tc_read", "function": {"name": "read_file", "arguments": "{}"}}],
            },
            {"role": "tool", "name": "read_file", "tool_call_id": "tc_read", "content": raw},
        ]

        persisted = agent._context_safe_messages_for_persistence(messages)

        assert persisted[2]["content"] != raw
        assert "context-offloaded-transcript-tool-result" in persisted[2]["content"]
        assert "event://worker/" in persisted[2]["content"]
        assert "very verbose source line\n2|very verbose source line" not in persisted[2]["content"]
        assert persisted[2]["_context_offloaded"] is True

        events = list_worker_events(agent._session_db, task_id="task-context-safe")
        assert len(events) == 1
        assert events[0].raw_size_bytes == len(raw.encode("utf-8"))
    finally:
        agent._session_db.close()


def test_persisted_transcript_keeps_small_tool_result_inline(tmp_path):
    agent = _agent_with_db(tmp_path)
    try:
        messages = [
            {"role": "tool", "name": "status", "tool_call_id": "tc_status", "content": "pytest passed; git diff clean"},
        ]

        persisted = agent._context_safe_messages_for_persistence(messages)

        assert persisted == messages
    finally:
        agent._session_db.close()


def test_persisted_transcript_offload_is_idempotent(tmp_path):
    from hermes_cli.worker_event_store import list_worker_events

    agent = _agent_with_db(tmp_path)
    try:
        raw = "worker-router watch claude\n" + ("proc wait output\n" * 700)
        messages = [
            {"role": "tool", "name": "terminal", "tool_call_id": "tc_term", "content": raw},
        ]

        first = agent._context_safe_messages_for_persistence(messages)
        second = agent._context_safe_messages_for_persistence(messages)

        assert first[0]["_context_event_ref"] == second[0]["_context_event_ref"]
        events = list_worker_events(agent._session_db, task_id="task-context-safe")
        assert len(events) == 1
    finally:
        agent._session_db.close()
