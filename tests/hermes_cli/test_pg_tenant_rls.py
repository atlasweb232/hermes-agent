"""Phase 2: Postgres RLS tenant isolation tests.

Tests are organised in two tiers:
  1. Unit tests (no DB needed) — verify the module imports, class interface, and
     TenantContext GUC-injection logic via mock asyncpg objects.
  2. Integration tests (require HERMES_PG_TEST_DSN env var) — prove RLS isolation:
       - Tenant A cannot read tenant B rows (even by supplying the correct id).
       - Unset GUC → 0 rows returned (fail-closed).
       - hermes_global_reader bypass lets the curator sidecar see all rows.

Run integration tests:
    HERMES_PG_TEST_DSN="postgres://hermes_app:pass@localhost/hermestest" \\
    pytest tests/hermes_cli/test_pg_tenant_rls.py -v
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── Tier 1 helpers ─────────────────────────────────────────────────────────

POSTGRES_DSN = os.getenv("HERMES_PG_TEST_DSN", "")
requires_pg = pytest.mark.skipif(
    not POSTGRES_DSN,
    reason="Set HERMES_PG_TEST_DSN to run Postgres RLS integration tests",
)


# ── Tier 1: import / interface ──────────────────────────────────────────────

def test_pg_tenant_store_importable():
    from hermes_cli.pg_tenant_store import (
        PostgresTenantStore,
        PostgresFTSIndex,
        PostgresMemoryAdapter,
        TenantContext,
        run_async,
    )
    assert callable(run_async)


def test_postgres_tenant_store_protocol_methods():
    """PostgresTenantStore exposes the StateStoreAdapter protocol interface."""
    from hermes_cli.pg_tenant_store import PostgresTenantStore

    # Can't connect without asyncpg + real DB, but we can instantiate
    # and inspect if asyncpg is available.
    try:
        store = PostgresTenantStore("postgresql://fake/fake")
        assert hasattr(store, "upsert")
        assert hasattr(store, "get")
        assert hasattr(store, "health")
        assert hasattr(store, "for_tenant")
    except ImportError:
        pytest.skip("asyncpg not installed")


def test_postgres_fts_index_protocol_methods():
    """PostgresFTSIndex exposes the SearchIndexAdapter protocol interface."""
    from hermes_cli.pg_tenant_store import PostgresFTSIndex

    try:
        idx = PostgresFTSIndex("postgresql://fake/fake")
        assert hasattr(idx, "upsert")
        assert hasattr(idx, "search")
        assert hasattr(idx, "for_tenant")
    except ImportError:
        pytest.skip("asyncpg not installed")


def test_postgres_memory_adapter_protocol_methods():
    """PostgresMemoryAdapter mirrors SessionDB tenant memory API."""
    from hermes_cli.pg_tenant_store import PostgresMemoryAdapter

    try:
        adapter = PostgresMemoryAdapter("postgresql://fake/fake")
        expected_methods = [
            "upsert_meta_candidate",
            "list_meta_candidates",
            "get_meta_candidate",
            "update_meta_candidate_status",
            "upsert_memory_packet",
            "list_memory_packets",
            "get_memory_packet",
            "upsert_memory_record",
            "list_memory_records",
            "add_memory_evidence",
            "for_tenant",
        ]
        for method in expected_methods:
            assert hasattr(adapter, method), f"missing method: {method}"
    except ImportError:
        pytest.skip("asyncpg not installed")


def test_for_tenant_binds_tenant_id():
    """for_tenant() returns a new store with the tenant_id bound."""
    from hermes_cli.pg_tenant_store import PostgresTenantStore, _PoolState

    try:
        store = PostgresTenantStore("postgresql://fake/fake")
        bounded = store.for_tenant("tenant-abc")
        assert bounded._tenant_id == "tenant-abc"
        # Pool state is shared
        assert bounded._pool_state is store._pool_state
        # Original store is unchanged
        assert store._tenant_id is None
    except ImportError:
        pytest.skip("asyncpg not installed")


# ── Tier 1: TenantContext GUC injection (mock asyncpg) ─────────────────────

def _make_mock_pool_and_conn():
    """Return (pool, conn, txn) mocks matching real asyncpg's sync/async API.

    asyncpg's conn.transaction() is a sync call returning a Transaction object;
    pool.acquire() is async.  Using AsyncMock for transaction() causes it to
    return a coroutine instead of a Transaction, breaking TenantContext.
    """
    executed_sqls: list[str] = []

    async def fake_execute(sql, *args, **kwargs):
        executed_sqls.append(sql.strip())

    mock_txn = MagicMock()
    mock_txn.start = AsyncMock()
    mock_txn.commit = AsyncMock()
    mock_txn.rollback = AsyncMock()

    mock_conn = AsyncMock()
    mock_conn.execute.side_effect = fake_execute
    # transaction() is sync in real asyncpg — use MagicMock not AsyncMock
    mock_conn.transaction = MagicMock(return_value=mock_txn)

    mock_pool = AsyncMock()
    mock_pool.acquire.return_value = mock_conn
    mock_pool.release = AsyncMock()

    return mock_pool, mock_conn, mock_txn, executed_sqls


def test_tenant_context_sets_guc_on_enter():
    """TenantContext emits set_config('hermes.tenant_id', …, TRUE) on __aenter__."""
    from hermes_cli.pg_tenant_store import TenantContext

    try:
        import asyncpg  # noqa: F401
    except ImportError:
        pytest.skip("asyncpg not installed")

    mock_pool, _, _, executed_sqls = _make_mock_pool_and_conn()

    async def _run():
        async with TenantContext(mock_pool, "tenant-xyz"):
            pass

    asyncio.run(_run())

    guc_calls = [s for s in executed_sqls if "set_config" in s and "hermes.tenant_id" in s]
    assert guc_calls, f"set_config not emitted; executed: {executed_sqls}"


def test_tenant_context_rolls_back_on_exception():
    """TenantContext calls rollback when an exception occurs inside the block."""
    from hermes_cli.pg_tenant_store import TenantContext

    try:
        import asyncpg  # noqa: F401
    except ImportError:
        pytest.skip("asyncpg not installed")

    mock_pool, _, mock_txn, _ = _make_mock_pool_and_conn()

    async def _run():
        with pytest.raises(ValueError, match="deliberate"):
            async with TenantContext(mock_pool, "tenant-xyz"):
                raise ValueError("deliberate")

    asyncio.run(_run())

    mock_txn.rollback.assert_awaited_once()
    mock_txn.commit.assert_not_awaited()


# ── Tier 1: SessionDB integration ──────────────────────────────────────────

def test_session_db_configure_postgres_backend(tmp_path):
    """SessionDB.configure_postgres_backend() stores the adapter."""
    from hermes_state import SessionDB

    db = SessionDB(tmp_path / "state.db")
    dummy_adapter = object()
    db.configure_postgres_backend(dummy_adapter)
    assert db._pg_memory is dummy_adapter
    db.close()


def test_session_db_delegates_to_pg_when_configured(tmp_path):
    """When _pg_memory is set, upsert_meta_candidate delegates to it."""
    from hermes_state import SessionDB

    db = SessionDB(tmp_path / "state.db")

    calls: list[dict] = []

    class _FakeAdapter:
        def upsert_meta_candidate(self, **kwargs) -> str:
            calls.append(kwargs)
            return kwargs["candidate_id"]

    db.configure_postgres_backend(_FakeAdapter())
    result = db.upsert_meta_candidate(
        candidate_id="cand-001",
        kind="test_kind",
        claim="test claim",
        tenant_id="tenant-A",
    )

    assert result == "cand-001"
    assert len(calls) == 1
    assert calls[0]["tenant_id"] == "tenant-A"
    db.close()


def test_global_memory_persist_lesson_routes_through_pg(tmp_path):
    """persist_global_lesson must delegate to _pg_memory, NOT SQLite, when configured.

    This is the security-critical path: cross-tenant global lessons are the
    training-data supply-chain surface, so they MUST flow through the RLS adapter.
    """
    from hermes_state import SessionDB
    from hermes_cli import global_memory

    db = SessionDB(tmp_path / "state.db")

    persisted: list[dict] = []

    class _FakeAdapter:
        def pg_persist_global_lesson(self, values: dict) -> None:
            persisted.append(values)

    db.configure_postgres_backend(_FakeAdapter())

    lesson = {
        "id": "glesson-001",
        "tenant_id": "tenant-A",
        "approval_state": "approved",
        "scope": "global",
        "sensitivity": "internal",
        "visibility": "global",
        "claim_type": "lesson",
        "normalized_text": "prefer X over Y",
        "cross_tenant_shareable": True,
    }
    record = global_memory.persist_global_lesson(db, lesson)

    assert record.id == "glesson-001"
    assert len(persisted) == 1, "persist_global_lesson did NOT route through the PG adapter"
    assert persisted[0]["tenant_id"] == "tenant-A"
    assert persisted[0]["cross_tenant_shareable"] == 1  # bool→int for the column

    # And the SQLite global-lessons table must remain empty (no bypass write).
    with db._lock:
        tables = {
            r[0] for r in db._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    assert "hermes_global_lessons" not in tables, (
        "SQLite global-lessons schema was created — persist bypassed the adapter"
    )
    db.close()


def test_global_memory_get_and_list_route_through_pg(tmp_path):
    """get_global_lesson and list_global_lessons delegate to the adapter."""
    from hermes_state import SessionDB
    from hermes_cli import global_memory

    db = SessionDB(tmp_path / "state.db")

    class _FakeAdapter:
        def pg_get_global_lesson(self, lesson_id: str):
            return {
                "id": lesson_id, "tenant_id": "tenant-A", "repo_id": None,
                "approval_state": "approved", "scope": "global",
                "sensitivity": "internal", "visibility": "global",
                "claim_type": "lesson", "normalized_text": "x", "text_hash": "h",
                "simhash": "0", "confidence": 0.5, "cross_tenant_shareable": 1,
                "created_at": 1.0, "updated_at": 1.0,
            }

        def pg_list_global_lessons(self, **kwargs):
            return [self.pg_get_global_lesson("glesson-xyz")]

    db.configure_postgres_backend(_FakeAdapter())

    got = global_memory.get_global_lesson(db, "glesson-xyz")
    assert got is not None and got["id"] == "glesson-xyz"

    listed = global_memory.list_global_lessons(db, tenant_id="tenant-A")
    assert len(listed) == 1 and listed[0]["id"] == "glesson-xyz"
    db.close()


# ── Tier 2: Full RLS integration (requires real Postgres) ──────────────────

@requires_pg
def test_rls_tenant_a_cannot_read_tenant_b_rows():
    """Core RLS proof: tenant A must not see rows written by tenant B."""
    from hermes_cli.pg_tenant_store import PostgresMemoryAdapter, run_async
    import asyncpg

    async def _run():
        pool = await asyncpg.create_pool(POSTGRES_DSN, min_size=1, max_size=2)
        adapter_a = PostgresMemoryAdapter(POSTGRES_DSN)
        adapter_a._pool_state.pool = pool
        adapter_a = adapter_a.for_tenant("rls-test-tenant-A")

        adapter_b = PostgresMemoryAdapter(POSTGRES_DSN)
        adapter_b._pool_state.pool = pool
        adapter_b = adapter_b.for_tenant("rls-test-tenant-B")

        unique = str(int(time.time()))
        cand_id = f"rls-cand-{unique}"

        # Write as tenant A
        await adapter_a._upsert_meta_candidate_async(
            candidate_id=cand_id,
            kind="test",
            claim="RLS test claim",
            evidence_json=None,
            score=0.9,
            status="proposed",
            tenant_id="rls-test-tenant-A",
            repo_id=None,
        )

        # Tenant A should see it
        row_a = await adapter_a._get_meta_candidate_async(cand_id)
        assert row_a is not None, "Tenant A should see its own row"

        # Tenant B must NOT see it (RLS blocks cross-tenant reads)
        row_b = await adapter_b._get_meta_candidate_async(cand_id)
        assert row_b is None, f"RLS FAILURE: Tenant B can read Tenant A's row: {row_b}"

        # Cleanup
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "SELECT set_config('hermes.tenant_id', $1, TRUE)",
                    "rls-test-tenant-A",
                )
                await conn.execute(
                    "DELETE FROM hermes_meta_candidates WHERE id = $1", cand_id
                )

        await pool.close()

    run_async(_run())


@requires_pg
def test_rls_unset_guc_returns_no_rows():
    """Fail-closed: querying without setting hermes.tenant_id returns zero rows."""
    from hermes_cli.pg_tenant_store import run_async
    import asyncpg

    async def _run():
        pool = await asyncpg.create_pool(POSTGRES_DSN, min_size=1, max_size=2)

        async with pool.acquire() as conn:
            # No GUC set — RLS should block everything
            async with conn.transaction():
                rows = await conn.fetch(
                    "SELECT * FROM hermes_meta_candidates LIMIT 10"
                )
        assert rows == [], (
            f"Fail-closed FAILURE: got {len(rows)} rows without hermes.tenant_id set"
        )

        await pool.close()

    run_async(_run())


@requires_pg
def test_rls_global_reader_bypasses_tenant_filter():
    """hermes_global_reader role can read all tenants' rows."""
    from hermes_cli.pg_tenant_store import run_async
    import asyncpg

    # This test requires a separate DSN for the global_reader role.
    reader_dsn = os.getenv("HERMES_PG_READER_DSN", "")
    if not reader_dsn:
        pytest.skip("Set HERMES_PG_READER_DSN (hermes_global_reader credentials) to run this test")

    async def _run():
        # Write a row as a regular tenant via the app DSN
        app_pool = await asyncpg.create_pool(POSTGRES_DSN, min_size=1, max_size=2)
        unique = str(int(time.time()))
        cand_id = f"rls-reader-{unique}"
        async with app_pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "SELECT set_config('hermes.tenant_id', $1, TRUE)", "rls-reader-tenant"
                )
                await conn.execute(
                    """
                    INSERT INTO hermes_meta_candidates
                        (id, tenant_id, kind, claim, status, created_at, updated_at)
                    VALUES ($1,$2,$3,$4,$5,$6,$7)
                    """,
                    cand_id, "rls-reader-tenant", "test", "reader bypass test",
                    "proposed", time.time(), time.time(),
                )

        # Now read as global_reader — should see the row without setting tenant GUC
        reader_pool = await asyncpg.create_pool(reader_dsn, min_size=1, max_size=2)
        async with reader_pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    "SELECT id FROM hermes_meta_candidates WHERE id = $1", cand_id
                )
        assert row is not None, "hermes_global_reader should bypass tenant RLS filter"

        # Cleanup
        async with app_pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "SELECT set_config('hermes.tenant_id', $1, TRUE)", "rls-reader-tenant"
                )
                await conn.execute(
                    "DELETE FROM hermes_meta_candidates WHERE id = $1", cand_id
                )

        await app_pool.close()
        await reader_pool.close()

    run_async(_run())
