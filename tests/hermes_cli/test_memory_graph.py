from pathlib import Path

from hermes_cli.memory_graph import expand_graph, upsert_graph_edge, upsert_graph_node
from hermes_state import SessionDB


def _make_db(tmp_path: Path) -> SessionDB:
    return SessionDB(db_path=tmp_path / "state.db")


def test_memory_graph_node_edge_expansion_and_explanation_paths(tmp_path):
    db = _make_db(tmp_path)
    try:
        upsert_graph_node(db, node_id="memory:1", kind="memory", label="Claude routing lesson")
        upsert_graph_node(db, node_id="tool:claude", kind="tool", label="Claude Code")
        upsert_graph_node(db, node_id="error:unknown-option", kind="error", label="unknown option")
        upsert_graph_edge(db, source_id="memory:1", target_id="tool:claude", relation="applies_to", weight=0.9)
        upsert_graph_edge(db, source_id="memory:1", target_id="error:unknown-option", relation="avoids", weight=0.8)

        paths = expand_graph(db, start_id="memory:1", limit=5)

        assert {path["target_id"] for path in paths} == {"tool:claude", "error:unknown-option"}
        assert paths[0]["relation"] == "applies_to"
        assert paths[0]["label"] == "Claude Code"
    finally:
        db.close()
