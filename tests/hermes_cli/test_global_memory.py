import json
import sys
from unittest.mock import patch

import pytest

from hermes_cli.global_memory import (
    DiscussionMemoryRecord,
    GlobalPreCurationEvent,
    approval_invocation_allowed,
    build_global_topic,
    build_idempotency_key,
    classify_dedupe,
    dreaming_sidecar_definitions,
    discussion_sidecar_definitions,
    discussion_storage_config,
    fanout_canonical_claim_to_indexes,
    fanout_discussion_record_to_indexes,
    get_global_memory_bus,
    normalize_proposal,
    hydrate_task_memory_from_global,
    materialize_global_lesson_to_hot_cache,
    persist_global_lesson,
    publish_global_proposal,
    record_global_lesson_reuse_metric,
    retrieve_global_lessons_for_event,
    retrieve_global_hot_cache_for_event,
    run_persisted_global_precuration,
    should_curate_locally,
    simple_simhash,
    text_hash,
    update_global_lesson_reuse_feedback,
    upsert_discussion_memory_record,
    validate_proposal,
)
from hermes_cli.learning_bus import list_learning_events
from hermes_cli.memory_graph import expand_graph
from hermes_cli.memory_index import lexical_search
from hermes_state import SessionDB

from hermes_cli.global_memory_sidecars import (
    run_global_indexer_sidecar,
    run_local_sync_sidecar,
)


def _db(tmp_path):
    return SessionDB(db_path=tmp_path / "state.db")


def _proposal(**overrides):
    data = {
        "id": "proposal_1",
        "source_instance_id": "vm-1",
        "source_session_id": "sess-1",
        "source_event_id": "evt-1",
        "tenant_id": "atlas",
        "user_id_hash": "userhash",
        "domain": "architecture",
        "scope": "global",
        "visibility": "global_candidate",
        "sensitivity": "internal",
        "claim_type": "principle",
        "language": "en",
        "title": "Global memory uses central canonical store",
        "normalized_text": "Global memory should use central canonical storage and local cache.",
        "graph_keys": ["domain:memory-architecture"],
        "entities": ["Hermes", "Memory Wiki"],
        "evidence_refs": ["s3://bucket/evidence/1.json"],
        "citation_refs": ["url_hash:abc"],
        "created_at": "2026-05-17T00:00:00Z",
        "confidence": 0.82,
        "approval_state": "proposed",
    }
    data.update(overrides)
    return data


def _sidecar_config(*, index_enabled=True, sync_enabled=True, ttl_seconds=60):
    return {
        "supervisor": {
            "global_memory_wiki": {
                "sidecars": {
                    "global_indexer": {
                        "enabled": index_enabled,
                        "mode": "local",
                        "max_batch": 100,
                    },
                    "local_sync": {
                        "enabled": sync_enabled,
                        "mode": "local",
                        "ttl_seconds": ttl_seconds,
                        "max_batch": 100,
                    },
                }
            }
        }
    }


def test_global_memory_config_defaults_exist(_isolate_hermes_home):
    from hermes_cli.config import load_config

    cfg = load_config()
    wiki = cfg["supervisor"]["global_memory_wiki"]
    bus = cfg["supervisor"]["global_memory_bus"]
    injection = cfg["supervisor"]["runtime_memory_injection"]

    assert wiki["object_store"]["backend"] == "local"
    assert wiki["state_store"]["backend"] == "sqlite"
    assert wiki["vector_index"]["backend"] == "disabled"
    assert wiki["require_global_approval"] is True
    assert wiki["task_memory_profile"]["vector_graph_fallback"]["enabled"] is False
    assert wiki["task_memory_profile"]["vector_graph_fallback"]["min_exact_score"] == 1.0
    assert bus["backend"] == "sqlite"
    assert bus["topic_prefix"] == "hermes.memory"
    assert wiki["precuration"]["skip_expensive_curator_on_exact"] is True
    assert wiki["sidecars"]["global_indexer"]["enabled"] is False
    assert wiki["sidecars"]["global_indexer"]["mode"] == "local"
    assert wiki["sidecars"]["local_sync"]["enabled"] is False
    assert wiki["sidecars"]["local_sync"]["mode"] == "local"
    assert injection["enabled"] is True
    assert injection["token_budget"] == 600


def test_discussion_memory_config_and_sidecars_exist(_isolate_hermes_home):
    from hermes_cli.config import load_config

    cfg = load_config()
    storage = discussion_storage_config(cfg)
    sidecars = {item.name: item for item in discussion_sidecar_definitions(cfg)}

    assert storage["root"] == "~/.hermes/memory-wiki"
    assert storage["max_local_gb"] == 50
    assert storage["raw_retention_days"] == 30
    assert sidecars["discussion_capture"].llm_role == "discussion_capture"
    assert sidecars["claim_extractor"].llm_role == "claim_extractor"
    assert sidecars["citation_validator"].mode == "deterministic_first"
    assert sidecars["indexer"].llm_role is None
    assert sidecars["sync"].mode == "programmatic"


def test_model_roles_include_discussion_sidecars(_isolate_hermes_home):
    from hermes_cli.config import load_config
    from hermes_cli.model_roles import get_model_role, get_model_tier, role_names

    names = set(role_names())
    assert {"discussion_capture", "claim_extractor", "wiki_compiler", "dreaming", "global_dreaming", "citation_validator"} <= names
    cfg = load_config()
    role = get_model_role(cfg, "claim_extractor")
    assert role["path"] == "supervisor.sidecar_models.claim_extractor"
    assert role["tier"] == "cheap_reasoning"
    assert role["config"]["provider"] == "cerebras"

    # Backward-compatible alias: older configs/tests may still refer to
    # low_cost_reasoning, but runtime role surfaces canonicalize to
    # cheap_reasoning.
    alias = get_model_tier(cfg, "low_cost_reasoning")
    assert alias["tier"] == "cheap_reasoning"
    assert alias["provider"] == role["config"]["provider"]


def test_normalize_proposal_adds_hashes_and_simhash():
    proposal = normalize_proposal(_proposal()).to_dict()

    assert proposal["text_hash"]
    assert proposal["simhash"]
    assert proposal["normalized_text"] == "global memory should use central canonical storage and local cache."


def test_validate_proposal_rejects_secret_global_candidate():
    proposal = _proposal(sensitivity="secret", visibility="global_candidate")

    result = validate_proposal(proposal)

    assert result.valid is False
    assert "secret proposals must remain private" in result.errors


def test_idempotency_key_is_stable_for_same_source_text_and_evidence():
    first = normalize_proposal(_proposal()).to_dict()
    second = normalize_proposal(_proposal()).to_dict()

    assert build_idempotency_key(first) == build_idempotency_key(second)


def test_sqlite_global_bus_publish_is_idempotent(tmp_path):
    db = _db(tmp_path)
    try:
        config = {"supervisor": {"global_memory_bus": {"backend": "sqlite", "topic_prefix": "hermes.memory"}}}

        first = publish_global_proposal(db, config, _proposal())
        second = publish_global_proposal(db, config, _proposal(normalized_text="Global memory should use central canonical storage and local cache."))
        rows = list_learning_events(db, topic="hermes.memory.proposed")

        assert first["ok"] is True
        assert second["ok"] is True
        assert first["idempotency_key"] == second["idempotency_key"]
        assert len(rows) == 1
    finally:
        db.close()


def test_global_topic_uses_configured_prefix():
    config = {"supervisor": {"global_memory_bus": {"topic_prefix": "atlas.memory"}}}

    assert build_global_topic(config, "dedupe_requested") == "atlas.memory.dedupe.requested"


def test_kafka_bus_boundary_requires_optional_dependency(tmp_path):
    db = _db(tmp_path)
    try:
        config = {
            "supervisor": {
                "global_memory_bus": {
                    "backend": "redpanda",
                    "brokers": ["127.0.0.1:9092"],
                }
            }
        }

        with pytest.raises(RuntimeError, match="confluent-kafka"):
            get_global_memory_bus(db, config)
    finally:
        db.close()


def test_dedupe_exact_duplicate():
    proposal = _proposal(id="proposal_new")
    existing = _proposal(id="claim_existing")

    decision = classify_dedupe(proposal, [existing])

    assert decision.dedupe_class == "exact_duplicate"
    assert decision.matched_id == "claim_existing"


def test_dedupe_same_evidence_when_text_differs():
    proposal = _proposal(id="proposal_new", normalized_text="Global wiki needs dedupe before approval.")
    existing = _proposal(id="claim_existing", normalized_text="Canonical memory should deduplicate proposals first.")

    decision = classify_dedupe(proposal, [existing])

    assert decision.dedupe_class == "same_evidence"
    assert decision.matched_id == "claim_existing"


def test_dedupe_near_duplicate_uses_simhash():
    proposal = _proposal(
        id="proposal_new",
        normalized_text="Global memory wiki should use canonical storage and local hot cache.",
        evidence_refs=["s3://bucket/evidence/2.json"],
    )
    existing = normalize_proposal(
        _proposal(
            id="claim_existing",
            normalized_text="Global memory wiki should use canonical store and local hot cache.",
            evidence_refs=["s3://bucket/evidence/3.json"],
        )
    ).to_dict()
    existing["simhash"] = normalize_proposal(proposal).to_dict()["simhash"]

    decision = classify_dedupe(proposal, [existing])

    assert decision.dedupe_class == "near_duplicate"


def test_dedupe_same_topic_for_related_claims():
    proposal = _proposal(
        id="proposal_new",
        normalized_text="Global memory wiki retrieval should combine lexical vector graph ranking.",
        evidence_refs=["s3://bucket/evidence/2.json"],
        entities=["Hermes", "retrieval", "memory"],
    )
    existing = _proposal(
        id="claim_existing",
        normalized_text="Global memory wiki retrieval should use lexical vector graph scoring.",
        evidence_refs=["s3://bucket/evidence/3.json"],
        entities=["Hermes", "retrieval", "memory"],
    )

    decision = classify_dedupe(proposal, [existing])

    assert decision.dedupe_class in {"same_topic", "near_duplicate"}


def test_dedupe_conflict_for_same_topic_opposite_claim():
    proposal = _proposal(
        id="proposal_new",
        normalized_text="Global memories should be shared across tenants.",
        evidence_refs=["s3://bucket/evidence/2.json"],
        entities=["Hermes", "tenant", "memory"],
    )
    existing = _proposal(
        id="claim_existing",
        normalized_text="Global memories should not be shared across tenants.",
        evidence_refs=["s3://bucket/evidence/3.json"],
        entities=["Hermes", "tenant", "memory"],
    )

    decision = classify_dedupe(proposal, [existing])

    assert decision.dedupe_class == "conflict"


def test_dedupe_supersedes_lower_confidence_same_topic():
    proposal = _proposal(
        id="proposal_new",
        normalized_text="Global memory wiki should use object storage vector indexes and graph indexes.",
        evidence_refs=["s3://bucket/evidence/2.json"],
        confidence=0.95,
    )
    existing = _proposal(
        id="claim_existing",
        normalized_text="Global memory wiki should use object storage vector indexes and lexical indexes.",
        evidence_refs=["s3://bucket/evidence/3.json"],
        confidence=0.5,
    )

    decision = classify_dedupe(proposal, [existing])

    assert decision.dedupe_class == "supersedes"


def test_index_fanout_requires_approved_canonical_claim(tmp_path):
    db = _db(tmp_path)
    try:
        result = fanout_canonical_claim_to_indexes(db, canonical_claim=_proposal(approval_state="proposed"))

        assert result.status == "skipped"
        assert "approved" in result.errors[0]
    finally:
        db.close()


def test_index_fanout_skips_secret_claims(tmp_path):
    db = _db(tmp_path)
    try:
        result = fanout_canonical_claim_to_indexes(
            db,
            canonical_claim=_proposal(approval_state="approved", sensitivity="secret", visibility="private"),
        )

        assert result.status == "skipped"
        assert "secret" in result.errors[0]
    finally:
        db.close()


def test_index_fanout_writes_lexical_graph_and_bus_event(tmp_path):
    db = _db(tmp_path)
    try:
        config = {"supervisor": {"global_memory_bus": {"backend": "sqlite", "topic_prefix": "hermes.memory"}}}
        claim = _proposal(
            id="claim_global_1",
            approval_state="approved",
            normalized_text="Global memory wiki should fan out approved claims to lexical vector graph indexes.",
            entities=["Hermes", "indexer", "memory"],
            graph_keys=["domain:memory-architecture", "index:graph"],
            evidence_refs=["s3://bucket/evidence/indexing.json"],
            citation_refs=["url_hash:indexing"],
        )

        result = fanout_canonical_claim_to_indexes(db, canonical_claim=claim, config=config)
        lexical = lexical_search(db, query="approved claims graph indexes", statuses=["approved"])
        graph = expand_graph(db, start_id="global:claim_global_1", limit=20)
        events = list_learning_events(db, topic="hermes.memory.index.completed")

        assert result.status == "indexed"
        assert result.lexical_indexed is True
        assert result.graph_nodes >= 6
        assert result.graph_edges >= 5
        assert result.vector_payload["id"] == "global:claim_global_1"
        assert lexical[0]["memory_id"] == "global:claim_global_1"
        assert {edge["relation"] for edge in graph} >= {"APPLIES_TO_DOMAIN", "SUPPORTED_BY", "CITES"}
        assert len(events) == 1
        assert events[0].payload_json["status"] == "indexed"
    finally:
        db.close()


def test_discussion_memory_schema_round_trip_and_index_fanout(tmp_path):
    db = _db(tmp_path)
    try:
        record = DiscussionMemoryRecord(
            id="disc_1",
            tenant_id="atlas",
            record_type="architecture_discussion",
            title="Global memory wiki storage",
            summary="Global memory needs configurable storage and sidecar indexing.",
            scope="global",
            domain="architecture",
            sensitivity="internal",
            source_session_id="sess-1",
            evidence_refs=["s3://bucket/evidence/disc_1.json"],
            citation_refs=["url_hash:doc"],
            claims=["Storage locations should be configurable.", "Indexing should be sidecar driven."],
            approval_state="approved",
            producer_invocation_id="producer-1",
            judge_invocation_id="judge-1",
            operator_approved=True,
        )

        upsert_discussion_memory_record(db, record)
        result = fanout_discussion_record_to_indexes(db, record)
        lexical = lexical_search(db, query="configurable storage sidecar indexing", statuses=["approved"])
        graph = expand_graph(db, start_id="discussion:disc_1", limit=10)

        assert result.status == "indexed"
        assert result.lexical_indexed is True
        assert lexical[0]["memory_id"] == "discussion:disc_1"
        assert {edge["relation"] for edge in graph} >= {"APPLIES_TO_DOMAIN", "SUPPORTED_BY", "CITES"}
    finally:
        db.close()


def test_approval_guard_rejects_same_invocation_and_global_without_operator():
    result = approval_invocation_allowed(
        {
            "scope": "global",
            "producer_invocation_id": "same",
            "judge_invocation_id": "same",
            "operator_approved": False,
        }
    )

    assert result.valid is False
    assert "judge invocation must differ from producer invocation" in result.errors
    assert "global discussion memory requires operator approval" in result.errors


def test_approval_guard_accepts_separate_invocations_with_operator():
    result = approval_invocation_allowed(
        {
            "scope": "global",
            "producer_invocation_id": "producer",
            "judge_invocation_id": "judge",
            "operator_approved": True,
        }
    )

    assert result.valid is True


def test_should_curate_locally_skips_expensive_curator_on_exact_global_lesson():
    event = GlobalPreCurationEvent(
        event_id="evt-claude-router",
        tenant_id="atlas",
        failure_signature="cmd:worker-router:claude:parse-error",
        normalized_text="worker-router claude fails but direct claude sonnet works",
    )
    lesson = {
        "id": "global-lesson-1",
        "status": "approved",
        "scope": "global",
        "sensitivity": "internal",
        "failure_signature": "cmd:worker-router:claude:parse-error",
        "confidence": 0.91,
        "cross_tenant_shareable": True,
    }

    decision = should_curate_locally(event, [lesson])

    assert decision.action == "skip_global_exact_hit"
    assert decision.metric == "global_lesson_hit"
    assert decision.should_run_expensive_curator is False
    assert decision.global_claim_id == "global-lesson-1"


def test_should_curate_locally_near_global_lesson_requires_lightweight_confirmation():
    text = "worker router claude failed repeatedly then direct claude model sonnet print mode worked"
    event = {
        "event_id": "evt-near",
        "tenant_id": "atlas",
        "normalized_text": text,
    }
    lesson = {
        "id": "global-lesson-near",
        "status": "approved",
        "scope": "global",
        "sensitivity": "internal",
        "simhash": simple_simhash(text),
        "confidence": 0.88,
        "cross_tenant_shareable": True,
    }

    decision = should_curate_locally(event, [lesson])

    assert decision.action == "confirm_global_near_hit"
    assert decision.metric == "global_lesson_near_hit"
    assert decision.local_confirmation_required is True
    assert decision.should_run_expensive_curator is False


def test_should_curate_locally_allows_curator_on_miss_and_respects_sensitivity_scope():
    event = {
        "event_id": "evt-miss",
        "tenant_id": "atlas",
        "failure_signature": "cmd:codex:timeout",
        "normalized_text": "codex timed out while planning a flutter migration",
    }
    unusable = {
        "id": "private-other-tenant",
        "status": "approved",
        "tenant_id": "other",
        "sensitivity": "confidential",
        "failure_signature": "cmd:codex:timeout",
        "confidence": 0.95,
    }

    decision = should_curate_locally(event, [unusable])

    assert decision.action == "curate_locally"
    assert decision.metric == "global_lesson_miss"
    assert decision.should_run_expensive_curator is True


def test_should_curate_locally_checks_local_hot_warm_before_global():
    event = {
        "event_id": "evt-local",
        "tenant_id": "atlas",
        "normalized_text": "branch triage should inspect diff before implementation",
    }
    local = {
        "id": "local-hot-1",
        "status": "approved",
        "tier": "hot",
        "tenant_id": "atlas",
        "sensitivity": "internal",
        "text_hash": text_hash("branch triage should inspect diff before implementation"),
        "confidence": 0.8,
    }

    decision = should_curate_locally(event, [], local_lessons=[local])

    assert decision.action == "skip_local_exact_hit"
    assert decision.metric == "local_lesson_hit"
    assert decision.should_run_expensive_curator is False


def test_global_lesson_reuse_metrics_and_feedback_are_aggregate_only():
    metrics = {}

    for metric in [
        "global_lesson_hit",
        "global_lesson_near_hit",
        "global_lesson_used",
        "global_lesson_helped",
        "global_lesson_ignored",
        "global_lesson_hurt",
    ]:
        record_global_lesson_reuse_metric(metrics, metric)

    assert metrics == {
        "global_lesson_hit": 1,
        "global_lesson_near_hit": 1,
        "global_lesson_used": 1,
        "global_lesson_helped": 1,
        "global_lesson_ignored": 1,
        "global_lesson_hurt": 1,
    }

    lesson = {"id": "global-lesson", "confidence": 0.5, "evidence_refs": ["global://redacted/ref"]}
    helped = update_global_lesson_reuse_feedback(lesson, "helped")
    hurt = update_global_lesson_reuse_feedback(helped, "hurt")

    assert helped["confidence"] > lesson["confidence"]
    assert hurt["confidence"] < helped["confidence"]
    assert hurt["reuse_stats"]["global_lesson_helped"] == 1
    assert hurt["reuse_stats"]["global_lesson_hurt"] == 1
    assert hurt["evidence_refs"] == ["global://redacted/ref"]


def test_local_and_global_dreaming_sidecars_are_separate_and_non_mutating(_isolate_hermes_home):
    from hermes_cli.config import load_config

    cfg = load_config()
    cfg["supervisor"]["dreaming"]["enabled"] = True
    cfg["supervisor"]["global_dreaming"]["enabled"] = True
    sidecars = {item.name: item for item in dreaming_sidecar_definitions(cfg)}

    assert sidecars["local_dreaming"].scope == "tenant_repo"
    assert sidecars["local_dreaming"].llm_role == "dreaming"
    assert sidecars["local_dreaming"].source == "approved_local_memory"
    assert sidecars["local_dreaming"].output_topic == "memory.local.dreaming.proposed"
    assert sidecars["local_dreaming"].allow_private_raw_logs is False
    assert sidecars["local_dreaming"].mutates_runtime_state is False

    assert sidecars["global_dreaming"].scope == "global_redacted"
    assert sidecars["global_dreaming"].llm_role == "global_dreaming"
    assert sidecars["global_dreaming"].source == "approved_shareable_global_memory"
    assert sidecars["global_dreaming"].output_topic == "memory.global.dreaming.proposed"
    assert sidecars["global_dreaming"].allow_private_raw_logs is False
    assert sidecars["global_dreaming"].mutates_runtime_state is False


def test_persisted_global_lesson_round_trip_and_exact_retrieval(tmp_path):
    db = _db(tmp_path)
    try:
        lesson = persist_global_lesson(
            db,
            {
                "id": "global-claude-router-repair",
                "approval_state": "approved",
                "scope": "global",
                "visibility": "global_candidate",
                "sensitivity": "internal",
                "claim_type": "command_repair_policy",
                "tenant_id": "atlas",
                "tool": "claude",
                "task_type": "worker_routing",
                "failure_signature": "cmd:worker-router:claude:parse-error",
                "success_signature": "cmd:claude:sonnet:print-mode",
                "normalized_text": "Prefer direct Claude Code invocation after worker-router claude parse errors.",
                "confidence": 0.91,
                "reuse_stats": {"global_lesson_helped": 2},
                "approval_provenance": {"judge_id": "judge-1", "operator_approved": True},
                "evidence_refs": ["global://evidence/claude-router"],
                "cross_tenant_shareable": True,
            },
        )

        result = retrieve_global_lessons_for_event(
            db,
            {
                "event_id": "evt-1",
                "tenant_id": "atlas",
                "tool": "claude",
                "task_type": "worker_routing",
                "failure_signature": "cmd:worker-router:claude:parse-error",
                "normalized_text": "worker-router claude failed",
            },
        )

        assert lesson.id == "global-claude-router-repair"
        assert result.lessons[0]["id"] == "global-claude-router-repair"
        assert result.lessons[0]["reuse_stats"]["global_lesson_helped"] == 2
        assert result.lessons[0]["approval_provenance"]["operator_approved"] is True
        assert result.audit.exact_matches == 1
        assert result.audit.returned == 1

        decision = should_curate_locally(
            {"event_id": "evt-1", "tenant_id": "atlas", "failure_signature": "cmd:worker-router:claude:parse-error"},
            result.lessons,
        )
        assert decision.action == "skip_global_exact_hit"
        assert decision.should_run_expensive_curator is False
    finally:
        db.close()


def test_retrieve_global_lessons_for_event_near_match_and_top_k(tmp_path):
    db = _db(tmp_path)
    try:
        event_text = "worker router claude failed repeatedly direct claude model sonnet print mode worked"
        lesson_text = "claude router wrapper failed repeatedly and direct sonnet print mode worked"
        for idx in range(3):
            persist_global_lesson(
                db,
                {
                    "id": f"global-near-{idx}",
                    "approval_state": "approved",
                    "scope": "global",
                    "visibility": "global_candidate",
                    "sensitivity": "internal",
                    "claim_type": "command_repair_policy",
                    "normalized_text": lesson_text,
                    "simhash": simple_simhash(event_text),
                    "confidence": 0.9 - (idx * 0.01),
                    "cross_tenant_shareable": True,
                },
            )

        result = retrieve_global_lessons_for_event(
            db,
            {"event_id": "evt-near", "tenant_id": "atlas", "normalized_text": event_text},
            limit=2,
        )

        assert [lesson["id"] for lesson in result.lessons] == ["global-near-0", "global-near-1"]
        assert result.audit.near_matches == 3
        assert result.audit.returned == 2
    finally:
        db.close()


def test_retrieve_global_lessons_for_event_metadata_lexical_match(tmp_path):
    db = _db(tmp_path)
    try:
        persist_global_lesson(
            db,
            {
                "id": "global-claude-router-lexical",
                "approval_state": "approved",
                "scope": "global",
                "visibility": "global_candidate",
                "sensitivity": "internal",
                "claim_type": "command_repair_policy",
                "tenant_id": "atlas",
                "tool": "claude",
                "task_type": "worker_routing",
                "failure_signature": "cmd:worker-router:claude:parse-error",
                "normalized_text": "Prefer direct Claude Code invocation after worker-router claude parse errors.",
                "confidence": 0.91,
                "cross_tenant_shareable": True,
            },
        )

        result = retrieve_global_lessons_for_event(
            db,
            {
                "event_id": "evt-claude-task-start",
                "tenant_id": "atlas",
                "tool": "claude",
                "task_type": "worker_routing",
                "normalized_text": "Ask Claude Code what is two plus two",
            },
        )

        assert [lesson["id"] for lesson in result.lessons] == ["global-claude-router-lexical"]
        assert result.audit.matched[0]["reason"] == "metadata_lexical"
    finally:
        db.close()


def test_retrieve_global_lessons_rejects_wrong_tenant_secret_rejected_and_retired(tmp_path):
    db = _db(tmp_path)
    try:
        common = {
            "scope": "tenant",
            "visibility": "global_candidate",
            "claim_type": "command_repair_policy",
            "failure_signature": "cmd:codex:timeout",
            "normalized_text": "codex timed out while planning a flutter migration",
            "confidence": 0.95,
        }
        persist_global_lesson(db, {**common, "id": "wrong-tenant", "approval_state": "approved", "tenant_id": "other", "sensitivity": "confidential"})
        persist_global_lesson(db, {**common, "id": "secret", "approval_state": "approved", "tenant_id": "atlas", "sensitivity": "secret"})
        persist_global_lesson(db, {**common, "id": "rejected", "approval_state": "rejected", "tenant_id": "atlas", "sensitivity": "internal"})
        persist_global_lesson(db, {**common, "id": "retired", "approval_state": "approved", "tenant_id": "atlas", "sensitivity": "internal", "retired_at": 1779000000.0})
        persist_global_lesson(db, {**common, "id": "usable", "approval_state": "approved", "tenant_id": "atlas", "sensitivity": "internal"})

        result = retrieve_global_lessons_for_event(
            db,
            {
                "event_id": "evt-codex",
                "tenant_id": "atlas",
                "failure_signature": "cmd:codex:timeout",
                "normalized_text": "codex timed out while planning a flutter migration",
            },
        )

        assert [lesson["id"] for lesson in result.lessons] == ["usable"]
        rejected = {item["id"]: item["reason"] for item in result.audit.rejected}
        assert rejected["wrong-tenant"] == "scope_or_sensitivity_gate"
        assert "secret" not in rejected
        assert "rejected" not in rejected
        assert "retired" not in rejected
        assert result.audit.considered == 2
    finally:
        db.close()


def test_persisted_global_precuration_records_hit_and_updates_reuse_stats(tmp_path):
    db = _db(tmp_path)
    try:
        persist_global_lesson(
            db,
            {
                "id": "global-hit",
                "approval_state": "approved",
                "scope": "global",
                "visibility": "global_candidate",
                "sensitivity": "internal",
                "claim_type": "command_repair_policy",
                "failure_signature": "cmd:worker-router:claude:parse-error",
                "normalized_text": "Prefer direct Claude after worker-router failures.",
                "confidence": 0.9,
                "cross_tenant_shareable": True,
            },
        )

        result = run_persisted_global_precuration(
            db,
            {
                "event_id": "evt-hit",
                "tenant_id": "atlas",
                "failure_signature": "cmd:worker-router:claude:parse-error",
            },
        )
        stored = retrieve_global_lessons_for_event(
            db,
            {
                "event_id": "evt-hit-2",
                "tenant_id": "atlas",
                "failure_signature": "cmd:worker-router:claude:parse-error",
            },
        ).lessons[0]

        assert result.decision.action == "skip_global_exact_hit"
        assert result.metrics["global_lesson_hit"] == 1
        assert stored["reuse_stats"]["global_lesson_hit"] == 1
    finally:
        db.close()


def test_curator_policy_pass_skips_model_on_persisted_exact_global_lesson(tmp_path):
    from hermes_cli.curator_runtime import CuratorConfig, run_curator_policy_pass

    db = _db(tmp_path)
    try:
        db.upsert_memory_record(
            record_id="memrec_claude",
            kind="tool_routing_lesson",
            title="Claude Code direct invocation works after worker-router failures",
            body="Use direct Claude Code invocation until worker-router is fixed.",
            payload_json={
                "failed_path": "worker-router claude",
                "working_path": "claude --model sonnet -p",
                "failure_signature": "path:worker-router claude",
                "success_signature": "path:claude --model sonnet -p",
            },
            status="active",
            score=0.9,
            tenant_id="atlas",
            repo_id="hermes-agent",
            evidence_uri="hermes:runtime-lesson:memrec_claude",
        )
        persist_global_lesson(
            db,
            {
                "id": "global-claude-router",
                "approval_state": "approved",
                "scope": "global",
                "visibility": "global_candidate",
                "sensitivity": "internal",
                "claim_type": "command_repair_policy",
                "failure_signature": "path:worker-router claude",
                "success_signature": "path:claude --model sonnet -p",
                "normalized_text": "Prefer direct Claude invocation after worker-router failures.",
                "confidence": 0.93,
                "cross_tenant_shareable": True,
            },
        )
        calls = []

        def model_call(_cfg: CuratorConfig, prompt: str) -> str:
            calls.append(prompt)
            return "{}"

        result = run_curator_policy_pass(
            db,
            tenant_id="atlas",
            repo_id="hermes-agent",
            config={"supervisor": {"curator": {"enabled": True, "max_records": 5, "min_score": 0.5}}},
            model_call=model_call,
        )

        assert result.status == "completed"
        assert calls == []
        assert result.candidates_created == 0
        assert result.precuration["records_skipped"] == 1
        assert result.precuration["global_lesson_hit"] == 1
    finally:
        db.close()


def test_curator_policy_pass_calls_model_on_persisted_miss(tmp_path):
    from hermes_cli.curator_runtime import CuratorConfig, run_curator_policy_pass

    db = _db(tmp_path)
    try:
        db.upsert_memory_record(
            record_id="memrec_codex",
            kind="tool_routing_lesson",
            title="Codex timed out",
            body="Codex timed out while planning a migration.",
            payload_json={
                "failed_path": "codex",
                "working_path": "codex --model gpt-5.5",
                "failure_signature": "path:codex",
            },
            status="active",
            score=0.9,
            tenant_id="atlas",
            repo_id="hermes-agent",
            evidence_uri="hermes:runtime-lesson:memrec_codex",
        )
        persist_global_lesson(
            db,
            {
                "id": "wrong-tenant",
                "approval_state": "approved",
                "scope": "tenant",
                "visibility": "global_candidate",
                "sensitivity": "confidential",
                "tenant_id": "other",
                "claim_type": "command_repair_policy",
                "failure_signature": "path:codex",
                "normalized_text": "Other tenant codex repair.",
                "confidence": 0.93,
            },
        )
        calls = []

        def model_call(_cfg: CuratorConfig, prompt: str) -> str:
            calls.append(prompt)
            return "valid advisory curator output"

        result = run_curator_policy_pass(
            db,
            tenant_id="atlas",
            repo_id="hermes-agent",
            config={"supervisor": {"curator": {"enabled": True, "max_records": 5, "min_score": 0.5}}},
            model_call=model_call,
        )

        assert len(calls) == 1
        assert result.precuration["records_skipped"] == 0
        assert result.precuration["global_lesson_miss"] == 1
    finally:
        db.close()


def test_materialize_global_lesson_to_hot_cache_and_retrieve_exact(tmp_path):
    db = _db(tmp_path)
    try:
        lesson = persist_global_lesson(
            db,
            {
                "id": "global-hot-1",
                "approval_state": "approved",
                "scope": "global",
                "visibility": "global_candidate",
                "sensitivity": "internal",
                "claim_type": "command_repair_policy",
                "failure_signature": "cmd:worker-router:claude:parse-error",
                "normalized_text": "Use direct Claude Code invocation after worker-router failures.",
                "confidence": 0.92,
                "evidence_refs": ["global://evidence/1"],
                "cross_tenant_shareable": True,
            },
        )
        event = {
            "event_id": "evt-hot",
            "tenant_id": "atlas",
            "repo_id": "hermes-agent",
            "failure_signature": "cmd:worker-router:claude:parse-error",
        }

        entry = materialize_global_lesson_to_hot_cache(db, lesson.to_dict(), event, ttl_seconds=60)
        hits = retrieve_global_hot_cache_for_event(db, event)

        assert entry.global_lesson_id == "global-hot-1"
        assert hits[0]["global_lesson_id"] == "global-hot-1"
        assert hits[0]["evidence_refs"] == ["global://evidence/1"]
        assert hits[0]["compact_text"]
    finally:
        db.close()


def test_task_hydration_uses_hot_cache_before_global_lookup(tmp_path):
    db = _db(tmp_path)
    try:
        event = {
            "event_id": "evt-cache-first",
            "tenant_id": "atlas",
            "repo_id": "hermes-agent",
            "failure_signature": "cmd:worker-router:claude:parse-error",
        }
        materialize_global_lesson_to_hot_cache(
            db,
            {
                "id": "global-cache-first",
                "scope": "global",
                "sensitivity": "internal",
                "failure_signature": "cmd:worker-router:claude:parse-error",
                "normalized_text": "Use direct Claude Code invocation.",
                "confidence": 0.9,
                "cross_tenant_shareable": True,
            },
            event,
        )

        packet = hydrate_task_memory_from_global(db, event, local_claims=[{"id": "local-1", "text": "Local repo fact."}])

        assert packet.status == "ready"
        assert packet.materialized == 0
        assert packet.retrieval_audit["reason"] == "hot_cache_hit"
        assert [item["source"] for item in packet.advisory_items] == ["local_memory", "global_hot_cache"]
    finally:
        db.close()


def test_task_hydration_retrieves_global_and_materializes_hot_cache_on_miss(tmp_path):
    db = _db(tmp_path)
    try:
        persist_global_lesson(
            db,
            {
                "id": "global-fallback",
                "approval_state": "approved",
                "scope": "global",
                "visibility": "global_candidate",
                "sensitivity": "internal",
                "claim_type": "command_repair_policy",
                "failure_signature": "cmd:worker-router:claude:parse-error",
                "normalized_text": "Use direct Claude Code invocation after worker-router failures.",
                "confidence": 0.92,
                "cross_tenant_shareable": True,
            },
        )
        event = {
            "event_id": "evt-fallback",
            "tenant_id": "atlas",
            "repo_id": "hermes-agent",
            "failure_signature": "cmd:worker-router:claude:parse-error",
        }

        packet = hydrate_task_memory_from_global(db, event)
        hot_hits = retrieve_global_hot_cache_for_event(db, event)

        assert packet.materialized == 1
        assert packet.retrieval_audit["exact_matches"] == 1
        assert hot_hits[0]["global_lesson_id"] == "global-fallback"
        assert packet.advisory_items[0]["source"] == "global_hot_cache"
    finally:
        db.close()


def test_task_hydration_enforces_token_budget(tmp_path):
    db = _db(tmp_path)
    try:
        event = {
            "event_id": "evt-budget",
            "tenant_id": "atlas",
            "repo_id": "hermes-agent",
            "failure_signature": "cmd:worker-router:claude:parse-error",
        }
        materialize_global_lesson_to_hot_cache(
            db,
            {
                "id": "global-budget",
                "scope": "global",
                "sensitivity": "internal",
                "failure_signature": "cmd:worker-router:claude:parse-error",
                "normalized_text": "Use direct Claude Code invocation after worker-router failures.",
                "confidence": 0.9,
                "cross_tenant_shareable": True,
            },
            event,
        )

        packet = hydrate_task_memory_from_global(
            db,
            event,
            local_claims=[{"id": "too-large", "text": "x" * 400}],
            token_budget=20,
        )

        assert packet.estimated_tokens <= 20
        assert [item["source"] for item in packet.advisory_items] == ["global_hot_cache"]
    finally:
        db.close()


def test_global_indexer_sidecar_indexes_only_approved_shareable_metadata(tmp_path):
    db = _db(tmp_path)
    secret_value = "sk-live-secret-transcript"
    try:
        base = {
            "approval_state": "approved",
            "scope": "global",
            "visibility": "global_candidate",
            "sensitivity": "internal",
            "claim_type": "command_repair_policy",
            "failure_signature": "cmd:pytest:sqlite",
            "normalized_text": "Use sqlite local metadata for approved global lesson indexing.",
            "confidence": 0.9,
            "cross_tenant_shareable": True,
            "evidence_refs": ["global://evidence/index-ok"],
        }
        persist_global_lesson(db, {**base, "id": "idx-ok", "tool": "terminal"})
        persist_global_lesson(db, {**base, "id": "idx-proposed", "approval_state": "proposed"})
        persist_global_lesson(db, {**base, "id": "idx-private", "scope": "private"})
        persist_global_lesson(db, {**base, "id": "idx-secret", "sensitivity": "secret", "normalized_text": f"Never sync {secret_value}."})
        persist_global_lesson(db, {**base, "id": "idx-tenant-only", "cross_tenant_shareable": False})
        persist_global_lesson(db, {**base, "id": "idx-retired", "retired_at": 1779000000.0})

        result = run_global_indexer_sidecar(db, _sidecar_config(), once=True)
        result_json = result.to_dict()
        result_blob = repr(result_json)

        assert result.status == "ok"
        assert result.feature_enabled is True
        assert result.scanned == 6
        assert result.indexed == 1
        assert result.skipped == 5
        assert secret_value not in result_blob
        skip_reasons = {item["id"]: item["reason"] for item in result_json["refs"]["skipped"]}
        assert skip_reasons["idx-proposed"] == "not_approved_canonical"
        assert skip_reasons["idx-private"] == "not_global_scope"
        assert skip_reasons["idx-secret"] == "secret_sensitivity"
        assert skip_reasons["idx-tenant-only"] == "not_cross_tenant_shareable"
        assert skip_reasons["idx-retired"] == "retired_or_deleted"

        rows = db._execute_write(
            lambda conn: [dict(row) for row in conn.execute("SELECT * FROM hermes_global_lesson_index").fetchall()]
        )
        assert [row["lesson_id"] for row in rows] == ["idx-ok"]
        storage_blob = repr(rows)
        assert "sqlite local metadata" not in storage_blob
        assert secret_value not in storage_blob
        assert rows[0]["text_hash"]
        assert rows[0]["lexical_terms_json"]
        assert rows[0]["vector_stub_json"]

        second = run_global_indexer_sidecar(db, _sidecar_config(), once=True)
        count = db._execute_write(lambda conn: conn.execute("SELECT COUNT(*) FROM hermes_global_lesson_index").fetchone()[0])
        assert second.indexed == 0
        assert second.updated == 1
        assert count == 1
    finally:
        db.close()


def test_local_sync_sidecar_applies_relevant_deltas_idempotently(tmp_path):
    db = _db(tmp_path)
    raw_text = "Use direct Claude Code invocation after worker-router failures."
    try:
        common = {
            "approval_state": "approved",
            "scope": "global",
            "visibility": "global_candidate",
            "sensitivity": "internal",
            "claim_type": "command_repair_policy",
            "failure_signature": "cmd:worker-router:claude:parse-error",
            "normalized_text": raw_text,
            "confidence": 0.92,
            "cross_tenant_shareable": True,
            "tool": "terminal",
            "task_type": "implementation",
        }
        persist_global_lesson(db, {**common, "id": "sync-ok"})
        persist_global_lesson(db, {**common, "id": "sync-other-tool", "tool": "browser"})
        persist_global_lesson(db, {**common, "id": "sync-empty-tool", "tool": ""})
        run_global_indexer_sidecar(db, _sidecar_config(), once=True)

        result = run_local_sync_sidecar(
            db,
            _sidecar_config(ttl_seconds=120),
            once=True,
            tenant_id="atlas",
            repo_id="hermes-agent",
            tool="terminal",
            task_type="implementation",
        )

        assert result.status == "ok"
        assert result.feature_enabled is True
        assert result.scanned == 3
        assert result.synced == 1
        assert result.skipped == 2
        assert result.demoted == 0
        assert result.removed == 0
        assert raw_text not in repr(result.to_dict())
        hits = retrieve_global_hot_cache_for_event(
            db,
            {
                "event_id": "evt-sync",
                "tenant_id": "atlas",
                "repo_id": "hermes-agent",
                "tool": "terminal",
                "task_type": "implementation",
                "failure_signature": "cmd:worker-router:claude:parse-error",
            },
        )
        assert [hit["global_lesson_id"] for hit in hits] == ["sync-ok"]
        sidecar_rows = db._execute_write(
            lambda conn: [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT lesson_id, tenant_id, repo_id, tool, task_type, action, metadata_json
                    FROM hermes_global_sync_deltas
                    ORDER BY lesson_id
                    """
                ).fetchall()
            ]
        )
        assert [row["lesson_id"] for row in sidecar_rows] == ["sync-ok"]
        assert raw_text not in repr(sidecar_rows)

        second = run_local_sync_sidecar(
            db,
            _sidecar_config(ttl_seconds=120),
            once=True,
            tenant_id="atlas",
            repo_id="hermes-agent",
            tool="terminal",
            task_type="implementation",
        )
        count = db._execute_write(lambda conn: conn.execute("SELECT COUNT(*) FROM hermes_global_hot_cache").fetchone()[0])
        assert second.synced == 0
        assert second.updated == 1
        assert count == 1
    finally:
        db.close()


def test_local_sync_sidecar_marks_orphaned_index_rows_removed(tmp_path):
    db = _db(tmp_path)
    try:
        persist_global_lesson(
            db,
            {
                "id": "sync-orphan-index",
                "approval_state": "approved",
                "scope": "global",
                "visibility": "global_candidate",
                "sensitivity": "internal",
                "claim_type": "command_repair_policy",
                "failure_signature": "cmd:pytest:orphan",
                "normalized_text": "Deleted global lessons should remove orphaned index rows.",
                "confidence": 0.9,
                "cross_tenant_shareable": True,
                "tool": "terminal",
                "task_type": "implementation",
            },
        )
        indexed = run_global_indexer_sidecar(db, _sidecar_config(), once=True)
        assert indexed.indexed == 1

        db._execute_write(lambda conn: conn.execute("DELETE FROM hermes_global_lessons WHERE id = ?", ("sync-orphan-index",)))

        removed = run_local_sync_sidecar(
            db,
            _sidecar_config(ttl_seconds=120),
            once=True,
            tenant_id="atlas",
            repo_id="hermes-agent",
            tool="terminal",
            task_type="implementation",
        )

        assert removed.removed == 1
        row = db._execute_write(
            lambda conn: dict(
                conn.execute(
                    "SELECT deleted_at, retired_at FROM hermes_global_lesson_index WHERE lesson_id = ?",
                    ("sync-orphan-index",),
                ).fetchone()
            )
        )
        assert row["deleted_at"] is not None
    finally:
        db.close()


def test_local_sync_sidecar_demotes_expired_and_removes_retired_or_deleted(tmp_path):
    db = _db(tmp_path)
    try:
        lesson = persist_global_lesson(
            db,
            {
                "id": "sync-retire",
                "approval_state": "approved",
                "scope": "global",
                "visibility": "global_candidate",
                "sensitivity": "internal",
                "claim_type": "command_repair_policy",
                "failure_signature": "cmd:pytest:ttl",
                "normalized_text": "Demote expired cache rows and remove retired global lessons.",
                "confidence": 0.9,
                "cross_tenant_shareable": True,
                "tool": "terminal",
                "task_type": "implementation",
            },
        )
        event = {
            "event_id": "evt-retire",
            "tenant_id": "atlas",
            "repo_id": "hermes-agent",
            "tool": "terminal",
            "task_type": "implementation",
            "failure_signature": "cmd:pytest:ttl",
        }
        materialize_global_lesson_to_hot_cache(db, lesson.to_dict(), event, ttl_seconds=-1)
        expired = run_local_sync_sidecar(db, _sidecar_config(ttl_seconds=120), once=True, tenant_id="atlas", repo_id="hermes-agent", tool="terminal")
        assert expired.demoted == 1

        run_global_indexer_sidecar(db, _sidecar_config(), once=True)
        materialize_global_lesson_to_hot_cache(db, lesson.to_dict(), event, ttl_seconds=120)
        persist_global_lesson(db, {**lesson.to_dict(), "retired_at": 1779000000.0})
        removed = run_local_sync_sidecar(db, _sidecar_config(ttl_seconds=120), once=True, tenant_id="atlas", repo_id="hermes-agent", tool="terminal")

        assert removed.removed >= 1
        cache_count = db._execute_write(lambda conn: conn.execute("SELECT COUNT(*) FROM hermes_global_hot_cache WHERE global_lesson_id = 'sync-retire'").fetchone()[0])
        index_count = db._execute_write(lambda conn: conn.execute("SELECT COUNT(*) FROM hermes_global_lesson_index WHERE lesson_id = 'sync-retire' AND deleted_at IS NULL").fetchone()[0])
        assert cache_count == 0
        assert index_count == 0
    finally:
        db.close()


def test_sidecars_default_disabled_do_not_mutate_foreground_paths(tmp_path):
    db = _db(tmp_path)
    try:
        persist_global_lesson(
            db,
            {
                "id": "disabled-ok",
                "approval_state": "approved",
                "scope": "global",
                "visibility": "global_candidate",
                "sensitivity": "internal",
                "claim_type": "command_repair_policy",
                "normalized_text": "Disabled sidecars should not mutate local indexes.",
                "confidence": 0.9,
                "cross_tenant_shareable": True,
            },
        )

        index_result = run_global_indexer_sidecar(db, {"supervisor": {"global_memory_wiki": {}}}, once=True)
        sync_result = run_local_sync_sidecar(db, {"supervisor": {"global_memory_wiki": {}}}, once=True, tenant_id="atlas")

        assert index_result.status == "disabled"
        assert index_result.feature_enabled is False
        assert sync_result.status == "disabled"
        assert sync_result.feature_enabled is False
        tables = db._execute_write(
            lambda conn: [
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('hermes_global_lesson_index', 'hermes_global_sync_deltas')"
                ).fetchall()
            ]
        )
        assert tables == []
    finally:
        db.close()


def test_global_index_and_memory_sync_cli_json_smoke(tmp_path, monkeypatch, capsys):
    home = tmp_path / ".hermes"
    monkeypatch.setenv("HERMES_HOME", str(home))
    import hermes_state
    from hermes_cli.config import load_config, save_config

    monkeypatch.setattr(hermes_state, "DEFAULT_DB_PATH", home / "state.db")
    cfg = load_config()
    cfg["supervisor"]["global_memory_wiki"].setdefault("sidecars", {})
    cfg["supervisor"]["global_memory_wiki"]["sidecars"]["global_indexer"] = {
        "enabled": True,
        "mode": "local",
        "max_batch": 100,
    }
    cfg["supervisor"]["global_memory_wiki"]["sidecars"]["local_sync"] = {
        "enabled": True,
        "mode": "local",
        "ttl_seconds": 120,
        "max_batch": 100,
    }
    save_config(cfg)

    db = SessionDB()
    try:
        persist_global_lesson(
            db,
            {
                "id": "cli-sync-ok",
                "approval_state": "approved",
                "scope": "global",
                "visibility": "global_candidate",
                "sensitivity": "internal",
                "claim_type": "command_repair_policy",
                "failure_signature": "cmd:cli:json",
                "normalized_text": "CLI sidecars index approved metadata and sync relevant cache rows.",
                "confidence": 0.9,
                "cross_tenant_shareable": True,
                "tool": "terminal",
                "task_type": "implementation",
            },
        )
    finally:
        db.close()

    from hermes_cli import main as hermes_main

    with patch.object(sys, "argv", ["hermes", "memory", "global", "index", "--once", "--json"]):
        hermes_main.main()
    indexed = json.loads(capsys.readouterr().out)
    assert indexed["status"] == "ok"
    assert indexed["indexed"] == 1

    with patch.object(
        sys,
        "argv",
        [
            "hermes",
            "memory",
            "sync",
            "--once",
            "--tenant-id",
            "atlas",
            "--repo-id",
            "hermes-agent",
            "--tool",
            "terminal",
            "--task-type",
            "implementation",
            "--json",
        ],
    ):
        hermes_main.main()
    synced = json.loads(capsys.readouterr().out)
    assert synced["status"] == "ok"
    assert synced["synced"] == 1
    assert synced["demoted"] == 0
    assert synced["removed"] == 0
