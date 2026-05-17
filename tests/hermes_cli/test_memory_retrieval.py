from pathlib import Path

from hermes_cli.memory_retrieval import (
    build_memory_packet,
    classify_task_query,
    record_memory_feedback,
    retrieve_memory_candidates,
    score_retrieval_candidate,
)
from hermes_state import SessionDB


def _make_db(tmp_path: Path) -> SessionDB:
    return SessionDB(db_path=tmp_path / "state.db")


def test_task_classifier_extracts_tool_entities_and_signatures():
    query = "worker-router claude failed with unknown option, then claude --model sonnet works"

    classified = classify_task_query(query, tenant_id="atlas", repo_id="hermes-agent", tool="claude")

    assert classified.task_type == "tool_routing"
    assert classified.intent == "repair"
    assert "claude" in classified.entities
    assert classified.error_signatures
    assert classified.success_signatures


def test_relevance_scorer_rewards_exact_match_and_penalizes_scope():
    query = classify_task_query("claude worker-router failed", tenant_id="atlas", repo_id="repo-a")
    candidate = {
        "id": "metacand_1",
        "kind": "routing_hint",
        "claim": "worker-router claude failed; use direct claude",
        "score": 0.9,
        "status": "approved",
        "tenant_id": "atlas",
        "repo_id": "repo-a",
        "evidence_json": {"failed_path": "worker-router claude"},
    }
    wrong_repo = dict(candidate, id="metacand_2", repo_id="repo-b")

    good = score_retrieval_candidate(candidate, query)
    bad = score_retrieval_candidate(wrong_repo, query)

    assert good.score > bad.score
    assert "claude" in good.features["matched_terms"]


def test_retrieval_run_audit_and_packet_builder(tmp_path):
    db = _make_db(tmp_path)
    try:
        db.upsert_meta_candidate(
            candidate_id="metacand_1",
            kind="routing_hint",
            claim="Prefer direct Claude after worker-router claude failures",
            evidence_json={"failed_path": "worker-router claude", "working_path": "claude --model sonnet -p"},
            score=0.9,
            status="approved",
            tenant_id="atlas",
            repo_id="hermes-agent",
        )
        query = classify_task_query("worker-router claude failed", tenant_id="atlas", repo_id="hermes-agent")

        result = retrieve_memory_candidates(db, query=query, statuses=["approved"], limit=3, min_score=0.5)
        packet = build_memory_packet(query=query, candidates=result["candidates"], max_chars=1000)

        assert result["audit"]["candidates_considered"] >= 1
        assert result["audit"]["candidates_returned"] == 1
        assert packet["header"].startswith("ADVISORY MEMORY ONLY")
        assert packet["candidates"][0]["evidence_label"] is None
        assert "hermes-agent" in packet["candidates"][0]["scope_labels"]
    finally:
        db.close()


def test_memory_feedback_adjusts_confidence(tmp_path):
    db = _make_db(tmp_path)
    try:
        db.upsert_meta_candidate(
            candidate_id="metacand_feedback",
            kind="playbook",
            claim="A useful lesson",
            evidence_json={"record_id": "rec-1"},
            score=0.7,
            status="approved",
        )

        helpful = record_memory_feedback(db, candidate_id="metacand_feedback", outcome="helpful", reason="used")
        irrelevant = record_memory_feedback(db, candidate_id="metacand_feedback", outcome="irrelevant", reason="wrong")
        harmful = record_memory_feedback(db, candidate_id="metacand_feedback", outcome="harmful", reason="bad")

        assert helpful["score"] > 0.7
        assert irrelevant["score"] < helpful["score"]
        assert harmful["score"] < irrelevant["score"]
        row = db.get_meta_candidate("metacand_feedback")
        assert len(row["evidence_json"]["feedback"]) == 3
    finally:
        db.close()
