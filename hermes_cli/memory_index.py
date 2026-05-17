"""Local lexical/vector index scaffolding for Hermes memory retrieval."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import re
import time
from typing import Any, Dict, Iterable, List, Optional

from hermes_state import SessionDB


def _now() -> float:
    return time.time()


def _json_dumps(value: Any) -> str:
    return json.dumps(value or {}, sort_keys=True)


def _json_loads(value: Any) -> Dict[str, Any]:
    if not value:
        return {}
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(value)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def extract_lexical_terms(text: str) -> List[str]:
    terms = []
    for token in re.findall(r"[A-Za-z0-9_./:@-]+", text or ""):
        cleaned = token.strip().casefold()
        if len(cleaned) >= 2:
            terms.append(cleaned)
    return sorted(set(terms))


@dataclass
class MemoryIndexDocument:
    memory_id: str
    text: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    terms: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def ensure_memory_index_schema(db: SessionDB) -> None:
    def _do(conn):
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS hermes_memory_index (
                memory_id TEXT PRIMARY KEY,
                tenant_id TEXT,
                repo_id TEXT,
                tool TEXT,
                task_type TEXT,
                tier TEXT,
                status TEXT,
                text TEXT NOT NULL,
                metadata_json TEXT,
                terms_json TEXT,
                vector_json TEXT,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_hermes_memory_index_scope
                ON hermes_memory_index(tenant_id, repo_id, tool, task_type, status)
            """
        )

    db._execute_write(_do)


def upsert_memory_index_document(
    db: SessionDB,
    *,
    memory_id: str,
    text: str,
    metadata: Optional[Dict[str, Any]] = None,
    vector: Optional[Iterable[float]] = None,
) -> MemoryIndexDocument:
    ensure_memory_index_schema(db)
    meta = metadata or {}
    terms = extract_lexical_terms(
        " ".join(
            [
                text,
                str(meta.get("command") or ""),
                str(meta.get("flags") or ""),
                str(meta.get("file_path") or ""),
                str(meta.get("branch") or ""),
                str(meta.get("tool") or ""),
                str(meta.get("error_signature") or ""),
            ]
        )
    )
    now = _now()

    def _do(conn):
        conn.execute(
            """
            INSERT INTO hermes_memory_index (
                memory_id, tenant_id, repo_id, tool, task_type, tier, status,
                text, metadata_json, terms_json, vector_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(memory_id) DO UPDATE SET
                tenant_id = excluded.tenant_id,
                repo_id = excluded.repo_id,
                tool = excluded.tool,
                task_type = excluded.task_type,
                tier = excluded.tier,
                status = excluded.status,
                text = excluded.text,
                metadata_json = excluded.metadata_json,
                terms_json = excluded.terms_json,
                vector_json = excluded.vector_json,
                updated_at = excluded.updated_at
            """,
            (
                memory_id,
                meta.get("tenant_id"),
                meta.get("repo_id"),
                meta.get("tool"),
                meta.get("task_type"),
                meta.get("tier"),
                meta.get("status"),
                text,
                _json_dumps(meta),
                _json_dumps(terms),
                _json_dumps(list(vector) if vector is not None else []),
                now,
                now,
            ),
        )

    db._execute_write(_do)
    return MemoryIndexDocument(memory_id=memory_id, text=text, metadata=meta, terms=terms)


def lexical_search(
    db: SessionDB,
    *,
    query: str,
    tenant_id: Optional[str] = None,
    repo_id: Optional[str] = None,
    statuses: Optional[Iterable[str]] = None,
    limit: int = 10,
) -> List[Dict[str, Any]]:
    ensure_memory_index_schema(db)
    query_terms = set(extract_lexical_terms(query))
    if not query_terms:
        return []
    allowed_statuses = {str(status) for status in (statuses or ["approved", "applied", "active"]) if status}
    rows = db._conn.execute(
        """
        SELECT * FROM hermes_memory_index
        ORDER BY updated_at DESC
        LIMIT 500
        """
    ).fetchall()
    matches: List[Dict[str, Any]] = []
    for row in rows:
        meta = _json_loads(row["metadata_json"])
        status = str(row["status"] or meta.get("status") or "")
        if status and status not in allowed_statuses:
            continue
        if tenant_id is not None and row["tenant_id"] not in {None, tenant_id}:
            continue
        if repo_id is not None and row["repo_id"] not in {None, repo_id}:
            continue
        try:
            parsed_terms = json.loads(row["terms_json"] or "[]")
        except Exception:
            parsed_terms = []
        terms = set(parsed_terms if isinstance(parsed_terms, list) else [])
        if not terms:
            terms = set(extract_lexical_terms(row["text"] or ""))
        overlap = query_terms & terms
        if not overlap:
            continue
        matches.append(
            {
                "memory_id": row["memory_id"],
                "text": row["text"],
                "metadata": meta,
                "lexical_score": len(overlap) / max(1, len(query_terms)),
                "matched_terms": sorted(overlap),
            }
        )
    matches.sort(key=lambda item: item["lexical_score"], reverse=True)
    return matches[: max(1, int(limit))]


def vector_search(
    db: SessionDB,
    *,
    query_vector: Iterable[float],
    tenant_id: Optional[str] = None,
    repo_id: Optional[str] = None,
    statuses: Optional[Iterable[str]] = None,
    limit: int = 10,
) -> List[Dict[str, Any]]:
    """Vector placeholder that still enforces hard scope/status filters."""
    ensure_memory_index_schema(db)
    allowed_statuses = {str(status) for status in (statuses or ["approved", "applied", "active"]) if status}
    query = list(query_vector)
    rows = db._conn.execute("SELECT * FROM hermes_memory_index ORDER BY updated_at DESC LIMIT 500").fetchall()
    matches: List[Dict[str, Any]] = []
    for row in rows:
        meta = _json_loads(row["metadata_json"])
        status = str(row["status"] or meta.get("status") or "")
        if status and status not in allowed_statuses:
            continue
        if tenant_id is not None and row["tenant_id"] not in {None, tenant_id}:
            continue
        if repo_id is not None and row["repo_id"] not in {None, repo_id}:
            continue
        vector = json.loads(row["vector_json"] or "[]")
        if not isinstance(vector, list) or not vector or len(vector) != len(query):
            continue
        dot = sum(float(a) * float(b) for a, b in zip(query, vector))
        matches.append(
            {
                "memory_id": row["memory_id"],
                "text": row["text"],
                "metadata": meta,
                "vector_score": dot,
            }
        )
    matches.sort(key=lambda item: item["vector_score"], reverse=True)
    return matches[: max(1, int(limit))]
