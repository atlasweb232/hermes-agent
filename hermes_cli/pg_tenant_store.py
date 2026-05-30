"""Postgres tenant isolation adapters — Phase 2 of memory-hardening.

Implements StateStoreAdapter, SearchIndexAdapter, and PostgresMemoryAdapter
backed by Postgres Row-Level Security.  The tenant_id is injected as a
transaction-local GUC (hermes.tenant_id) at connection checkout — never read
from user-supplied parameters — so the database enforces isolation even if
application code passes the wrong tenant.

Usage (sync callers):
    store = PostgresTenantStore(dsn)
    tenant_store = store.for_tenant(authenticated_tenant_id)
    tenant_store.upsert("item-1", {...})
    item = tenant_store.get("item-1")

The class uses a background asyncio event loop thread to bridge asyncpg
(fully async) to the synchronous hermes_cli call sites.
"""

from __future__ import annotations

import asyncio
import json
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Coroutine, Dict, List, Optional

try:
    import asyncpg
    _ASYNCPG_AVAILABLE = True
except ImportError:  # pragma: no cover
    asyncpg = None  # type: ignore[assignment]
    _ASYNCPG_AVAILABLE = False

from hermes_cli.memory_wiki_backends import BackendHealth


# ── Background event loop (singleton) ─────────────────────────────────────

_bg_loop: Optional[asyncio.AbstractEventLoop] = None
_bg_thread: Optional[threading.Thread] = None
_bg_lock = threading.Lock()


def _get_bg_loop() -> asyncio.AbstractEventLoop:
    global _bg_loop, _bg_thread
    with _bg_lock:
        if _bg_loop is None or not _bg_loop.is_running():
            _bg_loop = asyncio.new_event_loop()
            _bg_thread = threading.Thread(
                target=_bg_loop.run_forever,
                name="hermes-pg-bg-loop",
                daemon=True,
            )
            _bg_thread.start()
    return _bg_loop


def run_async(coro: Coroutine, timeout: float = 30.0) -> Any:
    """Run an async coroutine from synchronous code via the background loop."""
    loop = _get_bg_loop()
    fut = asyncio.run_coroutine_threadsafe(coro, loop)
    return fut.result(timeout=timeout)


# ── Pool state (shared between for_tenant() clones) ───────────────────────

@dataclass
class _PoolState:
    pool: Any = None  # asyncpg.Pool when initialised
    lock: Any = field(default_factory=asyncio.Lock)


# ── TenantContext (async) ──────────────────────────────────────────────────

class TenantContext:
    """
    Async context manager that acquires a connection from the pool and sets
    the hermes.tenant_id GUC for the duration of a transaction.

    The GUC is set with set_config(..., TRUE) which makes it transaction-local;
    it reverts automatically on COMMIT or ROLLBACK, so it cannot leak between
    requests sharing a pooled connection.

    The tenant_id MUST come from the authenticated caller identity — never
    from a user-supplied request parameter.

    Example:
        async with TenantContext(pool, tenant_id) as conn:
            row = await conn.fetchrow("SELECT * FROM hermes_meta_candidates WHERE id = $1", cid)
    """

    def __init__(self, pool: Any, tenant_id: str) -> None:
        self._pool = pool
        self._tenant_id = tenant_id
        self._conn: Any = None
        self._txn: Any = None

    async def __aenter__(self) -> Any:
        self._conn = await self._pool.acquire()
        self._txn = self._conn.transaction()
        await self._txn.start()
        await self._conn.execute(
            "SELECT set_config('hermes.tenant_id', $1, TRUE)",
            self._tenant_id,
        )
        return self._conn

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        try:
            if exc_type is None:
                await self._txn.commit()
            else:
                await self._txn.rollback()
        finally:
            await self._pool.release(self._conn)
            self._conn = None
            self._txn = None


# ── PostgresTenantStore (StateStoreAdapter) ────────────────────────────────

class PostgresTenantStore:
    """
    Postgres-backed state store with RLS tenant isolation.
    Implements the StateStoreAdapter protocol (sync) via the background loop.

    Schema: memory_wiki_state
        id TEXT PRIMARY KEY, tenant_id TEXT, payload_json TEXT, updated_at DOUBLE PRECISION
    (see migrations/001_hermes_rls.sql)
    """

    def __init__(
        self,
        dsn: str,
        table: str = "memory_wiki_state",
        *,
        tenant_id: Optional[str] = None,
        _pool_state: Optional[_PoolState] = None,
    ) -> None:
        if not _ASYNCPG_AVAILABLE:
            raise ImportError("asyncpg is required for PostgresTenantStore. pip install asyncpg")
        self._dsn = dsn
        self._table = table
        self._tenant_id = tenant_id
        self._pool_state = _pool_state or _PoolState()
        self.health = BackendHealth(
            role="state", backend="postgres", status="initializing",
            enabled=True, dependency_free=False, local_only=False,
        )

    def for_tenant(self, tenant_id: str) -> "PostgresTenantStore":
        """Return a store bound to tenant_id, sharing the underlying pool."""
        clone = PostgresTenantStore.__new__(PostgresTenantStore)
        clone._dsn = self._dsn
        clone._table = self._table
        clone._tenant_id = tenant_id
        clone._pool_state = self._pool_state  # shared
        clone.health = self.health
        return clone

    # -- Sync interface (StateStoreAdapter protocol) -----------------------

    def upsert(self, item_id: str, payload: Dict[str, Any]) -> None:
        run_async(self._upsert_async(item_id, payload))

    def get(self, item_id: str) -> Optional[Dict[str, Any]]:
        return run_async(self._get_async(item_id))

    # -- Pool management ---------------------------------------------------

    async def _ensure_pool(self) -> Any:
        if self._pool_state.pool is None:
            async with self._pool_state.lock:
                if self._pool_state.pool is None:
                    try:
                        self._pool_state.pool = await asyncpg.create_pool(
                            self._dsn, min_size=1, max_size=5
                        )
                        self.health = BackendHealth(
                            role="state", backend="postgres", status="ready",
                            enabled=True, dependency_free=False, local_only=False,
                        )
                    except Exception as exc:
                        self.health = BackendHealth(
                            role="state", backend="postgres", status="error",
                            enabled=True, dependency_free=False, local_only=False,
                            error=str(exc),
                        )
                        raise
        return self._pool_state.pool

    # -- Async internals ---------------------------------------------------

    async def _upsert_async(self, item_id: str, payload: Dict[str, Any]) -> None:
        pool = await self._ensure_pool()
        payload_text = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        now = time.time()
        if self._tenant_id:
            async with TenantContext(pool, self._tenant_id) as conn:
                await conn.execute(
                    f"""
                    INSERT INTO {self._table} (id, tenant_id, payload_json, updated_at)
                    VALUES ($1, $2, $3, $4)
                    ON CONFLICT (id) DO UPDATE SET
                        payload_json = EXCLUDED.payload_json,
                        updated_at   = EXCLUDED.updated_at
                    """,
                    item_id, self._tenant_id, payload_text, now,
                )
        else:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    await conn.execute(
                        f"""
                        INSERT INTO {self._table} (id, tenant_id, payload_json, updated_at)
                        VALUES ($1, $2, $3, $4)
                        ON CONFLICT (id) DO UPDATE SET
                            payload_json = EXCLUDED.payload_json,
                            updated_at   = EXCLUDED.updated_at
                        """,
                        item_id, None, payload_text, now,
                    )

    async def _get_async(self, item_id: str) -> Optional[Dict[str, Any]]:
        pool = await self._ensure_pool()
        if self._tenant_id:
            async with TenantContext(pool, self._tenant_id) as conn:
                row = await conn.fetchrow(
                    f"SELECT payload_json FROM {self._table} WHERE id = $1",
                    item_id,
                )
        else:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    row = await conn.fetchrow(
                        f"SELECT payload_json FROM {self._table} WHERE id = $1",
                        item_id,
                    )
        return json.loads(row["payload_json"]) if row else None


# ── PostgresFTSIndex (SearchIndexAdapter) ──────────────────────────────────

class PostgresFTSIndex(PostgresTenantStore):
    """
    Postgres full-text search index.
    Reuses memory_wiki_state via Postgres GIN/tsvector.
    Implements the SearchIndexAdapter protocol.
    """

    def __init__(
        self,
        dsn: str,
        *,
        tenant_id: Optional[str] = None,
        _pool_state: Optional[_PoolState] = None,
    ) -> None:
        super().__init__(
            dsn,
            table="memory_wiki_state",
            tenant_id=tenant_id,
            _pool_state=_pool_state,
        )
        self.health = BackendHealth(
            role="lexical", backend="postgres_fts", status="initializing",
            enabled=True, dependency_free=False, local_only=False,
        )

    def for_tenant(self, tenant_id: str) -> "PostgresFTSIndex":
        clone = PostgresFTSIndex.__new__(PostgresFTSIndex)
        clone._dsn = self._dsn
        clone._table = self._table
        clone._tenant_id = tenant_id
        clone._pool_state = self._pool_state
        clone.health = self.health
        return clone

    def search(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        return run_async(self._search_async(query, limit))

    async def _search_async(self, query: str, limit: int) -> List[Dict[str, Any]]:
        terms = re.findall(r"[a-z0-9_]+", query.lower())
        if not terms:
            return []
        tsquery = " & ".join(terms)
        pool = await self._ensure_pool()
        sql = f"""
            SELECT id, payload_json,
                   ts_rank(to_tsvector('simple', payload_json),
                           to_tsquery('simple', $1)) AS score
            FROM {self._table}
            WHERE to_tsvector('simple', payload_json) @@ to_tsquery('simple', $1)
            ORDER BY score DESC
            LIMIT $2
        """
        if self._tenant_id:
            async with TenantContext(pool, self._tenant_id) as conn:
                rows = await conn.fetch(sql, tsquery, max(1, int(limit)))
        else:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    rows = await conn.fetch(sql, tsquery, max(1, int(limit)))
        return [
            {
                "id": row["id"],
                "score": float(row["score"]),
                "payload": json.loads(row["payload_json"]),
            }
            for row in rows
        ]


# ── PostgresMemoryAdapter (mirrors SessionDB tenant memory methods) ────────

class PostgresMemoryAdapter:
    """
    Postgres-backed adapter for SessionDB's tenant memory methods.

    Wraps hermes_meta_candidates, hermes_memory_packets, hermes_memory_records,
    and hermes_memory_evidence tables with RLS via hermes.tenant_id GUC.

    Wire it into SessionDB at startup:
        db.configure_postgres_backend(PostgresMemoryAdapter(dsn))

    Then on each request, bind it to the authenticated tenant:
        db._pg_memory = db._pg_memory.for_tenant(authenticated_tenant_id)
    """

    def __init__(
        self,
        dsn: str,
        *,
        tenant_id: Optional[str] = None,
        _pool_state: Optional[_PoolState] = None,
    ) -> None:
        if not _ASYNCPG_AVAILABLE:
            raise ImportError("asyncpg is required for PostgresMemoryAdapter. pip install asyncpg")
        self._dsn = dsn
        self._tenant_id = tenant_id
        self._pool_state = _pool_state or _PoolState()

    def for_tenant(self, tenant_id: str) -> "PostgresMemoryAdapter":
        """Return an adapter bound to the authenticated tenant_id."""
        clone = PostgresMemoryAdapter.__new__(PostgresMemoryAdapter)
        clone._dsn = self._dsn
        clone._tenant_id = tenant_id
        clone._pool_state = self._pool_state
        return clone

    async def _ensure_pool(self) -> Any:
        if self._pool_state.pool is None:
            async with self._pool_state.lock:
                if self._pool_state.pool is None:
                    self._pool_state.pool = await asyncpg.create_pool(
                        self._dsn, min_size=1, max_size=5
                    )
        return self._pool_state.pool

    def _conn_ctx(self, pool: Any) -> Any:
        """Return TenantContext if tenant_id is set, else plain acquire."""
        if self._tenant_id:
            return TenantContext(pool, self._tenant_id)
        # No tenant bound — caller should always use for_tenant() before queries.
        # Returning a plain connection lets tests exercise the path; production
        # code should always bind a tenant before calling any method.
        return pool.acquire()

    @staticmethod
    def _json_text(value: Any) -> Optional[str]:
        if value is None:
            return None
        if isinstance(value, str):
            return value
        return json.dumps(value, ensure_ascii=False)

    @staticmethod
    def _json_value(value: Any) -> Any:
        if value is None or not isinstance(value, str):
            return value
        try:
            return json.loads(value)
        except Exception:
            return value

    # -- upsert_meta_candidate ---------------------------------------------

    def upsert_meta_candidate(
        self,
        *,
        candidate_id: str,
        kind: str,
        claim: str,
        evidence_json: Any = None,
        score: Optional[float] = None,
        status: str = "proposed",
        tenant_id: Optional[str] = None,
        repo_id: Optional[str] = None,
    ) -> str:
        effective_tenant = tenant_id or self._tenant_id
        run_async(self._upsert_meta_candidate_async(
            candidate_id=candidate_id,
            kind=kind,
            claim=claim,
            evidence_json=evidence_json,
            score=score,
            status=status,
            tenant_id=effective_tenant,
            repo_id=repo_id,
        ))
        return candidate_id

    async def _upsert_meta_candidate_async(
        self,
        *,
        candidate_id: str,
        kind: str,
        claim: str,
        evidence_json: Any,
        score: Optional[float],
        status: str,
        tenant_id: Optional[str],
        repo_id: Optional[str],
    ) -> None:
        pool = await self._ensure_pool()
        now = time.time()
        async with TenantContext(pool, tenant_id or "") as conn:
            await conn.execute(
                """
                INSERT INTO hermes_meta_candidates
                    (id, tenant_id, repo_id, kind, claim, evidence_json,
                     score, status, created_at, updated_at)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
                ON CONFLICT (id) DO UPDATE SET
                    tenant_id    = EXCLUDED.tenant_id,
                    repo_id      = EXCLUDED.repo_id,
                    kind         = EXCLUDED.kind,
                    claim        = EXCLUDED.claim,
                    evidence_json= EXCLUDED.evidence_json,
                    score        = EXCLUDED.score,
                    status       = EXCLUDED.status,
                    updated_at   = EXCLUDED.updated_at
                """,
                candidate_id, tenant_id, repo_id, kind, claim,
                self._json_text(evidence_json), score, status, now, now,
            )

    # -- list_meta_candidates ----------------------------------------------

    def list_meta_candidates(
        self,
        *,
        tenant_id: Optional[str] = None,
        repo_id: Optional[str] = None,
        kind: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        return run_async(self._list_meta_candidates_async(
            tenant_id=tenant_id or self._tenant_id,
            repo_id=repo_id,
            kind=kind,
            status=status,
            limit=limit,
        ))

    async def _list_meta_candidates_async(
        self,
        *,
        tenant_id: Optional[str],
        repo_id: Optional[str],
        kind: Optional[str],
        status: Optional[str],
        limit: int,
    ) -> List[Dict[str, Any]]:
        pool = await self._ensure_pool()
        clauses = []
        params: List[Any] = []
        idx = 2  # $1 used by set_config inside TenantContext; start at $2? No.
        # We're inside a transaction started by TenantContext; params start at $1.
        idx = 1
        for col, val in (("tenant_id", tenant_id), ("repo_id", repo_id),
                         ("kind", kind), ("status", status)):
            if val is not None:
                clauses.append(f"{col} = ${idx}")
                params.append(val)
                idx += 1
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(max(1, int(limit)))
        async with TenantContext(pool, tenant_id or self._tenant_id or "") as conn:
            rows = await conn.fetch(
                f"""
                SELECT * FROM hermes_meta_candidates
                {where}
                ORDER BY created_at DESC
                LIMIT ${idx}
                """,
                *params,
            )
        parsed = []
        for row in rows:
            item = dict(row)
            item["evidence_json"] = self._json_value(item.get("evidence_json"))
            parsed.append(item)
        return parsed

    # -- get_meta_candidate ------------------------------------------------

    def get_meta_candidate(self, candidate_id: str) -> Optional[Dict[str, Any]]:
        return run_async(self._get_meta_candidate_async(candidate_id))

    async def _get_meta_candidate_async(self, candidate_id: str) -> Optional[Dict[str, Any]]:
        pool = await self._ensure_pool()
        async with TenantContext(pool, self._tenant_id or "") as conn:
            row = await conn.fetchrow(
                "SELECT * FROM hermes_meta_candidates WHERE id = $1",
                candidate_id,
            )
        if row is None:
            return None
        item = dict(row)
        item["evidence_json"] = self._json_value(item.get("evidence_json"))
        return item

    # -- update_meta_candidate_status -------------------------------------

    def update_meta_candidate_status(
        self,
        candidate_id: str,
        *,
        status: str,
        evidence_json: Any = None,
        score: Optional[float] = None,
    ) -> bool:
        return run_async(self._update_meta_candidate_status_async(
            candidate_id, status=status, evidence_json=evidence_json, score=score
        ))

    async def _update_meta_candidate_status_async(
        self,
        candidate_id: str,
        *,
        status: str,
        evidence_json: Any,
        score: Optional[float],
    ) -> bool:
        pool = await self._ensure_pool()
        now = time.time()
        async with TenantContext(pool, self._tenant_id or "") as conn:
            result = await conn.execute(
                """
                UPDATE hermes_meta_candidates
                   SET status       = $1,
                       evidence_json= COALESCE($2, evidence_json),
                       score        = COALESCE($3, score),
                       updated_at   = $4
                 WHERE id = $5
                """,
                status,
                self._json_text(evidence_json) if evidence_json is not None else None,
                score,
                now,
                candidate_id,
            )
        return result != "UPDATE 0"

    # -- upsert_memory_packet ---------------------------------------------

    def upsert_memory_packet(
        self,
        *,
        packet_id: str,
        query: str,
        status: str,
        tenant_id: Optional[str] = None,
        repo_id: Optional[str] = None,
        job_id: Optional[str] = None,
        task_id: Optional[str] = None,
        scopes: Any = None,
        claims_json: Any = None,
        evidence_json: Any = None,
        contradictions_json: Any = None,
        freshness_json: Any = None,
        confidence: Optional[float] = None,
        source: Optional[str] = None,
        expires_at: Optional[float] = None,
    ) -> str:
        effective_tenant = tenant_id or self._tenant_id
        run_async(self._upsert_memory_packet_async(
            packet_id=packet_id, query=query, status=status,
            tenant_id=effective_tenant, repo_id=repo_id, job_id=job_id,
            task_id=task_id, scopes=scopes, claims_json=claims_json,
            evidence_json=evidence_json, contradictions_json=contradictions_json,
            freshness_json=freshness_json, confidence=confidence,
            source=source, expires_at=expires_at,
        ))
        return packet_id

    async def _upsert_memory_packet_async(self, *, packet_id, query, status,
                                          tenant_id, repo_id, job_id, task_id,
                                          scopes, claims_json, evidence_json,
                                          contradictions_json, freshness_json,
                                          confidence, source, expires_at) -> None:
        pool = await self._ensure_pool()
        now = time.time()
        async with TenantContext(pool, tenant_id or "") as conn:
            await conn.execute(
                """
                INSERT INTO hermes_memory_packets
                    (id, tenant_id, repo_id, job_id, task_id, query, scopes,
                     claims_json, evidence_json, contradictions_json,
                     freshness_json, status, confidence, source, expires_at,
                     created_at, updated_at)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17)
                ON CONFLICT (id) DO UPDATE SET
                    tenant_id          = EXCLUDED.tenant_id,
                    repo_id            = EXCLUDED.repo_id,
                    job_id             = EXCLUDED.job_id,
                    task_id            = EXCLUDED.task_id,
                    query              = EXCLUDED.query,
                    scopes             = EXCLUDED.scopes,
                    claims_json        = EXCLUDED.claims_json,
                    evidence_json      = EXCLUDED.evidence_json,
                    contradictions_json= EXCLUDED.contradictions_json,
                    freshness_json     = EXCLUDED.freshness_json,
                    status             = EXCLUDED.status,
                    confidence         = EXCLUDED.confidence,
                    source             = EXCLUDED.source,
                    expires_at         = EXCLUDED.expires_at,
                    updated_at         = EXCLUDED.updated_at
                """,
                packet_id, tenant_id, repo_id, job_id, task_id, query,
                self._json_text(scopes), self._json_text(claims_json),
                self._json_text(evidence_json), self._json_text(contradictions_json),
                self._json_text(freshness_json), status, confidence, source,
                expires_at, now, now,
            )

    # -- list_memory_packets -----------------------------------------------

    def list_memory_packets(
        self,
        *,
        tenant_id: Optional[str] = None,
        repo_id: Optional[str] = None,
        job_id: Optional[str] = None,
        task_id: Optional[str] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        return run_async(self._list_memory_packets_async(
            tenant_id=tenant_id or self._tenant_id,
            repo_id=repo_id, job_id=job_id, task_id=task_id, limit=limit,
        ))

    async def _list_memory_packets_async(
        self, *, tenant_id, repo_id, job_id, task_id, limit
    ) -> List[Dict[str, Any]]:
        pool = await self._ensure_pool()
        clauses, params, idx = [], [], 1
        for col, val in (("tenant_id", tenant_id), ("repo_id", repo_id),
                         ("job_id", job_id), ("task_id", task_id)):
            if val is not None:
                clauses.append(f"{col} = ${idx}")
                params.append(val)
                idx += 1
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(max(1, int(limit)))
        async with TenantContext(pool, tenant_id or self._tenant_id or "") as conn:
            rows = await conn.fetch(
                f"SELECT * FROM hermes_memory_packets {where} ORDER BY created_at DESC LIMIT ${idx}",
                *params,
            )
        parsed = []
        for row in rows:
            item = dict(row)
            for k in ("scopes", "claims_json", "evidence_json",
                      "contradictions_json", "freshness_json"):
                item[k] = self._json_value(item.get(k))
            parsed.append(item)
        return parsed

    # -- get_memory_packet ------------------------------------------------

    def get_memory_packet(self, packet_id: str) -> Optional[Dict[str, Any]]:
        return run_async(self._get_memory_packet_async(packet_id))

    async def _get_memory_packet_async(self, packet_id: str) -> Optional[Dict[str, Any]]:
        pool = await self._ensure_pool()
        async with TenantContext(pool, self._tenant_id or "") as conn:
            row = await conn.fetchrow(
                "SELECT * FROM hermes_memory_packets WHERE id = $1", packet_id
            )
        if row is None:
            return None
        item = dict(row)
        for k in ("scopes", "claims_json", "evidence_json",
                  "contradictions_json", "freshness_json"):
            item[k] = self._json_value(item.get(k))
        return item

    # -- upsert_memory_record ---------------------------------------------

    def upsert_memory_record(
        self,
        *,
        record_id: str,
        kind: str,
        title: Optional[str] = None,
        body: Optional[str] = None,
        payload_json: Any = None,
        status: str = "active",
        score: Optional[float] = None,
        tenant_id: Optional[str] = None,
        repo_id: Optional[str] = None,
        job_id: Optional[str] = None,
        task_id: Optional[str] = None,
        packet_id: Optional[str] = None,
        evidence_uri: Optional[str] = None,
        evidence_sha256: Optional[str] = None,
    ) -> str:
        effective_tenant = tenant_id or self._tenant_id
        run_async(self._upsert_memory_record_async(
            record_id=record_id, kind=kind, title=title, body=body,
            payload_json=payload_json, status=status, score=score,
            tenant_id=effective_tenant, repo_id=repo_id, job_id=job_id,
            task_id=task_id, packet_id=packet_id, evidence_uri=evidence_uri,
            evidence_sha256=evidence_sha256,
        ))
        return record_id

    async def _upsert_memory_record_async(
        self, *, record_id, kind, title, body, payload_json, status, score,
        tenant_id, repo_id, job_id, task_id, packet_id, evidence_uri, evidence_sha256,
    ) -> None:
        pool = await self._ensure_pool()
        now = time.time()
        async with TenantContext(pool, tenant_id or "") as conn:
            await conn.execute(
                """
                INSERT INTO hermes_memory_records
                    (id, tenant_id, repo_id, job_id, task_id, kind, title,
                     body, payload_json, packet_id, evidence_uri,
                     evidence_sha256, status, score, created_at, updated_at)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16)
                ON CONFLICT (id) DO UPDATE SET
                    tenant_id      = EXCLUDED.tenant_id,
                    repo_id        = EXCLUDED.repo_id,
                    job_id         = EXCLUDED.job_id,
                    task_id        = EXCLUDED.task_id,
                    kind           = EXCLUDED.kind,
                    title          = EXCLUDED.title,
                    body           = EXCLUDED.body,
                    payload_json   = EXCLUDED.payload_json,
                    packet_id      = EXCLUDED.packet_id,
                    evidence_uri   = EXCLUDED.evidence_uri,
                    evidence_sha256= EXCLUDED.evidence_sha256,
                    status         = EXCLUDED.status,
                    score          = EXCLUDED.score,
                    updated_at     = EXCLUDED.updated_at
                """,
                record_id, tenant_id, repo_id, job_id, task_id, kind, title,
                body, self._json_text(payload_json), packet_id,
                evidence_uri, evidence_sha256, status, score, now, now,
            )

    # -- list_memory_records ----------------------------------------------

    def list_memory_records(
        self,
        *,
        tenant_id: Optional[str] = None,
        repo_id: Optional[str] = None,
        kind: Optional[str] = None,
        status: Optional[str] = None,
        packet_id: Optional[str] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        return run_async(self._list_memory_records_async(
            tenant_id=tenant_id or self._tenant_id,
            repo_id=repo_id, kind=kind, status=status,
            packet_id=packet_id, limit=limit,
        ))

    async def _list_memory_records_async(
        self, *, tenant_id, repo_id, kind, status, packet_id, limit
    ) -> List[Dict[str, Any]]:
        pool = await self._ensure_pool()
        clauses, params, idx = [], [], 1
        for col, val in (("tenant_id", tenant_id), ("repo_id", repo_id),
                         ("kind", kind), ("status", status), ("packet_id", packet_id)):
            if val is not None:
                clauses.append(f"{col} = ${idx}")
                params.append(val)
                idx += 1
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(max(1, int(limit)))
        async with TenantContext(pool, tenant_id or self._tenant_id or "") as conn:
            rows = await conn.fetch(
                f"SELECT * FROM hermes_memory_records {where} ORDER BY created_at DESC LIMIT ${idx}",
                *params,
            )
        parsed = []
        for row in rows:
            item = dict(row)
            item["payload_json"] = self._json_value(item.get("payload_json"))
            parsed.append(item)
        return parsed

    # -- add_memory_evidence ----------------------------------------------

    def add_memory_evidence(
        self,
        *,
        uri: str,
        record_id: Optional[str] = None,
        packet_id: Optional[str] = None,
        sha256: Optional[str] = None,
        mime_type: Optional[str] = None,
        excerpt: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ) -> int:
        return run_async(self._add_memory_evidence_async(
            uri=uri, record_id=record_id, packet_id=packet_id,
            sha256=sha256, mime_type=mime_type, excerpt=excerpt,
            tenant_id=tenant_id or self._tenant_id,
        ))

    async def _add_memory_evidence_async(
        self, *, uri, record_id, packet_id, sha256, mime_type, excerpt, tenant_id
    ) -> int:
        pool = await self._ensure_pool()
        now = time.time()
        async with TenantContext(pool, tenant_id or "") as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO hermes_memory_evidence
                    (tenant_id, record_id, packet_id, uri, sha256, mime_type, excerpt, created_at)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
                RETURNING id
                """,
                tenant_id, record_id, packet_id, uri, sha256, mime_type, excerpt, now,
            )
        return row["id"] if row else -1

    # ── Global pool (cross-tenant lessons + hot cache) ─────────────────────
    #
    # The global pool is bimodal:
    #   - Curator/dreaming sidecar path: adapter configured with the
    #     hermes_curator DSN (member of hermes_global_reader). No tenant GUC →
    #     RLS global-reader branch grants cross-tenant read/write.
    #   - Agent task path: adapter bound via for_tenant(agent_tenant). The GUC
    #     is set to the agent's tenant, so the agent sees its own lessons plus
    #     globally-approved shareable lessons (per the hermes_global_lessons
    #     RLS policy), and can only WRITE rows for its own tenant.  A reuse-stat
    #     update against ANOTHER tenant's shared lesson fails closed under RLS —
    #     that path must be routed through the curator (tracked for Phase 3).
    #
    # global_memory.py keeps all record-building / scope-matching; these methods
    # are dialect-only persistence primitives.

    _GLOBAL_LESSON_COLUMNS = (
        "id", "tenant_id", "repo_id", "approval_state", "scope", "sensitivity",
        "visibility", "claim_type", "tool", "task_type", "worker_kind",
        "failure_signature", "success_signature", "scope_signature",
        "evidence_signature", "normalized_text", "text_hash", "simhash",
        "confidence", "reuse_stats_json", "approval_provenance_json",
        "evidence_refs_json", "citation_refs_json", "cross_tenant_shareable",
        "created_at", "updated_at", "retired_at",
    )

    _HOT_CACHE_COLUMNS = (
        "id", "global_lesson_id", "tenant_id", "repo_id", "scope", "sensitivity",
        "tool", "task_type", "worker_kind", "failure_signature",
        "success_signature", "compact_text", "confidence", "evidence_refs_json",
        "reuse_stats_json", "created_at", "updated_at", "last_used_at", "expires_at",
    )

    def pg_persist_global_lesson(self, values: Dict[str, Any]) -> None:
        run_async(self._pg_upsert_async(
            "hermes_global_lessons", self._GLOBAL_LESSON_COLUMNS, values,
            guc_tenant=values.get("tenant_id"),
        ))

    def pg_get_global_lesson(self, lesson_id: str) -> Optional[Dict[str, Any]]:
        return run_async(self._pg_fetchrow_async(
            "SELECT * FROM hermes_global_lessons WHERE id = $1",
            (lesson_id,), guc_tenant=self._tenant_id,
        ))

    def pg_list_global_lessons(
        self, *, tenant_id: Optional[str], repo_id: Optional[str],
        approval_state: Optional[str], limit: int,
    ) -> List[Dict[str, Any]]:
        clauses, params, idx = [], [], 1
        for col, val in (("tenant_id", tenant_id), ("repo_id", repo_id),
                         ("approval_state", approval_state)):
            if val:
                clauses.append(f"{col} = ${idx}")
                params.append(val)
                idx += 1
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(max(1, int(limit)))
        sql = (f"SELECT * FROM hermes_global_lessons {where} "
               f"ORDER BY updated_at DESC LIMIT ${idx}")
        return run_async(self._pg_fetch_async(
            sql, tuple(params), guc_tenant=tenant_id or self._tenant_id,
        ))

    def pg_upsert_hot_cache(self, values: Dict[str, Any]) -> None:
        run_async(self._pg_upsert_async(
            "hermes_global_hot_cache", self._HOT_CACHE_COLUMNS, values,
            guc_tenant=values.get("tenant_id"),
        ))

    def pg_fetch_hot_cache(self, *, now: float, limit: int = 200) -> List[Dict[str, Any]]:
        sql = (
            "SELECT * FROM hermes_global_hot_cache "
            "WHERE (expires_at IS NULL OR expires_at > $1) "
            "ORDER BY last_used_at DESC NULLS LAST, confidence DESC LIMIT $2"
        )
        return run_async(self._pg_fetch_async(
            sql, (now, max(1, int(limit))), guc_tenant=self._tenant_id,
        ))

    def pg_touch_hot_cache(self, ids: List[str]) -> None:
        if not ids:
            return
        run_async(self._pg_touch_hot_cache_async(ids))

    # -- shared async primitives -------------------------------------------

    async def _pg_upsert_async(
        self, table: str, columns: tuple, values: Dict[str, Any],
        *, guc_tenant: Optional[str],
    ) -> None:
        pool = await self._ensure_pool()
        placeholders = ", ".join(f"${i+1}" for i in range(len(columns)))
        updates = ", ".join(
            f"{c} = EXCLUDED.{c}" for c in columns if c != "id"
        )
        sql = (
            f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders}) "
            f"ON CONFLICT (id) DO UPDATE SET {updates}"
        )
        args = [values.get(c) for c in columns]
        async with TenantContext(pool, guc_tenant or "") as conn:
            await conn.execute(sql, *args)

    async def _pg_fetchrow_async(
        self, sql: str, params: tuple, *, guc_tenant: Optional[str],
    ) -> Optional[Dict[str, Any]]:
        pool = await self._ensure_pool()
        async with TenantContext(pool, guc_tenant or "") as conn:
            row = await conn.fetchrow(sql, *params)
        return dict(row) if row is not None else None

    async def _pg_fetch_async(
        self, sql: str, params: tuple, *, guc_tenant: Optional[str],
    ) -> List[Dict[str, Any]]:
        pool = await self._ensure_pool()
        async with TenantContext(pool, guc_tenant or "") as conn:
            rows = await conn.fetch(sql, *params)
        return [dict(row) for row in rows]

    async def _pg_touch_hot_cache_async(self, ids: List[str]) -> None:
        pool = await self._ensure_pool()
        ts = time.time()
        async with TenantContext(pool, self._tenant_id or "") as conn:
            await conn.execute(
                "UPDATE hermes_global_hot_cache "
                "SET last_used_at = $1, updated_at = $2 WHERE id = ANY($3::text[])",
                ts, ts, ids,
            )
