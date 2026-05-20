"""Config-driven backend boundaries for the global memory wiki.

The production adapters are deliberately interface placeholders in this slice.
Local filesystem and SQLite implementations give tests and small deployments a
dependency-free path while cloud/database backends report safe unavailable
health until their optional provider packages are installed by a future plugin.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import time
from typing import Any, Dict, List, Optional, Protocol


BACKEND_ROLES = ("object", "state", "lexical", "vector", "graph")
APPROVED_STATES = {"approved", "canonical", "applied"}
GLOBAL_VISIBILITIES = {"global", "global_candidate", "shared"}
PRIVATE_SCOPES = {"private", "tenant", "tenant_only", "tenant-only", "local", "personal"}
SECRET_SENSITIVITIES = {"secret", "sensitive", "confidential", "restricted"}
LOCAL_BACKENDS = {
    "object": {"local", "memory"},
    "state": {"sqlite", "memory"},
    "lexical": {"sqlite_fts", "memory"},
    "vector": {"disabled", "local_fake"},
    "graph": {"disabled", "sqlite", "memory"},
}
PRODUCTION_BACKENDS = {
    "object": {"s3", "gcs", "azure", "minio"},
    "state": {"postgres", "delta", "iceberg"},
    "lexical": {"postgres_fts", "opensearch"},
    "vector": {"pgvector", "qdrant", "weaviate", "pinecone"},
    "graph": {"postgres", "neo4j", "neptune"},
}
DROP_KEYS = {
    "provider_logs",
    "provider_log",
    "debug_log",
    "unbounded_logs",
    "private_tenant_records",
}
REJECT_KEYS = {
    "raw_transcript",
    "raw_transcripts",
    "transcript",
    "raw_proposal",
    "raw_proposals",
    "proposal_text",
    "raw_provider_log",
}
SECRET_KEYS = {"secret", "token", "api_key", "apikey", "password", "authorization", "credential"}
SECRET_VALUE_RE = re.compile(
    r"(sk-[A-Za-z0-9_-]{12,}|AKIA[0-9A-Z]{12,}|xox[baprs]-[A-Za-z0-9-]{12,}|"
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----)",
    re.I,
)


class ObjectStoreAdapter(Protocol):
    def put_json(self, key: str, payload: Dict[str, Any]) -> None: ...
    def get_json(self, key: str) -> Dict[str, Any]: ...


class StateStoreAdapter(Protocol):
    def upsert(self, item_id: str, payload: Dict[str, Any]) -> None: ...
    def get(self, item_id: str) -> Optional[Dict[str, Any]]: ...


class SearchIndexAdapter(Protocol):
    def upsert(self, item_id: str, payload: Dict[str, Any]) -> None: ...
    def search(self, query: str, limit: int = 10) -> List[Dict[str, Any]]: ...


class GraphIndexAdapter(Protocol):
    def upsert(self, item_id: str, payload: Dict[str, Any]) -> None: ...
    def neighbors(self, item_id: str, limit: int = 10) -> List[Dict[str, Any]]: ...


@dataclass
class BackendHealth:
    role: str
    backend: str
    status: str
    enabled: bool
    dependency_free: bool
    local_only: bool
    reason: str = ""
    error: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class UnavailableBackend:
    def __init__(self, role: str, backend: str, reason: str) -> None:
        self.health = BackendHealth(
            role=role,
            backend=backend,
            status="unavailable",
            enabled=True,
            dependency_free=False,
            local_only=False,
            reason=reason,
        )

    def put_json(self, key: str, payload: Dict[str, Any]) -> None:
        raise RuntimeError(self.health.reason)

    def get_json(self, key: str) -> Dict[str, Any]:
        raise RuntimeError(self.health.reason)

    def upsert(self, item_id: str, payload: Dict[str, Any]) -> None:
        raise RuntimeError(self.health.reason)

    def get(self, item_id: str) -> Optional[Dict[str, Any]]:
        raise RuntimeError(self.health.reason)

    def search(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        raise RuntimeError(self.health.reason)

    def neighbors(self, item_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        raise RuntimeError(self.health.reason)


class DisabledBackend(UnavailableBackend):
    def __init__(self, role: str) -> None:
        self.health = BackendHealth(
            role=role,
            backend="disabled",
            status="disabled",
            enabled=False,
            dependency_free=True,
            local_only=True,
            reason="backend disabled by config",
        )


class LocalObjectStore:
    def __init__(self, root: str) -> None:
        self.root = _expand_path(root or "~/.hermes/memory-wiki/global")
        self.health = BackendHealth("object", "local", "ready", True, True, True)

    def put_json(self, key: str, payload: Dict[str, Any]) -> None:
        data = sanitize_indexable_payload(payload)
        path = _safe_child(self.root, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, sort_keys=True, ensure_ascii=False), encoding="utf-8")

    def get_json(self, key: str) -> Dict[str, Any]:
        return json.loads(_safe_child(self.root, key).read_text(encoding="utf-8"))


class SQLiteStateStore:
    def __init__(self, uri: str, *, role: str = "state", backend: str = "sqlite") -> None:
        self.path = _expand_path(uri or "~/.hermes/memory-wiki/global/state.sqlite")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS memory_wiki_state (
                id TEXT PRIMARY KEY,
                payload_json TEXT NOT NULL,
                updated_at REAL NOT NULL
            )
            """
        )
        self._conn.commit()
        self.health = BackendHealth(role, backend, "ready", True, True, True)

    def upsert(self, item_id: str, payload: Dict[str, Any]) -> None:
        data = sanitize_indexable_payload(payload)
        self._conn.execute(
            """
            INSERT INTO memory_wiki_state (id, payload_json, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                payload_json = excluded.payload_json,
                updated_at = excluded.updated_at
            """,
            (item_id, json.dumps(data, sort_keys=True, ensure_ascii=False), time.time()),
        )
        self._conn.commit()

    def get(self, item_id: str) -> Optional[Dict[str, Any]]:
        row = self._conn.execute(
            "SELECT payload_json FROM memory_wiki_state WHERE id = ?",
            (item_id,),
        ).fetchone()
        return json.loads(row["payload_json"]) if row else None


class SQLiteLexicalIndex(SQLiteStateStore):
    def __init__(self, uri: str) -> None:
        super().__init__(uri or "~/.hermes/memory-wiki/global/lexical.sqlite", role="lexical", backend="sqlite_fts")

    def search(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        terms = _tokens(query)
        rows = self._conn.execute(
            "SELECT id, payload_json FROM memory_wiki_state ORDER BY updated_at DESC"
        ).fetchall()
        scored: List[tuple[int, Dict[str, Any]]] = []
        for row in rows:
            payload = json.loads(row["payload_json"])
            haystack = _search_text(payload)
            score = sum(1 for term in terms if term in haystack)
            if score:
                scored.append((score, {"id": row["id"], "score": score, "payload": payload}))
        scored.sort(key=lambda item: (-item[0], item[1]["id"]))
        return [item for _, item in scored[: max(1, int(limit))]]


class LocalFakeVectorIndex(SQLiteStateStore):
    def __init__(self, uri: str) -> None:
        super().__init__(uri or "~/.hermes/memory-wiki/global/vector.sqlite", role="vector", backend="local_fake")

    def search(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        query_tokens = set(_tokens(query))
        rows = self._conn.execute(
            "SELECT id, payload_json FROM memory_wiki_state ORDER BY updated_at DESC"
        ).fetchall()
        scored: List[tuple[float, Dict[str, Any]]] = []
        for row in rows:
            payload = json.loads(row["payload_json"])
            doc_tokens = set(_tokens(_search_text(payload)))
            overlap = len(query_tokens & doc_tokens)
            if overlap:
                score = overlap / max(1, len(query_tokens | doc_tokens))
                scored.append((score, {"id": row["id"], "score": score, "payload": payload}))
        scored.sort(key=lambda item: (-item[0], item[1]["id"]))
        return [item for _, item in scored[: max(1, int(limit))]]


class SQLiteGraphIndex:
    def __init__(self, uri: str) -> None:
        self.path = _expand_path(uri or "~/.hermes/memory-wiki/global/graph.sqlite")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS memory_wiki_edges (source_id TEXT, target_id TEXT, relation TEXT, PRIMARY KEY(source_id, target_id, relation))"
        )
        self._conn.commit()
        self.health = BackendHealth("graph", "sqlite", "ready", True, True, True)

    def upsert(self, item_id: str, payload: Dict[str, Any]) -> None:
        data = sanitize_indexable_payload(payload)
        refs = data.get("evidence_refs") if isinstance(data.get("evidence_refs"), list) else []
        for ref in refs:
            self._conn.execute(
                "INSERT OR REPLACE INTO memory_wiki_edges (source_id, target_id, relation) VALUES (?, ?, ?)",
                (item_id, str(ref), "EVIDENCED_BY"),
            )
        self._conn.commit()

    def neighbors(self, item_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        rows = self._conn.execute(
            """
            SELECT source_id, target_id, relation
            FROM memory_wiki_edges
            WHERE source_id = ?
            ORDER BY target_id
            LIMIT ?
            """,
            (item_id, max(1, int(limit))),
        ).fetchall()
        return [dict(row) for row in rows]


@dataclass
class MemoryWikiBackendBundle:
    object_store: Any
    state_store: Any
    lexical_index: Any
    vector_index: Any
    graph_index: Any

    def health(self) -> List[BackendHealth]:
        return [
            self.object_store.health,
            self.state_store.health,
            self.lexical_index.health,
            self.vector_index.health,
            self.graph_index.health,
        ]

    def to_dict(self) -> Dict[str, Any]:
        return {"backends": [item.to_dict() for item in self.health()]}


def sanitize_indexable_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("indexable payload must be an object")
    state = str(payload.get("approval_state") or payload.get("status") or "").lower()
    if state not in APPROVED_STATES:
        raise ValueError("approval_state must be approved, canonical, or applied")
    scope = _normalized_marker(payload.get("scope"))
    visibility = _normalized_marker(payload.get("visibility") or payload.get("scope"))
    sensitivity = _normalized_marker(payload.get("sensitivity"))
    shareable = payload.get("shareable")
    global_safe = payload.get("global_safe")
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    metadata_visibility = _normalized_marker(metadata.get("visibility") or metadata.get("scope"))
    if scope in PRIVATE_SCOPES:
        raise ValueError("scope must be global for indexable payloads")
    if sensitivity in SECRET_SENSITIVITIES:
        raise ValueError("sensitivity is not indexable")
    if metadata_visibility in PRIVATE_SCOPES and shareable is not True and global_safe is not True:
        raise ValueError("tenant-private metadata is not globally shareable")
    if visibility in PRIVATE_SCOPES:
        raise ValueError("shareable global visibility is required")
    if visibility not in GLOBAL_VISIBILITIES and scope != "global":
        raise ValueError("shareable global visibility is required")
    if shareable is not True and global_safe is not True:
        raise ValueError("shareable global approval is required")
    return _sanitize_value(payload, path="")


def build_memory_wiki_backends(config: Dict[str, Any]) -> MemoryWikiBackendBundle:
    wiki = ((config or {}).get("supervisor") or {}).get("global_memory_wiki") or {}
    object_cfg = _cfg(wiki, "object_store", "local")
    state_cfg = _cfg(wiki, "state_store", "sqlite")
    lexical_cfg = _cfg(wiki, "lexical_index", "sqlite_fts")
    vector_cfg = _cfg(wiki, "vector_index", "disabled")
    graph_cfg = _cfg(wiki, "graph_index", "sqlite")
    return MemoryWikiBackendBundle(
        object_store=_build_backend("object", object_cfg),
        state_store=_build_backend("state", state_cfg),
        lexical_index=_build_backend("lexical", lexical_cfg),
        vector_index=_build_backend("vector", vector_cfg),
        graph_index=_build_backend("graph", graph_cfg),
    )


def _build_backend(role: str, cfg: Dict[str, Any]) -> Any:
    backend = str(cfg.get("backend") or "").lower()
    uri = str(cfg.get("uri") or "")
    if backend == "disabled":
        return DisabledBackend(role)
    if role == "object" and backend in {"local", "memory"}:
        return LocalObjectStore(uri)
    if role == "state" and backend in {"sqlite", "memory"}:
        return SQLiteStateStore(uri)
    if role == "lexical" and backend in {"sqlite_fts", "memory"}:
        return SQLiteLexicalIndex(uri)
    if role == "vector" and backend == "local_fake":
        return LocalFakeVectorIndex(uri)
    if role == "graph" and backend in {"sqlite", "memory"}:
        return SQLiteGraphIndex(uri)
    if backend in PRODUCTION_BACKENDS.get(role, set()):
        return UnavailableBackend(role, backend, f"{role} backend {backend} configured but optional adapter is not installed")
    return UnavailableBackend(role, backend or "unknown", f"{role} backend {backend or 'unknown'} is not supported")


def _cfg(wiki: Dict[str, Any], key: str, default_backend: str) -> Dict[str, Any]:
    value = wiki.get(key) if isinstance(wiki.get(key), dict) else {}
    return {"backend": default_backend, **value}


def _sanitize_value(value: Any, *, path: str) -> Any:
    if isinstance(value, dict):
        result: Dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            lowered = key_text.lower()
            child_path = f"{path}.{lowered}" if path else lowered
            if lowered in REJECT_KEYS:
                raise ValueError(f"{lowered} is not indexable")
            if lowered in DROP_KEYS:
                continue
            if any(marker in lowered for marker in SECRET_KEYS):
                result[key_text] = "[REDACTED]"
                continue
            result[key_text] = _sanitize_value(item, path=child_path)
        return result
    if isinstance(value, list):
        return [_sanitize_value(item, path=path) for item in value]
    if isinstance(value, str) and SECRET_VALUE_RE.search(value):
        return SECRET_VALUE_RE.sub("[REDACTED]", value)
    return value


def _normalized_marker(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "_")


def _expand_path(uri: str) -> Path:
    return Path(uri).expanduser()


def _safe_child(root: Path, key: str) -> Path:
    path = (root / key).resolve()
    root_resolved = root.resolve()
    if root_resolved not in path.parents and path != root_resolved:
        raise ValueError("object key escapes object store root")
    return path


def _tokens(text: str) -> List[str]:
    return re.findall(r"[a-z0-9_:/.-]+", str(text or "").lower())


def _search_text(payload: Dict[str, Any]) -> str:
    parts = [
        str(payload.get("id") or ""),
        str(payload.get("title") or ""),
        str(payload.get("text") or payload.get("claim") or ""),
        " ".join(str(ref) for ref in payload.get("evidence_refs") or []),
        json.dumps(payload.get("metadata") or {}, sort_keys=True),
    ]
    return " ".join(parts).lower()


def payload_hash(payload: Dict[str, Any]) -> str:
    data = sanitize_indexable_payload(payload)
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode("utf-8")).hexdigest()
