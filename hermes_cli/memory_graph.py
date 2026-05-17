"""SQLite graph helpers for explaining why memory applies."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import time
from typing import Any, Dict, List, Optional

from hermes_state import SessionDB


def _now() -> float:
    return time.time()


@dataclass
class MemoryGraphNode:
    id: str
    kind: str
    label: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class MemoryGraphEdge:
    source_id: str
    target_id: str
    relation: str
    weight: float = 1.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def ensure_memory_graph_schema(db: SessionDB) -> None:
    def _do(conn):
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS hermes_memory_graph_nodes (
                id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                label TEXT NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS hermes_memory_graph_edges (
                source_id TEXT NOT NULL,
                target_id TEXT NOT NULL,
                relation TEXT NOT NULL,
                weight REAL NOT NULL DEFAULT 1.0,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                PRIMARY KEY(source_id, target_id, relation)
            )
            """
        )

    db._execute_write(_do)


def upsert_graph_node(db: SessionDB, *, node_id: str, kind: str, label: str) -> MemoryGraphNode:
    ensure_memory_graph_schema(db)
    now = _now()

    def _do(conn):
        conn.execute(
            """
            INSERT INTO hermes_memory_graph_nodes (id, kind, label, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                kind = excluded.kind,
                label = excluded.label,
                updated_at = excluded.updated_at
            """,
            (node_id, kind, label, now, now),
        )

    db._execute_write(_do)
    return MemoryGraphNode(id=node_id, kind=kind, label=label)


def upsert_graph_edge(
    db: SessionDB,
    *,
    source_id: str,
    target_id: str,
    relation: str,
    weight: float = 1.0,
) -> MemoryGraphEdge:
    ensure_memory_graph_schema(db)
    now = _now()

    def _do(conn):
        conn.execute(
            """
            INSERT INTO hermes_memory_graph_edges (source_id, target_id, relation, weight, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_id, target_id, relation) DO UPDATE SET
                weight = excluded.weight,
                updated_at = excluded.updated_at
            """,
            (source_id, target_id, relation, float(weight), now, now),
        )

    db._execute_write(_do)
    return MemoryGraphEdge(source_id=source_id, target_id=target_id, relation=relation, weight=float(weight))


def expand_graph(
    db: SessionDB,
    *,
    start_id: str,
    relation: Optional[str] = None,
    limit: int = 10,
) -> List[Dict[str, Any]]:
    ensure_memory_graph_schema(db)
    clauses = ["e.source_id = ?"]
    params: List[Any] = [start_id]
    if relation:
        clauses.append("e.relation = ?")
        params.append(relation)
    rows = db._conn.execute(
        f"""
        SELECT e.source_id, e.target_id, e.relation, e.weight, n.kind, n.label
        FROM hermes_memory_graph_edges e
        LEFT JOIN hermes_memory_graph_nodes n ON n.id = e.target_id
        WHERE {' AND '.join(clauses)}
        ORDER BY e.weight DESC
        LIMIT ?
        """,
        (*params, max(1, int(limit))),
    ).fetchall()
    return [dict(row) for row in rows]
