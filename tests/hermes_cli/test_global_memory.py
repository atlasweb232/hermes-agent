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
    persist_global_lesson,
    publish_global_proposal,
    record_global_lesson_reuse_metric,
    retrieve_global_lessons_for_event,
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


def test_global_memory_config_defaults_exist(_isolate_hermes_home):
    from hermes_cli.config import load_config

    cfg = load_config()
    wiki = cfg["supervisor"]["global_memory_wiki"]
    bus = cfg["supervisor"]["global_memory_bus"]

    assert wiki["object_store"]["backend"] == "local"
    assert wiki["state_store"]["backend"] == "sqlite"
    assert wiki["vector_index"]["backend"] == "disabled"
    assert wiki["require_global_approval"] is True
    assert bus["backend"] == "sqlite"
    assert bus["topic_prefix"] == "hermes.memory"
    assert wiki["precuration"]["skip_expensive_curator_on_exact"] is True


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
    from hermes_cli.model_roles import role_names, get_model_role

    names = set(role_names())
    assert {"discussion_capture", "claim_extractor", "wiki_compiler", "dreaming", "global_dreaming", "citation_validator"} <= names
    role = get_model_role(load_config(), "claim_extractor")
    assert role["path"] == "supervisor.sidecar_models.claim_extractor"
    assert role["tier"] == "low_cost_reasoning"
    assert role["config"]["provider"] == "deepseek"


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
