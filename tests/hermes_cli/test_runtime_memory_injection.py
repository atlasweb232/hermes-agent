from hermes_cli.global_memory import persist_global_lesson
from hermes_cli.runtime_memory_injection import (
    build_runtime_memory_context,
    infer_runtime_memory_event,
)
from hermes_state import SessionDB


def _db(tmp_path):
    return SessionDB(db_path=tmp_path / "state.db")


def test_infer_runtime_memory_event_classifies_claude_worker_task():
    event = infer_runtime_memory_event("Ask Claude Code what is two plus two", tenant_id="atlas")

    assert event.tenant_id == "atlas"
    assert event.tool == "claude"
    assert event.worker_kind == "claude-code"
    assert event.task_type == "worker_routing"
    assert event.normalized_text == "ask claude code what is two plus two"


def test_build_runtime_memory_context_injects_approved_global_lesson(tmp_path):
    db = _db(tmp_path)
    try:
        persist_global_lesson(
            db,
            {
                "id": "global-claude-runtime",
                "approval_state": "approved",
                "scope": "global",
                "visibility": "global_candidate",
                "sensitivity": "internal",
                "claim_type": "command_repair_policy",
                "tenant_id": "atlas",
                "tool": "claude",
                "task_type": "worker_routing",
                "normalized_text": "Prefer direct Claude Code invocation after worker-router claude parse errors.",
                "confidence": 0.91,
                "cross_tenant_shareable": True,
            },
        )

        result = build_runtime_memory_context(
            db,
            "Ask Claude Code what is two plus two",
            tenant_id="atlas",
            config={"supervisor": {"runtime_memory_injection": {"enabled": True}}},
        )

        assert result.status == "ready"
        assert "Hermes runtime memory advisory" in result.context
        assert "prefer direct claude code invocation" in result.context
        assert "Explicit user instructions, git, tests, and logs are more authoritative" in result.context
        assert result.packet is not None
        assert result.packet.retrieval_audit["matched"][0]["reason"] == "metadata_lexical"
    finally:
        db.close()


def test_build_runtime_memory_context_respects_disabled_config(tmp_path):
    db = _db(tmp_path)
    try:
        result = build_runtime_memory_context(
            db,
            "Ask Claude Code what is two plus two",
            tenant_id="atlas",
            config={"supervisor": {"runtime_memory_injection": {"enabled": False}}},
        )

        assert result.status == "disabled"
        assert result.context == ""
        assert result.packet is None
    finally:
        db.close()
