import json

from hermes_cli.runtime_lesson_capture import (
    RuntimeLessonObserver,
    ToolOutcome,
    append_lesson_capture_note,
    parse_terminal_failure,
    persist_runtime_lesson,
    redact_sensitive_text,
)
from hermes_state import SessionDB


def test_parse_terminal_failure_from_json_exit_code():
    assert parse_terminal_failure(json.dumps({"exit_code": 2, "stderr": "bad"})) is True
    assert parse_terminal_failure(json.dumps({"exit_code": 0, "stdout": "ok"})) is False


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


def test_persist_runtime_lesson_writes_memory_and_candidate(tmp_path):
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
    candidates = db.list_meta_candidates(kind="routing_hint", limit=5)
    assert records[0]["id"] == capture["record_id"]
    assert records[0]["payload_json"]["secret_safe"] is True
    assert candidates[0]["id"] == capture["candidate_id"]
    assert candidates[0]["status"] == "proposed"


def test_append_lesson_capture_note_preserves_json_result():
    result = append_lesson_capture_note(
        json.dumps({"exit_code": 0, "stdout": "4"}),
        {
            "lesson_captured": True,
            "candidate_id": "metacand_1",
            "record_id": "memrec_1",
            "kind": "routing_hint",
            "claim": "prefer direct claude",
        },
    )

    parsed = json.loads(result)
    assert parsed["exit_code"] == 0
    assert parsed["runtime_lesson_capture"]["status"] == "captured"


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
    assert db.list_meta_candidates(kind="routing_hint", limit=1)
