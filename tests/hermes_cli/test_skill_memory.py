import json
from pathlib import Path

from hermes_state import SessionDB
from hermes_cli.skill_memory import (
    SkillMemoryRegistry,
    build_bounded_skill_packet,
    build_skill_metadata,
    build_skill_retrieval_query,
    retrieve_skills,
    stable_json,
)


def _db(tmp_path: Path) -> SessionDB:
    return SessionDB(db_path=tmp_path / "state.db")


def _skill(**overrides):
    base = {
        "name": "ci repair",
        "version": "1.0.0",
        "scope": "repo",
        "tenant_id": "tenant-a",
        "repo_id": "repo-a",
        "domain": "ci",
        "toolset": "terminal",
        "worker_role": "worker",
        "task_type": "validation",
        "language": "python",
        "platform": "linux",
        "approval_state": "approved",
        "safety_state": "safe",
        "content": "Use pytest -q after editing. SECRET_TOKEN=raw-value",
        "summary": "Repair CI pytest failures and rerun focused tests.",
        "source_memory_refs": ["mem-1"],
        "source_wiki_refs": ["wiki-1"],
        "validation_refs": ["pytest://tests/hermes_cli/test_ci.py"],
        "safety_notes": ["No secrets or destructive commands."],
    }
    base.update(overrides)
    return build_skill_metadata(**base)


def test_skill_metadata_schema_is_deterministic_and_hashes_content_only():
    skill = _skill()

    required = {
        "skill_id",
        "name",
        "version",
        "scope",
        "tenant_id",
        "repo_id",
        "domain",
        "toolset",
        "worker_role",
        "task_type",
        "language",
        "platform",
        "approval_state",
        "safety_state",
        "content_sha256",
        "bundle_tree_sha256",
        "source_memory_refs",
        "source_wiki_refs",
        "validation_refs",
        "usage_count",
        "helpful_count",
        "irrelevant_count",
        "harmful_count",
        "last_used_at",
        "retired_at",
        "created_at",
        "updated_at",
    }
    assert required <= set(skill)
    assert skill["content_sha256"]
    assert skill["bundle_tree_sha256"]
    rendered = stable_json(skill)
    assert rendered == stable_json(json.loads(rendered))
    assert "raw-value" not in rendered
    assert "SECRET_TOKEN" not in rendered


def test_registry_saves_and_lists_tenant_scoped_skill_metadata(tmp_path):
    registry = SkillMemoryRegistry(_db(tmp_path))
    registry.save(_skill(skill_id="skill-a"))
    registry.save(_skill(skill_id="skill-b", tenant_id="tenant-b", repo_id="repo-b"))

    assert registry.get("skill-a")["tenant_id"] == "tenant-a"
    assert [item["skill_id"] for item in registry.list(tenant_id="tenant-a")] == ["skill-a"]
    assert registry.list(tenant_id="tenant-a", scope="tenant") == []


def test_retrieval_hard_filters_run_before_ranking():
    query = build_skill_retrieval_query(
        raw_query="perfect lexical ci repair pytest failure",
        tenant_id="tenant-a",
        repo_id="repo-a",
        toolset="terminal",
        worker_role="worker",
        task_type="validation",
        feature_state={"skills_enabled": True},
    )
    valid = _skill(skill_id="valid", summary="ci repair pytest failure")
    invalid = [
        _skill(skill_id="wrong-tenant", tenant_id="tenant-b", summary="perfect lexical ci repair pytest failure"),
        _skill(skill_id="wrong-repo", repo_id="repo-b", summary="perfect lexical ci repair pytest failure"),
        _skill(skill_id="wrong-tool", toolset="browser", summary="perfect lexical ci repair pytest failure"),
        _skill(skill_id="wrong-role", worker_role="qa", summary="perfect lexical ci repair pytest failure"),
        _skill(skill_id="unsafe", safety_state="unsafe", summary="perfect lexical ci repair pytest failure"),
        _skill(skill_id="draft", approval_state="draft", summary="perfect lexical ci repair pytest failure"),
        _skill(skill_id="retired", retired_at=123.0, summary="perfect lexical ci repair pytest failure"),
    ]

    result = retrieve_skills([*invalid, valid], query, limit=10)

    assert result["status"] == "ok"
    assert [item["skill_id"] for item in result["skills"]] == ["valid"]
    assert result["audit"]["filtered_count"] == len(invalid)


def test_bounded_packets_are_role_specific_advisory_and_reference_only():
    query = build_skill_retrieval_query(
        raw_query="qa browser deploy ci repair",
        tenant_id="tenant-a",
        repo_id="repo-a",
        toolset="terminal",
        worker_role="worker",
        task_id="task-1",
        feature_state={"skills_enabled": True},
    )
    skills = [
        _skill(skill_id="worker-skill", worker_role="worker", summary="worker repair steps"),
        _skill(skill_id="qa-skill", worker_role="qa", summary="qa validation steps"),
        _skill(skill_id="browser-skill", worker_role="browser", toolset="browser", summary="browser smoke steps"),
        _skill(skill_id="deploy-skill", worker_role="deployment", summary="deployment rollout checks"),
        _skill(skill_id="planner-skill", worker_role="planner", summary="planner decomposition checks"),
        _skill(skill_id="supervisor-skill", worker_role="supervisor", summary="supervisor routing checks"),
    ]

    for role in ("supervisor", "planner", "worker", "qa", "browser", "deployment"):
        packet = build_bounded_skill_packet(
            query={**query, "worker_role": role, "toolset": "browser" if role == "browser" else "terminal"},
            skills=skills,
            worker_role=role,
            max_skills=1,
            max_token_estimate=220,
        )
        assert packet["status"] == "ok"
        assert packet["worker_role"] == role
        assert packet["authority"] == "advisory_only_no_override"
        assert "do not override" in packet["authority_guard"].casefold()
        assert len(packet["skills"]) <= 1
        rendered = stable_json(packet)
        assert "SECRET_TOKEN" not in rendered
        assert "raw-value" not in rendered
        assert "content" not in packet["skills"][0]
        assert packet["skills"][0]["source_refs"]


def test_disabled_feature_skips_search_and_packet_without_breaking_baseline_flags():
    query = build_skill_retrieval_query(
        raw_query="ci repair",
        tenant_id="tenant-a",
        repo_id="repo-a",
        feature_state={"skills_enabled": False},
    )

    search = retrieve_skills([_skill()], query)
    packet = build_bounded_skill_packet(query=query, skills=[_skill()], worker_role="worker")

    assert search["status"] == "disabled"
    assert search["skills"] == []
    assert search["baseline_memory_passthrough"] is True
    assert search["delegation_passthrough"] is True
    assert packet["status"] == "disabled"
    assert packet["skills"] == []
    assert packet["baseline_memory_passthrough"] is True
    assert packet["delegation_passthrough"] is True


def test_cross_tenant_private_blocked_and_global_requires_redacted_shareable_opt_in():
    private = _skill(skill_id="private", tenant_id="tenant-b", repo_id="repo-b", scope="tenant")
    global_unredacted = _skill(skill_id="global-unredacted", scope="global", tenant_id=None, repo_id=None, redacted=False, shareable=True)
    global_unapproved = _skill(skill_id="global-unapproved", scope="global", tenant_id=None, repo_id=None, redacted=True, shareable=True, approval_state="candidate")
    global_not_shareable = _skill(skill_id="global-not-shareable", scope="global", tenant_id=None, repo_id=None, redacted=True, shareable=False)
    global_ok = _skill(skill_id="global-ok", scope="global", tenant_id=None, repo_id=None, redacted=True, shareable=True)

    no_opt_in = build_skill_retrieval_query(
        raw_query="ci repair",
        tenant_id="tenant-a",
        repo_id="repo-a",
        toolset="terminal",
        worker_role="worker",
        feature_state={"skills_enabled": True, "tenant_global_skill_opt_in": False},
    )
    opted_in = {**no_opt_in, "feature_state": {"skills_enabled": True, "tenant_global_skill_opt_in": True}}

    assert retrieve_skills([private, global_ok], no_opt_in)["skills"] == []
    result = retrieve_skills(
        [private, global_unredacted, global_unapproved, global_not_shareable, global_ok],
        opted_in,
    )
    assert [item["skill_id"] for item in result["skills"]] == ["global-ok"]
