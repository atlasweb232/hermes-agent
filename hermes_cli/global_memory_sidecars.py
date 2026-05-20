"""Explicit local sidecars for global-memory indexing and sync.

These helpers are intentionally SQLite-only. They run only when called by an
operator/CLI/API surface and never hook into foreground retrieval paths.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import re
import time
from typing import Any, Dict, List, Optional

from hermes_cli.global_memory import (
    ensure_global_hot_cache_schema,
    ensure_global_lesson_schema,
    materialize_global_lesson_to_hot_cache,
    simple_simhash,
    stable_hash,
    text_hash,
)
from hermes_state import SessionDB


APPROVED_CANONICAL_STATES = {"approved", "canonical", "applied"}
SECRET_RE = re.compile(
    r"(?i)(sk-[a-z0-9_-]{8,}|api[_-]?key|secret|password|token|"
    r"provider[_-]?log|raw[_-]?transcript|raw[_-]?proposal)"
)
TERM_RE = re.compile(r"[a-z0-9][a-z0-9_.:/-]{2,}", re.IGNORECASE)


@dataclass
class GlobalIndexerSidecarResult:
    status: str
    feature_enabled: bool
    scanned: int = 0
    indexed: int = 0
    updated: int = 0
    skipped: int = 0
    synced: int = 0
    demoted: int = 0
    removed: int = 0
    errors: List[str] = field(default_factory=list)
    refs: Dict[str, List[Dict[str, str]]] = field(
        default_factory=lambda: {"indexed": [], "updated": [], "skipped": [], "removed": []}
    )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class LocalSyncSidecarResult:
    status: str
    feature_enabled: bool
    scanned: int = 0
    indexed: int = 0
    updated: int = 0
    skipped: int = 0
    synced: int = 0
    demoted: int = 0
    removed: int = 0
    errors: List[str] = field(default_factory=list)
    refs: Dict[str, List[Dict[str, str]]] = field(
        default_factory=lambda: {"synced": [], "updated": [], "skipped": [], "demoted": [], "removed": []}
    )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _now() -> float:
    return time.time()


def _sidecar_cfg(config: Dict[str, Any], name: str) -> Dict[str, Any]:
    wiki = ((config or {}).get("supervisor") or {}).get("global_memory_wiki") or {}
    sidecars = wiki.get("sidecars") or {}
    cfg = sidecars.get(name) or {}
    return cfg if isinstance(cfg, dict) else {}


def _is_enabled(config: Dict[str, Any], name: str) -> bool:
    cfg = _sidecar_cfg(config, name)
    return bool(cfg.get("enabled", False)) and str(cfg.get("mode", "local")) == "local"


def _max_batch(config: Dict[str, Any], name: str, override: Optional[int]) -> int:
    if override is not None:
        return max(1, int(override))
    cfg = _sidecar_cfg(config, name)
    return max(1, int(cfg.get("max_batch", 100)))


def _ttl_seconds(config: Dict[str, Any], override: Optional[int]) -> int:
    if override is not None:
        return int(override)
    cfg = _sidecar_cfg(config, "local_sync")
    return int(cfg.get("ttl_seconds", 3600))


def ensure_global_lesson_index_schema(db: SessionDB) -> None:
    def _do(conn):
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS hermes_global_lesson_index (
                lesson_id TEXT PRIMARY KEY,
                text_hash TEXT NOT NULL,
                simhash TEXT NOT NULL,
                lexical_terms_json TEXT NOT NULL,
                graph_keys_json TEXT NOT NULL,
                vector_stub_json TEXT NOT NULL,
                metadata_json TEXT NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                retired_at REAL,
                deleted_at REAL
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_hermes_global_lesson_index_active
                ON hermes_global_lesson_index(deleted_at, updated_at DESC)
            """
        )

    db._execute_write(_do)


def ensure_global_sync_delta_schema(db: SessionDB) -> None:
    def _do(conn):
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS hermes_global_sync_deltas (
                id TEXT PRIMARY KEY,
                lesson_id TEXT NOT NULL,
                tenant_id TEXT,
                repo_id TEXT,
                tool TEXT,
                task_type TEXT,
                action TEXT NOT NULL,
                applied_at REAL NOT NULL,
                expires_at REAL,
                metadata_json TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_hermes_global_sync_deltas_scope
                ON hermes_global_sync_deltas(tenant_id, repo_id, tool, task_type, lesson_id)
            """
        )

    db._execute_write(_do)


def _safe_terms(text: str) -> List[str]:
    terms: List[str] = []
    seen = set()
    for token in TERM_RE.findall(str(text or "").lower()):
        if SECRET_RE.search(token):
            continue
        if token not in seen:
            seen.add(token)
            terms.append(token)
        if len(terms) >= 32:
            break
    return terms


def _graph_keys(row: Dict[str, Any], terms: List[str]) -> List[str]:
    keys = []
    for key in ("tool", "task_type", "worker_kind", "failure_signature", "success_signature", "scope"):
        value = str(row.get(key) or "").strip()
        if value and not SECRET_RE.search(value):
            keys.append(f"{key}:{stable_hash(value)[:16]}")
    keys.extend(f"term:{stable_hash(term)[:12]}" for term in terms[:12])
    return keys


def _skip_reason(row: Dict[str, Any]) -> Optional[str]:
    if row.get("retired_at") is not None:
        return "retired_or_deleted"
    if str(row.get("approval_state") or "") not in APPROVED_CANONICAL_STATES:
        return "not_approved_canonical"
    if str(row.get("scope") or "") != "global":
        return "not_global_scope"
    if str(row.get("sensitivity") or "") == "secret":
        return "secret_sensitivity"
    if not bool(row.get("cross_tenant_shareable")):
        return "not_cross_tenant_shareable"
    if SECRET_RE.search(str(row.get("normalized_text") or "")):
        return "secret_like_content"
    return None


def _bounded_ref(lesson_id: str, reason: str = "") -> Dict[str, str]:
    ref = {"id": str(lesson_id)[:96]}
    if reason:
        ref["reason"] = reason
    return ref


def _scan_lessons(db: SessionDB, limit: int) -> List[Dict[str, Any]]:
    ensure_global_lesson_schema(db)

    def _fetch(conn):
        rows = conn.execute(
            """
            SELECT * FROM hermes_global_lessons
            ORDER BY updated_at DESC, id ASC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]

    return db._execute_write(_fetch)


def run_global_indexer_sidecar(
    db: SessionDB,
    config: Dict[str, Any],
    *,
    once: bool = True,
    limit: Optional[int] = None,
) -> GlobalIndexerSidecarResult:
    if not once:
        return GlobalIndexerSidecarResult(
            status="requires_once",
            feature_enabled=_is_enabled(config, "global_indexer"),
        )
    if not _is_enabled(config, "global_indexer"):
        return GlobalIndexerSidecarResult(status="disabled", feature_enabled=False)

    ensure_global_lesson_index_schema(db)
    result = GlobalIndexerSidecarResult(status="ok", feature_enabled=True)
    for row in _scan_lessons(db, _max_batch(config, "global_indexer", limit)):
        result.scanned += 1
        lesson_id = str(row.get("id") or "")
        reason = _skip_reason(row)
        if reason:
            result.skipped += 1
            result.refs["skipped"].append(_bounded_ref(lesson_id, reason))
            if reason == "retired_or_deleted":
                removed = _mark_index_removed(db, lesson_id, row.get("retired_at"))
                if removed:
                    result.removed += removed
                    result.refs["removed"].append(_bounded_ref(lesson_id, reason))
            continue

        normalized = str(row.get("normalized_text") or "")
        terms = _safe_terms(normalized)
        now = _now()
        metadata = {
            "approval_state": row.get("approval_state"),
            "scope": row.get("scope"),
            "sensitivity": row.get("sensitivity"),
            "visibility": row.get("visibility"),
            "tool": row.get("tool") or "",
            "task_type": row.get("task_type") or "",
            "failure_signature_hash": stable_hash(row.get("failure_signature") or "")[:24],
            "success_signature_hash": stable_hash(row.get("success_signature") or "")[:24],
        }
        payload = {
            "lesson_id": lesson_id,
            "text_hash": row.get("text_hash") or text_hash(normalized),
            "simhash": row.get("simhash") or simple_simhash(normalized),
            "lexical_terms_json": json.dumps(terms, sort_keys=True),
            "graph_keys_json": json.dumps(_graph_keys(row, terms), sort_keys=True),
            "vector_stub_json": json.dumps(
                {
                    "backend": "disabled",
                    "text_hash": row.get("text_hash") or text_hash(normalized),
                    "dims": 0,
                },
                sort_keys=True,
            ),
            "metadata_json": json.dumps(metadata, sort_keys=True),
            "updated_at": now,
        }

        def _upsert(conn):
            existing = conn.execute(
                "SELECT lesson_id FROM hermes_global_lesson_index WHERE lesson_id = ?",
                (lesson_id,),
            ).fetchone()
            if existing:
                conn.execute(
                    """
                    UPDATE hermes_global_lesson_index
                    SET text_hash = ?, simhash = ?, lexical_terms_json = ?, graph_keys_json = ?,
                        vector_stub_json = ?, metadata_json = ?, updated_at = ?, retired_at = NULL, deleted_at = NULL
                    WHERE lesson_id = ?
                    """,
                    (
                        payload["text_hash"],
                        payload["simhash"],
                        payload["lexical_terms_json"],
                        payload["graph_keys_json"],
                        payload["vector_stub_json"],
                        payload["metadata_json"],
                        payload["updated_at"],
                        lesson_id,
                    ),
                )
                return "updated"
            conn.execute(
                """
                INSERT INTO hermes_global_lesson_index (
                    lesson_id, text_hash, simhash, lexical_terms_json, graph_keys_json,
                    vector_stub_json, metadata_json, created_at, updated_at, retired_at, deleted_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL)
                """,
                (
                    lesson_id,
                    payload["text_hash"],
                    payload["simhash"],
                    payload["lexical_terms_json"],
                    payload["graph_keys_json"],
                    payload["vector_stub_json"],
                    payload["metadata_json"],
                    now,
                    payload["updated_at"],
                ),
            )
            return "indexed"

        action = db._execute_write(_upsert)
        if action == "indexed":
            result.indexed += 1
            result.refs["indexed"].append(_bounded_ref(lesson_id))
        else:
            result.updated += 1
            result.refs["updated"].append(_bounded_ref(lesson_id))
    return result


def _mark_index_removed(db: SessionDB, lesson_id: str, retired_at: Any = None) -> int:
    ensure_global_lesson_index_schema(db)
    now = _now()

    def _do(conn):
        cur = conn.execute(
            """
            UPDATE hermes_global_lesson_index
            SET deleted_at = ?, retired_at = COALESCE(?, retired_at)
            WHERE lesson_id = ? AND deleted_at IS NULL
            """,
            (now, retired_at, lesson_id),
        )
        return int(cur.rowcount or 0)

    return db._execute_write(_do)


def _demote_expired_hot_cache(db: SessionDB) -> int:
    ensure_global_hot_cache_schema(db)
    now = _now()

    def _do(conn):
        rows = conn.execute(
            "SELECT id FROM hermes_global_hot_cache WHERE expires_at IS NOT NULL AND expires_at <= ?",
            (now,),
        ).fetchall()
        conn.execute("DELETE FROM hermes_global_hot_cache WHERE expires_at IS NOT NULL AND expires_at <= ?", (now,))
        return len(rows)

    return db._execute_write(_do)


def _remove_ineligible_hot_cache(db: SessionDB) -> int:
    ensure_global_hot_cache_schema(db)
    ensure_global_lesson_schema(db)
    ensure_global_lesson_index_schema(db)
    now = _now()

    def _do(conn):
        rows = conn.execute(
            """
            SELECT h.global_lesson_id
            FROM hermes_global_hot_cache h
            LEFT JOIN hermes_global_lessons l ON l.id = h.global_lesson_id
            WHERE l.id IS NULL
               OR l.retired_at IS NOT NULL
               OR l.approval_state NOT IN ('approved', 'canonical', 'applied')
               OR l.scope != 'global'
               OR l.sensitivity = 'secret'
               OR l.cross_tenant_shareable != 1
            """
        ).fetchall()
        lesson_ids = sorted({str(row["global_lesson_id"]) for row in rows})
        for lesson_id in lesson_ids:
            conn.execute("DELETE FROM hermes_global_hot_cache WHERE global_lesson_id = ?", (lesson_id,))
            conn.execute(
                "UPDATE hermes_global_lesson_index SET deleted_at = COALESCE(deleted_at, ?) WHERE lesson_id = ?",
                (now, lesson_id),
            )
        return len(lesson_ids)

    return db._execute_write(_do)


def _remove_orphaned_index_rows(db: SessionDB) -> int:
    ensure_global_lesson_schema(db)
    ensure_global_lesson_index_schema(db)
    now = _now()

    def _do(conn):
        cur = conn.execute(
            """
            UPDATE hermes_global_lesson_index
            SET deleted_at = ?
            WHERE deleted_at IS NULL
              AND NOT EXISTS (
                  SELECT 1
                  FROM hermes_global_lessons l
                  WHERE l.id = hermes_global_lesson_index.lesson_id
              )
            """,
            (now,),
        )
        return int(cur.rowcount or 0)

    return db._execute_write(_do)


def _scan_sync_candidates(db: SessionDB, limit: int) -> List[Dict[str, Any]]:
    ensure_global_lesson_index_schema(db)
    ensure_global_lesson_schema(db)

    def _fetch(conn):
        rows = conn.execute(
            """
            SELECT l.*
            FROM hermes_global_lesson_index i
            JOIN hermes_global_lessons l ON l.id = i.lesson_id
            WHERE i.deleted_at IS NULL
            ORDER BY i.updated_at DESC, l.id ASC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]

    return db._execute_write(_fetch)


def _matches_filter(value: Optional[str], lesson_value: Any) -> bool:
    requested = str(value or "").strip()
    existing = str(lesson_value or "").strip()
    if not requested:
        return True
    return bool(existing) and requested == existing


def _record_delta(
    db: SessionDB,
    lesson_id: str,
    *,
    tenant_id: Optional[str],
    repo_id: Optional[str],
    tool: Optional[str],
    task_type: Optional[str],
    action: str,
    ttl_seconds: int,
) -> None:
    ensure_global_sync_delta_schema(db)
    now = _now()
    delta_id = f"gsync_{stable_hash([lesson_id, tenant_id, repo_id, tool, task_type, action])[:20]}"

    def _do(conn):
        conn.execute(
            """
            INSERT OR REPLACE INTO hermes_global_sync_deltas (
                id, lesson_id, tenant_id, repo_id, tool, task_type, action, applied_at, expires_at, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                delta_id,
                lesson_id,
                tenant_id,
                repo_id,
                tool,
                task_type,
                action,
                now,
                now + ttl_seconds if ttl_seconds > 0 else now,
                json.dumps({"source": "local_sync_sidecar"}, sort_keys=True),
            ),
        )

    db._execute_write(_do)


def _hot_cache_exists(
    db: SessionDB,
    lesson_id: str,
    tenant_id: Optional[str],
    repo_id: Optional[str],
    tool: Optional[str],
    task_type: Optional[str],
) -> bool:
    ensure_global_hot_cache_schema(db)

    def _fetch(conn):
        return conn.execute(
            """
            SELECT 1 FROM hermes_global_hot_cache
            WHERE global_lesson_id = ?
              AND COALESCE(tenant_id, '') = COALESCE(?, '')
              AND COALESCE(repo_id, '') = COALESCE(?, '')
              AND COALESCE(tool, '') = COALESCE(?, '')
              AND COALESCE(task_type, '') = COALESCE(?, '')
            LIMIT 1
            """,
            (lesson_id, tenant_id, repo_id, tool, task_type),
        ).fetchone() is not None

    return bool(db._execute_write(_fetch))


def run_local_sync_sidecar(
    db: SessionDB,
    config: Dict[str, Any],
    *,
    once: bool = True,
    tenant_id: Optional[str] = None,
    repo_id: Optional[str] = None,
    tool: Optional[str] = None,
    task_type: Optional[str] = None,
    limit: Optional[int] = None,
    ttl_seconds: Optional[int] = None,
) -> LocalSyncSidecarResult:
    if not once:
        return LocalSyncSidecarResult(
            status="requires_once",
            feature_enabled=_is_enabled(config, "local_sync"),
        )
    if not _is_enabled(config, "local_sync"):
        return LocalSyncSidecarResult(status="disabled", feature_enabled=False)

    ensure_global_hot_cache_schema(db)
    ensure_global_sync_delta_schema(db)
    result = LocalSyncSidecarResult(status="ok", feature_enabled=True)
    result.demoted = _demote_expired_hot_cache(db)
    if result.demoted:
        result.refs["demoted"].append({"reason": "expired_ttl", "count": str(result.demoted)})
    result.removed = _remove_ineligible_hot_cache(db)
    result.removed += _remove_orphaned_index_rows(db)
    if result.removed:
        result.refs["removed"].append({"reason": "retired_or_deleted", "count": str(result.removed)})

    ttl = _ttl_seconds(config, ttl_seconds)
    for row in _scan_sync_candidates(db, _max_batch(config, "local_sync", limit)):
        result.scanned += 1
        lesson_id = str(row.get("id") or "")
        reason = _skip_reason(row)
        if reason:
            result.skipped += 1
            result.refs["skipped"].append(_bounded_ref(lesson_id, reason))
            continue
        if not (
            _matches_filter(tool, row.get("tool"))
            and _matches_filter(task_type, row.get("task_type"))
        ):
            result.skipped += 1
            result.refs["skipped"].append(_bounded_ref(lesson_id, "not_relevant"))
            continue
        event = {
            "event_id": f"global-sync:{lesson_id}",
            "tenant_id": tenant_id,
            "repo_id": repo_id,
            "tool": tool or row.get("tool") or "",
            "task_type": task_type or row.get("task_type") or "",
            "worker_kind": row.get("worker_kind") or "",
            "failure_signature": row.get("failure_signature") or "",
            "success_signature": row.get("success_signature") or "",
        }
        existed = _hot_cache_exists(
            db,
            lesson_id,
            tenant_id,
            repo_id,
            event["tool"],
            event["task_type"],
        )
        materialize_global_lesson_to_hot_cache(db, row, event, ttl_seconds=ttl)
        if existed:
            result.updated += 1
            result.refs["updated"].append(_bounded_ref(lesson_id))
            action = "update"
        else:
            result.synced += 1
            result.refs["synced"].append(_bounded_ref(lesson_id))
            action = "sync"
        _record_delta(
            db,
            lesson_id,
            tenant_id=tenant_id,
            repo_id=repo_id,
            tool=event["tool"],
            task_type=event["task_type"],
            action=action,
            ttl_seconds=ttl,
        )
    return result
