from pathlib import Path

from hermes_cli.memory_index import (
    lexical_search,
    upsert_memory_index_document,
    vector_search,
)
from hermes_state import SessionDB


def _make_db(tmp_path: Path) -> SessionDB:
    return SessionDB(db_path=tmp_path / "state.db")


def test_lexical_index_matches_commands_flags_paths_and_errors(tmp_path):
    db = _make_db(tmp_path)
    try:
        upsert_memory_index_document(
            db,
            memory_id="mem-1",
            text="worker-router claude failed with unknown option",
            metadata={
                "tenant_id": "atlas",
                "repo_id": "hermes-agent",
                "tool": "claude",
                "task_type": "tool_routing",
                "status": "approved",
                "command": "claude --model sonnet -p",
                "file_path": "tools/terminal_tool.py",
                "branch": "132-learning-memory-runtime",
                "error_signature": "unknown option",
            },
        )

        rows = lexical_search(
            db,
            query="claude --model sonnet unknown option tools/terminal_tool.py",
            tenant_id="atlas",
            repo_id="hermes-agent",
            statuses=["approved"],
        )

        assert rows
        assert rows[0]["memory_id"] == "mem-1"
        assert "claude" in rows[0]["matched_terms"]
        assert "tools/terminal_tool.py" in rows[0]["matched_terms"]
    finally:
        db.close()


def test_vector_search_cannot_bypass_scope_or_status_filters(tmp_path):
    db = _make_db(tmp_path)
    try:
        upsert_memory_index_document(
            db,
            memory_id="allowed",
            text="allowed memory",
            metadata={"tenant_id": "atlas", "repo_id": "repo-a", "status": "approved"},
            vector=[1.0, 0.0],
        )
        upsert_memory_index_document(
            db,
            memory_id="wrong-scope",
            text="wrong scope memory",
            metadata={"tenant_id": "other", "repo_id": "repo-a", "status": "approved"},
            vector=[10.0, 0.0],
        )
        upsert_memory_index_document(
            db,
            memory_id="rejected",
            text="rejected memory",
            metadata={"tenant_id": "atlas", "repo_id": "repo-a", "status": "rejected"},
            vector=[20.0, 0.0],
        )

        rows = vector_search(
            db,
            query_vector=[1.0, 0.0],
            tenant_id="atlas",
            repo_id="repo-a",
            statuses=["approved"],
        )

        assert [row["memory_id"] for row in rows] == ["allowed"]
    finally:
        db.close()
