import json
import os
import subprocess
import sys

from hermes_cli.global_memory import persist_global_lesson
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
