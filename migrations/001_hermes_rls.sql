-- Phase 2: Postgres tenant isolation via Row-Level Security
-- Idempotent — safe to re-run.
--
-- Roles (created with safe DO blocks so re-runs don't fail):
--   hermes_app          Per-request application role (LOGIN, fully bound by RLS).
--                       MUST NOT be a member of hermes_global_reader — otherwise
--                       pg_has_role() would return true for every query and the
--                       per-tenant policies' global-reader OR-branch would silently
--                       disable all tenant isolation.
--   hermes_global_reader  Privilege bundle (NOLOGIN) granting cross-tenant read of
--                       the global lesson/hot-cache pool.  Held ONLY by the curator
--                       login, never by the per-request app role.
--   hermes_curator      Global-curation sidecar login (curator / memory_dreaming).
--                       Member of hermes_global_reader; operates the cross-tenant
--                       global pool.  This is the only identity that bypasses
--                       per-tenant RLS.
--
-- GUC binding:  hermes.tenant_id
--   Every query on a tenant-scoped table MUST execute inside a transaction where
--   the caller has already run:
--       SELECT set_config('hermes.tenant_id', '<tenant>', TRUE);
--   (TRUE = transaction-local; resets automatically on COMMIT/ROLLBACK.)
--   Fail-closed: unset GUC returns '' which matches no tenant_id, blocking all rows.
--
-- Applying: psql $DATABASE_URL -f migrations/001_hermes_rls.sql

-- ── Roles ──────────────────────────────────────────────────────────────────

DO $$ BEGIN
    CREATE ROLE hermes_app WITH LOGIN;
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE ROLE hermes_global_reader NOLOGIN;
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE ROLE hermes_curator WITH LOGIN;
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- Only the curator sidecar login holds the cross-tenant bypass.
-- hermes_app is DELIBERATELY NOT granted hermes_global_reader (see role note).
GRANT hermes_global_reader TO hermes_curator;

-- ── Helper: policy predicate fragments ────────────────────────────────────
-- Reused across tables:
--   tenant_match  USING clause for tenant-scoped tables
--   global_reader_bypass  allows hermes_global_reader to bypass per-tenant filter

-- ── memory_wiki_state  (MemoryWikiBackendBundle state + lexical backends) ──

CREATE TABLE IF NOT EXISTS memory_wiki_state (
    id            TEXT             PRIMARY KEY,
    tenant_id     TEXT,
    payload_json  TEXT             NOT NULL,
    updated_at    DOUBLE PRECISION NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_memory_wiki_state_tenant
    ON memory_wiki_state(tenant_id);

-- GIN index for full-text search via to_tsvector (used by PostgresFTSIndex)
CREATE INDEX IF NOT EXISTS idx_memory_wiki_state_fts
    ON memory_wiki_state USING GIN(to_tsvector('simple', payload_json));

ALTER TABLE memory_wiki_state ENABLE ROW LEVEL SECURITY;
ALTER TABLE memory_wiki_state FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS memory_wiki_state_rls ON memory_wiki_state;
CREATE POLICY memory_wiki_state_rls ON memory_wiki_state
    USING (
        -- Global (null tenant_id) rows are readable by all authenticated users
        tenant_id IS NULL
        OR tenant_id = current_setting('hermes.tenant_id', TRUE)
        OR pg_has_role(current_user, 'hermes_global_reader', 'member')
    )
    WITH CHECK (
        -- Writes must be tenant-scoped or performed by global_reader (curator)
        tenant_id = current_setting('hermes.tenant_id', TRUE)
        OR pg_has_role(current_user, 'hermes_global_reader', 'member')
    );

GRANT SELECT, INSERT, UPDATE, DELETE ON memory_wiki_state TO hermes_app;

-- ── hermes_meta_candidates  (per-tenant learning candidates) ───────────────

CREATE TABLE IF NOT EXISTS hermes_meta_candidates (
    id            TEXT             PRIMARY KEY,
    tenant_id     TEXT,
    repo_id       TEXT,
    kind          TEXT             NOT NULL,
    claim         TEXT             NOT NULL,
    evidence_json TEXT,
    score         DOUBLE PRECISION,
    status        TEXT             NOT NULL,
    created_at    DOUBLE PRECISION NOT NULL,
    updated_at    DOUBLE PRECISION NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_hermes_meta_candidates_scope
    ON hermes_meta_candidates(tenant_id, repo_id, kind, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_hermes_meta_candidates_status
    ON hermes_meta_candidates(status, created_at DESC);

ALTER TABLE hermes_meta_candidates ENABLE ROW LEVEL SECURITY;
ALTER TABLE hermes_meta_candidates FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS hermes_meta_candidates_rls ON hermes_meta_candidates;
CREATE POLICY hermes_meta_candidates_rls ON hermes_meta_candidates
    USING (
        tenant_id = current_setting('hermes.tenant_id', TRUE)
        OR pg_has_role(current_user, 'hermes_global_reader', 'member')
    )
    WITH CHECK (
        tenant_id = current_setting('hermes.tenant_id', TRUE)
        OR pg_has_role(current_user, 'hermes_global_reader', 'member')
    );

GRANT SELECT, INSERT, UPDATE, DELETE ON hermes_meta_candidates TO hermes_app;

-- ── hermes_memory_packets  (per-tenant memory retrieval packets) ───────────

CREATE TABLE IF NOT EXISTS hermes_memory_packets (
    id                    TEXT             PRIMARY KEY,
    tenant_id             TEXT,
    repo_id               TEXT,
    job_id                TEXT,
    task_id               TEXT,
    query                 TEXT             NOT NULL,
    scopes                TEXT,
    claims_json           TEXT,
    evidence_json         TEXT,
    contradictions_json   TEXT,
    freshness_json        TEXT,
    status                TEXT             NOT NULL,
    confidence            DOUBLE PRECISION,
    source                TEXT,
    expires_at            DOUBLE PRECISION,
    created_at            DOUBLE PRECISION NOT NULL,
    updated_at            DOUBLE PRECISION NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_hermes_memory_packets_scope
    ON hermes_memory_packets(tenant_id, repo_id, job_id, task_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_hermes_memory_packets_status
    ON hermes_memory_packets(status, created_at DESC);

ALTER TABLE hermes_memory_packets ENABLE ROW LEVEL SECURITY;
ALTER TABLE hermes_memory_packets FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS hermes_memory_packets_rls ON hermes_memory_packets;
CREATE POLICY hermes_memory_packets_rls ON hermes_memory_packets
    USING (
        tenant_id = current_setting('hermes.tenant_id', TRUE)
        OR pg_has_role(current_user, 'hermes_global_reader', 'member')
    )
    WITH CHECK (
        tenant_id = current_setting('hermes.tenant_id', TRUE)
        OR pg_has_role(current_user, 'hermes_global_reader', 'member')
    );

GRANT SELECT, INSERT, UPDATE, DELETE ON hermes_memory_packets TO hermes_app;

-- ── hermes_memory_records  (per-tenant memory records) ────────────────────

CREATE TABLE IF NOT EXISTS hermes_memory_records (
    id              TEXT             PRIMARY KEY,
    tenant_id       TEXT,
    repo_id         TEXT,
    job_id          TEXT,
    task_id         TEXT,
    kind            TEXT             NOT NULL,
    title           TEXT,
    body            TEXT,
    payload_json    TEXT,
    packet_id       TEXT,
    evidence_uri    TEXT,
    evidence_sha256 TEXT,
    status          TEXT             NOT NULL,
    score           DOUBLE PRECISION,
    created_at      DOUBLE PRECISION NOT NULL,
    updated_at      DOUBLE PRECISION NOT NULL,
    FOREIGN KEY (packet_id) REFERENCES hermes_memory_packets(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_hermes_memory_records_scope
    ON hermes_memory_records(tenant_id, repo_id, kind, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_hermes_memory_records_status
    ON hermes_memory_records(status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_hermes_memory_records_packet
    ON hermes_memory_records(packet_id);

ALTER TABLE hermes_memory_records ENABLE ROW LEVEL SECURITY;
ALTER TABLE hermes_memory_records FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS hermes_memory_records_rls ON hermes_memory_records;
CREATE POLICY hermes_memory_records_rls ON hermes_memory_records
    USING (
        tenant_id = current_setting('hermes.tenant_id', TRUE)
        OR pg_has_role(current_user, 'hermes_global_reader', 'member')
    )
    WITH CHECK (
        tenant_id = current_setting('hermes.tenant_id', TRUE)
        OR pg_has_role(current_user, 'hermes_global_reader', 'member')
    );

GRANT SELECT, INSERT, UPDATE, DELETE ON hermes_memory_records TO hermes_app;

-- ── hermes_memory_evidence  (evidence fragments linked to records/packets) ─
-- tenant_id column added for defense-in-depth (the FK chain already protects
-- against orphan access, but explicit RLS prevents direct table scans).

CREATE TABLE IF NOT EXISTS hermes_memory_evidence (
    id         BIGINT           GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id  TEXT,
    record_id  TEXT,
    packet_id  TEXT,
    uri        TEXT             NOT NULL,
    sha256     TEXT,
    mime_type  TEXT,
    excerpt    TEXT,
    created_at DOUBLE PRECISION NOT NULL,
    FOREIGN KEY (record_id) REFERENCES hermes_memory_records(id) ON DELETE CASCADE,
    FOREIGN KEY (packet_id) REFERENCES hermes_memory_packets(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_hermes_memory_evidence_record
    ON hermes_memory_evidence(record_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_hermes_memory_evidence_packet
    ON hermes_memory_evidence(packet_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_hermes_memory_evidence_tenant
    ON hermes_memory_evidence(tenant_id, created_at DESC);

ALTER TABLE hermes_memory_evidence ENABLE ROW LEVEL SECURITY;
ALTER TABLE hermes_memory_evidence FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS hermes_memory_evidence_rls ON hermes_memory_evidence;
CREATE POLICY hermes_memory_evidence_rls ON hermes_memory_evidence
    USING (
        tenant_id = current_setting('hermes.tenant_id', TRUE)
        OR pg_has_role(current_user, 'hermes_global_reader', 'member')
    )
    WITH CHECK (
        tenant_id = current_setting('hermes.tenant_id', TRUE)
        OR pg_has_role(current_user, 'hermes_global_reader', 'member')
    );

GRANT SELECT, INSERT, UPDATE, DELETE ON hermes_memory_evidence TO hermes_app;

-- ── hermes_learning_runs  (per-tenant learning run records) ───────────────

CREATE TABLE IF NOT EXISTS hermes_learning_runs (
    id          TEXT             PRIMARY KEY,
    tenant_id   TEXT,
    repo_id     TEXT,
    packet_id   TEXT,
    status      TEXT             NOT NULL,
    metrics_json TEXT,
    notes       TEXT,
    created_at  DOUBLE PRECISION NOT NULL,
    updated_at  DOUBLE PRECISION NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_hermes_learning_runs_scope
    ON hermes_learning_runs(tenant_id, repo_id, created_at DESC);

ALTER TABLE hermes_learning_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE hermes_learning_runs FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS hermes_learning_runs_rls ON hermes_learning_runs;
CREATE POLICY hermes_learning_runs_rls ON hermes_learning_runs
    USING (
        tenant_id = current_setting('hermes.tenant_id', TRUE)
        OR pg_has_role(current_user, 'hermes_global_reader', 'member')
    )
    WITH CHECK (
        tenant_id = current_setting('hermes.tenant_id', TRUE)
        OR pg_has_role(current_user, 'hermes_global_reader', 'member')
    );

GRANT SELECT, INSERT, UPDATE, DELETE ON hermes_learning_runs TO hermes_app;

-- ── hermes_global_lessons  (cross-tenant approved global lessons) ──────────
-- Policy is more nuanced than per-tenant tables:
--   - Tenant's own lessons (any approval_state, matched by tenant_id).
--   - Globally approved cross-tenant lessons (scope=global, approved, shareable).
--   - hermes_global_reader bypass (curator sidecar).
-- Writes are restricted to the owning tenant or global_reader.

CREATE TABLE IF NOT EXISTS hermes_global_lessons (
    id                        TEXT             PRIMARY KEY,
    tenant_id                 TEXT,
    repo_id                   TEXT,
    approval_state            TEXT             NOT NULL,
    scope                     TEXT             NOT NULL,
    sensitivity               TEXT             NOT NULL,
    visibility                TEXT             NOT NULL,
    claim_type                TEXT             NOT NULL,
    tool                      TEXT,
    task_type                 TEXT,
    worker_kind               TEXT,
    failure_signature         TEXT,
    success_signature         TEXT,
    scope_signature           TEXT,
    evidence_signature        TEXT,
    normalized_text           TEXT             NOT NULL,
    text_hash                 TEXT             NOT NULL,
    simhash                   TEXT             NOT NULL,
    confidence                DOUBLE PRECISION NOT NULL DEFAULT 0,
    reuse_stats_json          TEXT,
    approval_provenance_json  TEXT,
    evidence_refs_json        TEXT,
    citation_refs_json        TEXT,
    cross_tenant_shareable    INTEGER          NOT NULL DEFAULT 0,
    created_at                DOUBLE PRECISION NOT NULL,
    updated_at                DOUBLE PRECISION NOT NULL,
    retired_at                DOUBLE PRECISION
);

CREATE INDEX IF NOT EXISTS idx_hermes_global_lessons_exact
    ON hermes_global_lessons(approval_state, sensitivity, failure_signature, success_signature, text_hash);
CREATE INDEX IF NOT EXISTS idx_hermes_global_lessons_scope
    ON hermes_global_lessons(tenant_id, repo_id, scope, approval_state, retired_at);
CREATE INDEX IF NOT EXISTS idx_hermes_global_lessons_simhash
    ON hermes_global_lessons(approval_state, simhash, confidence);

ALTER TABLE hermes_global_lessons ENABLE ROW LEVEL SECURITY;
ALTER TABLE hermes_global_lessons FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS hermes_global_lessons_rls ON hermes_global_lessons;
CREATE POLICY hermes_global_lessons_rls ON hermes_global_lessons
    USING (
        -- Own tenant lessons
        tenant_id = current_setting('hermes.tenant_id', TRUE)
        -- Cross-tenant globally approved lessons (read-only path)
        OR (
            scope = 'global'
            AND approval_state = 'approved'
            AND cross_tenant_shareable = 1
            AND retired_at IS NULL
        )
        -- Curator sidecar bypass
        OR pg_has_role(current_user, 'hermes_global_reader', 'member')
    )
    WITH CHECK (
        -- Only own tenant or curator can write
        tenant_id = current_setting('hermes.tenant_id', TRUE)
        OR pg_has_role(current_user, 'hermes_global_reader', 'member')
    );

GRANT SELECT, INSERT, UPDATE, DELETE ON hermes_global_lessons TO hermes_app;

-- ── hermes_global_hot_cache  (materialized hot cache of global lessons) ────

CREATE TABLE IF NOT EXISTS hermes_global_hot_cache (
    id                 TEXT             PRIMARY KEY,
    global_lesson_id   TEXT             NOT NULL,
    tenant_id          TEXT,
    repo_id            TEXT,
    scope              TEXT             NOT NULL,
    sensitivity        TEXT             NOT NULL,
    tool               TEXT,
    task_type          TEXT,
    worker_kind        TEXT,
    failure_signature  TEXT,
    success_signature  TEXT,
    compact_text       TEXT             NOT NULL,
    confidence         DOUBLE PRECISION NOT NULL DEFAULT 0,
    evidence_refs_json TEXT,
    reuse_stats_json   TEXT,
    created_at         DOUBLE PRECISION NOT NULL,
    updated_at         DOUBLE PRECISION NOT NULL,
    last_used_at       DOUBLE PRECISION,
    expires_at         DOUBLE PRECISION
);

CREATE INDEX IF NOT EXISTS idx_hermes_global_hot_cache_exact
    ON hermes_global_hot_cache(tenant_id, repo_id, failure_signature, success_signature, expires_at);
CREATE INDEX IF NOT EXISTS idx_hermes_global_hot_cache_scope
    ON hermes_global_hot_cache(tenant_id, repo_id, scope, sensitivity, updated_at DESC);

ALTER TABLE hermes_global_hot_cache ENABLE ROW LEVEL SECURITY;
ALTER TABLE hermes_global_hot_cache FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS hermes_global_hot_cache_rls ON hermes_global_hot_cache;
CREATE POLICY hermes_global_hot_cache_rls ON hermes_global_hot_cache
    USING (
        tenant_id = current_setting('hermes.tenant_id', TRUE)
        OR pg_has_role(current_user, 'hermes_global_reader', 'member')
    )
    WITH CHECK (
        tenant_id = current_setting('hermes.tenant_id', TRUE)
        OR pg_has_role(current_user, 'hermes_global_reader', 'member')
    );

GRANT SELECT, INSERT, UPDATE, DELETE ON hermes_global_hot_cache TO hermes_app;

-- ── state_meta  (TenantPlatformStore KV pairs, keyed with tenant prefix) ───
-- The key already embeds tenant_id via the "tenant_platform:<tid>:..." prefix.
-- RLS here uses a computed expression on the key column as defense-in-depth.

CREATE TABLE IF NOT EXISTS state_meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

-- Note: state_meta uses key-prefix scoping instead of a dedicated tenant_id
-- column (the key IS the namespace).  RLS enforces that each user can only see
-- keys that start with "tenant_platform:<their tenant_id>:" or are global keys
-- (no tenant_platform: prefix), or the user holds hermes_global_reader.
ALTER TABLE state_meta ENABLE ROW LEVEL SECURITY;
ALTER TABLE state_meta FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS state_meta_rls ON state_meta;
CREATE POLICY state_meta_rls ON state_meta
    USING (
        key NOT LIKE 'tenant_platform:%'
        OR key LIKE 'tenant_platform:' || current_setting('hermes.tenant_id', TRUE) || ':%'
        OR pg_has_role(current_user, 'hermes_global_reader', 'member')
    )
    WITH CHECK (
        key NOT LIKE 'tenant_platform:%'
        OR key LIKE 'tenant_platform:' || current_setting('hermes.tenant_id', TRUE) || ':%'
        OR pg_has_role(current_user, 'hermes_global_reader', 'member')
    );

GRANT SELECT, INSERT, UPDATE, DELETE ON state_meta TO hermes_app;

-- ── Curator (hermes_global_reader) grants ──────────────────────────────────
-- The curator sidecar operates the cross-tenant global pool (full DML) and
-- performs cross-tenant SELECT on per-tenant tables for global assessment.
-- It does NOT get write access to per-tenant tables — promotion writes land in
-- the global pool, not back into another tenant's private rows.
GRANT SELECT, INSERT, UPDATE, DELETE ON hermes_global_lessons   TO hermes_global_reader;
GRANT SELECT, INSERT, UPDATE, DELETE ON hermes_global_hot_cache TO hermes_global_reader;
GRANT SELECT ON hermes_meta_candidates  TO hermes_global_reader;
GRANT SELECT ON hermes_memory_records   TO hermes_global_reader;
GRANT SELECT ON hermes_memory_packets   TO hermes_global_reader;
GRANT SELECT ON hermes_memory_evidence  TO hermes_global_reader;
GRANT SELECT ON memory_wiki_state       TO hermes_global_reader;
