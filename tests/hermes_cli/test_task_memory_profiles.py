import json
import os
import subprocess
import sys

from hermes_cli.global_memory import persist_global_lesson
from hermes_cli.global_memory_sidecars import materialize_global_lesson_to_hot_cache
from hermes_cli.task_memory_profiles import build_task_memory_retrieval_profile
from hermes_state import SessionDB


def _db(tmp_path):
    return SessionDB(db_path=tmp_path / "state.db")


def _event(**overrides):
    data = {
        "event_id": "evt-profile",
        "tenant_id": "atlas",
        "repo_id": "hermes-agent",
        "tool": "terminal",
        "task_type": "implementation",
        "worker_kind": "low_cost_worker",
        "command_signature": "cmd:pytest:global-memory",
        "error_signature": "err:sqlite:locked",
        "normalized_text": "pytest global memory failed with sqlite locked",
    }
    data.update(overrides)
    return data


def _lesson(**overrides):
    data = {
        "id": "lesson-positive",
        "approval_state": "approved",
        "scope": "repo",
        "visibility": "global_candidate",
        "sensitivity": "internal",
        "claim_type": "command_repair_policy",
        "tenant_id": "atlas",
        "repo_id": "hermes-agent",
        "tool": "terminal",
        "task_type": "implementation",
        "worker_kind": "low_cost_worker",
        "failure_signature": "err:sqlite:locked",
        "success_signature": "cmd:pytest:global-memory",
        "normalized_text": (
            "When pytest global memory fails with sqlite locked, retry through "
            "the state DB write helper instead of opening a raw transaction."
        ),
        "confidence": 0.93,
        "reuse_stats": {"global_lesson_helped": 3},
        "evidence_refs": ["global://evidence/positive"],
    }
    data.update(overrides)
    return data


def _vector_graph_config(tmp_path, *, enabled=True, threshold=0.8):
    return {
        "supervisor": {
            "global_memory_wiki": {
                "task_memory_profile": {
                    "vector_graph_fallback": {
                        "enabled": enabled,
                        "min_exact_score": threshold,
                        "max_candidates": 5,
                    }
                },
                "vector_index": {
                    "backend": "local_fake",
                    "uri": str(tmp_path / "profile-vector.sqlite"),
                },
                "graph_index": {
                    "backend": "sqlite",
                    "uri": str(tmp_path / "profile-graph.sqlite"),
                },
            }
        }
    }


def test_exact_approved_profile_hit_is_scoped_bounded_and_llm_free(tmp_path):
    db = _db(tmp_path)
    try:
        persist_global_lesson(
            db,
            _lesson(
                id="lesson-exact-1",
                normalized_text="Use HERMES_SAFE_TOKEN=sk-secret raw transcript should not leak.",
            ),
        )
        persist_global_lesson(
            db,
            _lesson(
                id="lesson-exact-2",
                normalized_text="Second valid exact scoped lesson.",
                confidence=0.91,
                evidence_refs=["global://evidence/second"],
            ),
        )
        persist_global_lesson(
            db,
            _lesson(
                id="lesson-exact-3",
                normalized_text="Third valid exact scoped lesson.",
                confidence=0.90,
                evidence_refs=["global://evidence/third"],
            ),
        )
        persist_global_lesson(
            db,
            _lesson(
                id="lesson-exact-4",
                normalized_text="Fourth valid exact scoped lesson must be capped out.",
                confidence=0.89,
            ),
        )

        profile = build_task_memory_retrieval_profile(
            db,
            _event(),
            profile="low_cost_worker",
            top_k=10,
            token_budget=240,
        ).to_dict()

        assert profile["profile"] == "low_cost_worker"
        assert profile["mode"] == "programmatic"
        assert profile["llm_calls"] == []
        assert profile["exact_hit"] is True
        assert profile["semantic_fallback_used"] is False
        assert profile["fallback_backend"] == "disabled"
        assert profile["top_k_cap"] == 3
        assert profile["filters"] == {
            "tenant_id": "atlas",
            "repo_id": "hermes-agent",
            "tool": "terminal",
            "task_type": "implementation",
            "worker_kind": "low_cost_worker",
        }
        assert [item["id"] for item in profile["matches"]] == [
            "lesson-exact-1",
            "lesson-exact-2",
            "lesson-exact-3",
        ]
        assert [item["id"] for item in profile["injection_items"]] == [
            "lesson-exact-1",
            "lesson-exact-2",
            "lesson-exact-3",
        ]
        assert all("payload_json" not in item for item in profile["matches"])
        rendered = json.dumps(profile, sort_keys=True)
        assert "sk-secret" not in rendered
        assert "raw transcript" not in rendered
        assert "should_run_expensive_curator" not in rendered
        assert profile["retrieval_audit"]["exact_matches"] == 4
    finally:
        db.close()


def test_profile_filters_cross_scope_memories(tmp_path):
    db = _db(tmp_path)
    try:
        persist_global_lesson(db, _lesson(id="good"))
        persist_global_lesson(db, _lesson(id="wrong-tenant", tenant_id="other"))
        persist_global_lesson(db, _lesson(id="wrong-repo", repo_id="other-repo"))
        persist_global_lesson(db, _lesson(id="wrong-tool", tool="browser"))
        persist_global_lesson(db, _lesson(id="wrong-task", task_type="research"))

        profile = build_task_memory_retrieval_profile(db, _event()).to_dict()

        assert [item["id"] for item in profile["matches"]] == ["good"]
        rejected = {item["id"]: item["reason"] for item in profile["retrieval_audit"]["rejected"]}
        assert rejected["wrong-tenant"] == "tenant_mismatch"
        assert rejected["wrong-repo"] == "repo_mismatch"
        assert rejected["wrong-tool"] == "tool_mismatch"
        assert rejected["wrong-task"] == "task_type_mismatch"
    finally:
        db.close()


def test_profile_demotes_negative_feedback_below_positive_match(tmp_path):
    db = _db(tmp_path)
    try:
        persist_global_lesson(db, _lesson(id="negative", confidence=0.99, reuse_stats={"global_lesson_hurt": 4, "global_lesson_helped": 1}))
        persist_global_lesson(db, _lesson(id="positive", confidence=0.91, reuse_stats={"global_lesson_helped": 2}))

        profile = build_task_memory_retrieval_profile(db, _event(), top_k=2).to_dict()

        assert [item["id"] for item in profile["matches"]] == ["positive", "negative"]
        assert profile["matches"][1]["demotion_applied"] is True
        assert profile["demoted"] == [{"id": "negative", "reason": "negative_feedback_exceeds_positive"}]
    finally:
        db.close()


def test_profile_token_budget_caps_output_and_reports_exhaustion(tmp_path):
    db = _db(tmp_path)
    try:
        persist_global_lesson(db, _lesson(id="small", normalized_text="Short approved fix.", confidence=0.95))
        persist_global_lesson(db, _lesson(id="large", normalized_text="x" * 800, confidence=0.94))

        profile = build_task_memory_retrieval_profile(db, _event(), top_k=3, token_budget=12).to_dict()

        assert [item["id"] for item in profile["injection_items"]] == ["small"]
        assert profile["estimated_tokens"] <= 12
        assert profile["budget_exhausted"] is True
        assert {item["id"] for item in profile["matches"]} == {"small", "large"}
    finally:
        db.close()


def test_profile_semantic_local_fake_fallback_is_llm_free(tmp_path):
    db = _db(tmp_path)
    try:
        profile = build_task_memory_retrieval_profile(db, _event(), semantic_fallback=True).to_dict()

        assert profile["exact_hit"] is False
        assert profile["semantic_fallback_used"] is True
        assert profile["fallback_backend"] == "local_fake"
        assert profile["llm_calls"] == []
        assert profile["matches"][0]["source"] == "semantic_fallback"
        assert profile["matches"][0]["match_kind"] == "semantic_fallback"
        assert profile["matches"][0]["advisory"]
    finally:
        db.close()


def test_profile_vector_graph_fallback_is_disabled_by_default(tmp_path):
    db = _db(tmp_path)
    try:
        profile = build_task_memory_retrieval_profile(
            db,
            _event(error_signature="err:no-local-match", normalized_text="no local match"),
            semantic_fallback=False,
        ).to_dict()

        assert profile["exact_hit"] is False
        assert profile["signature_hit"] is False
        assert profile["vector_fallback_used"] is False
        assert profile["graph_fallback_used"] is False
        assert profile["metrics"] == {
            "exact_hit": 0,
            "signature_hit": 0,
            "vector_fallback_used": 0,
            "graph_fallback_used": 0,
            "skipped_private": 0,
            "skipped_secret": 0,
        }
        assert profile["matches"] == []
    finally:
        db.close()


def test_profile_exact_signature_hit_blocks_configured_vector_graph_fallback(tmp_path):
    db = _db(tmp_path)
    try:
        persist_global_lesson(db, _lesson(id="exact-first"))
        persist_global_lesson(
            db,
            _lesson(
                id="fallback-candidate",
                failure_signature="different",
                success_signature="different",
                normalized_text="sqlite locked fallback candidate shares query tokens",
                confidence=0.91,
                scope="global",
                cross_tenant_shareable=True,
            ),
        )

        profile = build_task_memory_retrieval_profile(
            db,
            _event(),
            config=_vector_graph_config(tmp_path),
        ).to_dict()

        assert [item["id"] for item in profile["matches"]] == ["exact-first"]
        assert profile["exact_hit"] is True
        assert profile["signature_hit"] is True
        assert profile["vector_fallback_used"] is False
        assert profile["graph_fallback_used"] is False
        assert profile["metrics"]["exact_hit"] == 1
        assert profile["metrics"]["signature_hit"] == 1
        assert profile["retrieval_audit"]["fallback_reason"] == "local_exact_signature_hit"
    finally:
        db.close()


def test_profile_hot_cache_signature_hit_is_first_path_before_vector_graph_fallback(tmp_path):
    db = _db(tmp_path)
    try:
        materialize_global_lesson_to_hot_cache(
            db,
            _lesson(
                id="hot-cache-first",
                scope="global",
                cross_tenant_shareable=True,
                confidence=0.42,
                normalized_text="Hot cache exact signature lesson must win before fallback.",
            ),
            _event(),
        )
        persist_global_lesson(
            db,
            _lesson(
                id="fallback-candidate",
                failure_signature="different",
                success_signature="different",
                normalized_text="sqlite locked fallback candidate shares query tokens",
                confidence=0.99,
                scope="global",
                cross_tenant_shareable=True,
            ),
        )

        profile = build_task_memory_retrieval_profile(
            db,
            _event(),
            config=_vector_graph_config(tmp_path, threshold=1.0),
            semantic_fallback=False,
        ).to_dict()

        assert [item["id"] for item in profile["matches"]] == ["hot-cache-first"]
        assert profile["matches"][0]["source"] == "global_hot_cache"
        assert profile["exact_hit"] is True
        assert profile["signature_hit"] is True
        assert profile["vector_fallback_used"] is False
        assert profile["graph_fallback_used"] is False
        assert profile["metrics"]["exact_hit"] == 1
        assert profile["metrics"]["signature_hit"] == 1
        assert profile["metrics"]["vector_fallback_used"] == 0
        assert profile["metrics"]["graph_fallback_used"] == 0
        assert profile["retrieval_audit"]["fallback_reason"] == "local_hot_cache_exact_signature_hit"
        assert profile["retrieval_audit"]["hot_cache_matches"] == 1
    finally:
        db.close()


def test_profile_vector_graph_fallback_indexes_only_approved_canonical_global_lessons(tmp_path):
    db = _db(tmp_path)
    secret_text = "raw transcript sk-live-secret-vector should never be indexed"
    try:
        common = _lesson(
            failure_signature="different-failure",
            success_signature="different-success",
            normalized_text="sqlite locked profile fallback should retry through state helper",
            confidence=0.88,
            scope="global",
            visibility="global_candidate",
            cross_tenant_shareable=True,
        )
        persist_global_lesson(db, {**common, "id": "vector-graph-ok"})
        persist_global_lesson(db, {**common, "id": "private-scope", "scope": "private"})
        persist_global_lesson(db, {**common, "id": "tenant-only", "cross_tenant_shareable": False})
        persist_global_lesson(db, {**common, "id": "secret-sensitivity", "sensitivity": "secret"})
        persist_global_lesson(db, {**common, "id": "raw-secret-text", "normalized_text": secret_text})
        persist_global_lesson(db, {**common, "id": "raw-proposal", "approval_state": "proposed"})

        profile = build_task_memory_retrieval_profile(
            db,
            _event(
                error_signature="err:totally-different",
                command_signature="cmd:totally-different",
                normalized_text="sqlite locked profile fallback state helper",
            ),
            config=_vector_graph_config(tmp_path),
            semantic_fallback=False,
            top_k=3,
        ).to_dict()
        rendered = json.dumps(profile, sort_keys=True)

        assert [item["id"] for item in profile["matches"]] == ["vector-graph-ok"]
        assert profile["exact_hit"] is False
        assert profile["signature_hit"] is False
        assert profile["vector_fallback_used"] is True
        assert profile["graph_fallback_used"] is True
        assert profile["fallback_backend"] == "local_fake_vector+sqlite_graph"
        assert profile["metrics"]["vector_fallback_used"] == 1
        assert profile["metrics"]["graph_fallback_used"] == 1
        assert profile["metrics"]["skipped_private"] == 2
        assert profile["metrics"]["skipped_secret"] == 2
        assert "private-scope" not in rendered
        assert "tenant-only" not in rendered
        assert "secret-sensitivity" not in rendered
        assert "raw-secret-text" not in rendered
        assert "raw-proposal" not in rendered
        assert "sk-live-secret-vector" not in rendered
        assert "raw transcript" not in rendered
    finally:
        db.close()


def test_memory_global_profile_cli_json_preview_is_bounded(tmp_path):
    db = _db(tmp_path)
    try:
        persist_global_lesson(
            db,
            _lesson(
                id="cli-good",
                normalized_text="Use bounded profile output. SECRET_TOKEN=sk-cli-secret raw transcript hidden.",
            ),
        )
    finally:
        db.close()

    env = os.environ.copy()
    env["HERMES_HOME"] = str(tmp_path)
    event_json = json.dumps(_event())
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "hermes_cli.main",
            "memory",
            "global",
            "profile",
            "--event-json",
            event_json,
            "--top-k",
            "3",
            "--token-budget",
            "240",
            "--json",
        ],
        cwd=os.getcwd(),
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["profile"] == "low_cost_worker"
    assert payload["mode"] == "programmatic"
    assert payload["llm_calls"] == []
    assert payload["matches"][0]["id"] == "cli-good"
    rendered = json.dumps(payload, sort_keys=True)
    assert "sk-cli-secret" not in rendered
    assert "raw transcript" not in rendered
