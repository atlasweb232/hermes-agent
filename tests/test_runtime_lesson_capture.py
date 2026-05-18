import json

from hermes_cli.runtime_lesson_capture import (
    RuntimeLessonObserver,
    ToolOutcome,
    append_lesson_capture_note,
    apply_runtime_failure_gate_to_final_response,
    classify_terminal_status,
    parse_terminal_failure,
    persist_runtime_lesson,
    redact_sensitive_text,
)
from hermes_state import SessionDB


def test_parse_terminal_failure_from_json_exit_code():
    assert parse_terminal_failure(json.dumps({"exit_code": 2, "stderr": "bad"})) is True
    assert parse_terminal_failure(json.dumps({"exit_code": 0, "stdout": "ok"})) is False


def test_classify_terminal_status_detects_timeout_and_empty_output():
    assert classify_terminal_status(json.dumps({"exit_code": 124, "error": "timed out"}), failed=True) == "timed_out"
    assert classify_terminal_status(json.dumps({"exit_code": 0, "output": ""}), failed=False) == "empty_output"
    assert classify_terminal_status(json.dumps({"exit_code": 0, "output": "4"}), failed=False) == "success"


def test_redacts_common_secret_shapes():
    text = "token=sk-abc123456789XYZ password=supersecret bot=123456:ABCDEFGHIJKLMNOPQRSTUVWXYZ"

    safe = redact_sensitive_text(text)

    assert "sk-abc" not in safe
    assert "supersecret" not in safe
    assert "ABCDEFGHIJKLMNOPQRSTUVWXYZ" not in safe
    assert "[REDACTED]" in safe


def test_observer_captures_claude_router_failure_then_direct_success():
    observer = RuntimeLessonObserver(min_failures=3)
    for command in (
        'worker-router claude "two plus two"',
        'worker-router claude -p "two plus two"',
        'worker-router claude --model sonnet "two plus two"',
    ):
        assert observer.observe(
            ToolOutcome(tool_name="terminal", command=command, failed=True)
        ) is None

    lesson = observer.observe(
        ToolOutcome(
            tool_name="terminal",
            command='claude --model sonnet -p "two plus two"',
            failed=False,
            result_excerpt="4",
            session_id="session-1",
            cwd="/tmp/project",
        )
    )

    assert lesson is not None
    assert lesson.kind == "routing_hint"
    assert "worker-router claude" in lesson.claim
    assert lesson.evidence["failure_count"] == 3
    assert lesson.evidence["working_path"] == "claude --model sonnet -p"


def test_observer_does_not_emit_without_successful_alternative():
    observer = RuntimeLessonObserver(min_failures=1)

    assert observer.observe(
        ToolOutcome(
            tool_name="terminal",
            command='worker-router claude "two plus two"',
            failed=True,
        )
    ) is None
    assert observer.observe(
        ToolOutcome(
            tool_name="terminal",
            command='claude -p "two plus two"',
            failed=True,
        )
    ) is None


def test_observer_captures_generic_long_tool_loop_failure():
    observer = RuntimeLessonObserver(long_failure_seconds=30)

    lesson = observer.observe(
        ToolOutcome(
            tool_name="terminal",
            command='worker-router watch agent',
            failed=True,
            result_excerpt="timed out",
            duration_seconds=120.0,
            session_id="session-loop",
            cwd="/tmp/project",
        )
    )

    assert lesson is not None
    assert lesson.kind == "supervisor_tool_loop_failure"
    assert lesson.evidence["failure_type"] == "supervisor_tool_loop_failure"
    assert lesson.evidence["command_family"] == "worker-router"
    assert lesson.evidence["requires_judge"] is True


def test_observer_captures_generic_evidence_mismatch_after_failed_route():
    observer = RuntimeLessonObserver(long_failure_seconds=30)
    observer.observe(
        ToolOutcome(
            tool_name="terminal",
            command='worker-router watch agent',
            failed=True,
            result_excerpt="timed out",
            duration_seconds=120.0,
        )
    )

    lesson = observer.observe(
        ToolOutcome(
            tool_name="terminal",
            command='echo $((2+2))',
            failed=False,
            result_excerpt="4",
            duration_seconds=0.3,
        )
    )

    assert lesson is not None
    assert lesson.kind == "supervisor_evidence_mismatch"
    assert lesson.evidence["failed_command_family"] == "worker-router"
    assert lesson.evidence["substitute_command_family"] == "echo"
    assert lesson.evidence["operator_approval_required"] is True


def test_runtime_failure_gate_requires_disclosure_after_failed_worker():
    observer = RuntimeLessonObserver(long_failure_seconds=30)
    observer.observe(
        ToolOutcome(
            tool_name="terminal",
            command='worker-router claude "what is two plus two"',
            failed=True,
            result_excerpt="timed out",
            duration_seconds=120.0,
            status="timed_out",
        )
    )

    gate = observer.runtime_failure_gate()
    response = apply_runtime_failure_gate_to_final_response("Answer: 4", gate)

    assert gate.status == "degraded"
    assert gate.last_failed_family == "worker-router"
    assert "Worker delegation degraded" in response
    assert "supervisor fallback" in response
    assert "Answer: 4" in response


def test_runtime_failure_gate_clears_after_later_successful_worker():
    observer = RuntimeLessonObserver(long_failure_seconds=30)
    observer.observe(
        ToolOutcome(
            tool_name="terminal",
            command='worker-router claude "what is two plus two"',
            failed=True,
            status="timed_out",
        )
    )
    observer.observe(
        ToolOutcome(
            tool_name="terminal",
            command='codex exec "what is two plus two"',
            failed=False,
            result_excerpt="4",
            status="success",
        )
    )

    assert observer.runtime_failure_gate().status == "passed"


def test_observer_counts_hermes_worker_router_wrapper_failures():
    observer = RuntimeLessonObserver(min_failures=3)
    for command in (
        'hermes worker-router claude "two plus two"',
        'worker-router claude "two plus two"',
        'hermes worker-router claude --help',
    ):
        assert observer.observe(
            ToolOutcome(tool_name="terminal", command=command, failed=True)
        ) is None

    lesson = observer.observe(
        ToolOutcome(
            tool_name="terminal",
            command='claude -p "two plus two" --model sonnet',
            failed=False,
            result_excerpt="4",
        )
    )

    assert lesson is not None
    assert lesson.evidence["failure_count"] == 3
    assert lesson.evidence["working_command"] == 'claude -p "two plus two" --model sonnet'


def test_persist_runtime_lesson_writes_memory_only(tmp_path):
    observer = RuntimeLessonObserver(min_failures=1)
    observer.observe(
        ToolOutcome(
            tool_name="terminal",
            command='worker-router claude "two plus two"',
            failed=True,
        )
    )
    lesson = observer.observe(
        ToolOutcome(
            tool_name="terminal",
            command='claude --model sonnet -p "two plus two"',
            failed=False,
            result_excerpt="4",
        )
    )
    db = SessionDB(tmp_path / "state.db")

    capture = persist_runtime_lesson(db, lesson)

    assert capture["lesson_captured"] is True
    records = db.list_memory_records(kind="tool_routing_lesson", limit=5)
    assert records[0]["id"] == capture["record_id"]
    assert records[0]["payload_json"]["secret_safe"] is True
    assert db.list_meta_candidates(kind="routing_hint", limit=5) == []


def test_persist_generic_supervisor_failure_writes_supervisor_runtime_failure(tmp_path):
    observer = RuntimeLessonObserver(long_failure_seconds=30)
    lesson = observer.observe(
        ToolOutcome(
            tool_name="terminal",
            command='worker-router watch agent',
            failed=True,
            result_excerpt="timed out",
            duration_seconds=120.0,
        )
    )
    db = SessionDB(tmp_path / "state.db")

    capture = persist_runtime_lesson(db, lesson)

    assert capture["lesson_captured"] is True
    records = db.list_memory_records(kind="supervisor_runtime_failure", limit=5)
    assert records[0]["id"] == capture["record_id"]
    assert records[0]["payload_json"]["failure_type"] == "supervisor_tool_loop_failure"


def test_append_lesson_capture_note_preserves_json_result():
    result = append_lesson_capture_note(
        json.dumps({"exit_code": 0, "stdout": "4"}),
        {
            "lesson_captured": True,
            "record_id": "memrec_1",
            "kind": "routing_hint",
            "claim": "prefer direct claude",
        },
    )

    parsed = json.loads(result)
    assert parsed["exit_code"] == 0
    assert parsed["runtime_lesson_capture"]["status"] == "captured"
    assert "candidate_id" not in parsed["runtime_lesson_capture"]


def test_agent_observer_hook_persists_lesson(tmp_path, monkeypatch):
    from run_agent import AIAgent

    db = SessionDB(tmp_path / "state.db")
    agent = object.__new__(AIAgent)
    agent._session_db = db
    agent.session_id = "session-hook-test"

    assert agent._observe_runtime_lesson(
        "terminal",
        {"command": 'worker-router claude "two plus two"', "workdir": str(tmp_path)},
        json.dumps({"exit_code": 2, "stderr": "bad args"}),
        True,
    )
    assert agent._observe_runtime_lesson(
        "terminal",
        {"command": 'worker-router claude -p "two plus two"', "workdir": str(tmp_path)},
        json.dumps({"exit_code": 2, "stderr": "bad args"}),
        True,
    )
    assert agent._observe_runtime_lesson(
        "terminal",
        {"command": 'worker-router claude --model sonnet "two plus two"', "workdir": str(tmp_path)},
        json.dumps({"exit_code": 2, "stderr": "bad args"}),
        True,
    )
    result = agent._observe_runtime_lesson(
        "terminal",
        {"command": 'claude --model sonnet -p "two plus two"', "workdir": str(tmp_path)},
        json.dumps({"exit_code": 0, "stdout": "4"}),
        False,
    )

    parsed = json.loads(result)
    assert parsed["runtime_lesson_capture"]["status"] == "captured"
    assert db.list_memory_records(kind="tool_routing_lesson", limit=1)
    assert db.list_meta_candidates(kind="routing_hint", limit=1) == []


def test_agent_observer_hook_persists_generic_supervisor_failure(tmp_path):
    from run_agent import AIAgent

    db = SessionDB(tmp_path / "state.db")
    agent = object.__new__(AIAgent)
    agent._session_db = db
    agent.session_id = "session-generic-hook-test"

    result = agent._observe_runtime_lesson(
        "terminal",
        {"command": 'worker-router watch agent', "workdir": str(tmp_path)},
        json.dumps({"exit_code": 124, "stderr": "timed out"}),
        True,
        120.0,
    )

    parsed = json.loads(result)
    assert parsed["runtime_lesson_capture"]["status"] == "captured"
    records = db.list_memory_records(kind="supervisor_runtime_failure", limit=1)
    assert records[0]["payload_json"]["failure_type"] == "supervisor_tool_loop_failure"


def test_agent_runtime_failure_gate_discloses_worker_degradation(tmp_path):
    from run_agent import AIAgent

    db = SessionDB(tmp_path / "state.db")
    agent = object.__new__(AIAgent)
    agent._session_db = db
    agent.session_id = "session-runtime-gate-test"
    agent._observe_runtime_lesson(
        "terminal",
        {"command": 'worker-router claude "what is two plus two"', "workdir": str(tmp_path)},
        json.dumps({"exit_code": 124, "error": "timed out"}),
        True,
        120.0,
    )

    response = agent._apply_runtime_failure_gate_to_final_response("The answer is 4.")

    assert "Worker delegation degraded" in response
    assert "worker-router" in response
    assert "The answer is 4." in response
