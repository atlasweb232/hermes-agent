import pytest

from hermes_cli.global_memory import (
    DiscussionMemoryRecord,
    approval_invocation_allowed,
    build_global_topic,
    build_idempotency_key,
    classify_dedupe,
    discussion_sidecar_definitions,
    discussion_storage_config,
    fanout_canonical_claim_to_indexes,
    fanout_discussion_record_to_indexes,
    get_global_memory_bus,
    normalize_proposal,
    publish_global_proposal,
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
    assert {"discussion_capture", "claim_extractor", "wiki_compiler", "dreaming", "citation_validator"} <= names
    role = get_model_role(load_config(), "claim_extractor")
    assert role["path"] == "supervisor.sidecar_models.claim_extractor"
    assert role["config"]["provider"] == "codex"


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
