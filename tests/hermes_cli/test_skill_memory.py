import json
import os
from pathlib import Path
import subprocess
import sys

from hermes_state import SessionDB
from hermes_cli.skill_memory import (
    SkillClawAdapter,
    SkillMemoryRegistry,
    apply_skill_feedback,
    attach_skill_refs_to_runtime_packet,
    build_bounded_skill_packet,
    build_harmful_skill_candidate,
    build_skill_candidate_from_memory,
    build_skill_e2e_fixture,
    build_skill_feedback,
    build_skill_metadata,
    build_skill_retrieval_query,
    publish_skill_candidate,
    record_skill_feedback,
    retrieve_skills,
    stable_json,
    validate_skill_candidate_publication,
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


def test_feedback_records_contract_fields_and_updates_counts_without_raw_logs_or_secrets(tmp_path):
    registry = SkillMemoryRegistry(_db(tmp_path))
    skill = registry.save(_skill(skill_id="feedback-skill", helpful_count=1, usage_count=1))

    feedback = build_skill_feedback(
        tenant_id="tenant-a",
        repo_id="repo-a",
        task_id="task-1",
        session_id="session-1",
        skill_id=skill["skill_id"],
        skill_version=skill["version"],
        worker_role="worker",
        impact="helpful",
        evidence_refs=["cmd://pytest", "raw log SECRET_TOKEN=leak should be bounded"],
        validation_refs=["pytest://tests/hermes_cli/test_skill_memory.py"],
        reason="Used the skill; raw secret OPENAI_API_KEY=abc and a very long log " * 20,
    )
    stored = record_skill_feedback(registry, feedback)
    updated = apply_skill_feedback(registry, stored)
    for impact in ("irrelevant", "unknown"):
        extra = record_skill_feedback(
            registry,
            build_skill_feedback(
                tenant_id="tenant-a",
                repo_id="repo-a",
                task_id=f"task-{impact}",
                session_id=f"session-{impact}",
                skill_id=skill["skill_id"],
                skill_version=skill["version"],
                worker_role="worker",
                impact=impact,
                evidence_refs=[f"evidence://{impact}"],
                validation_refs=[f"validation://{impact}"],
                reason=f"{impact} feedback",
            ),
        )
        updated = apply_skill_feedback(registry, extra)

    required = {
        "feedback_id",
        "tenant_id",
        "repo_id",
        "task_id",
        "session_id",
        "skill_id",
        "skill_version",
        "worker_role",
        "impact",
        "evidence_refs",
        "validation_refs",
        "reason",
        "created_at",
    }
    assert required <= set(stored)
    assert updated["helpful_count"] == 2
    assert updated["irrelevant_count"] == 1
    assert updated["unknown_count"] == 1
    assert updated["usage_count"] == 4
    rendered = stable_json({"feedback": stored, "skill": updated})
    assert "OPENAI_API_KEY" not in rendered
    assert "SECRET_TOKEN" not in rendered
    assert len(stored["reason"]) <= 280


def test_skill_candidate_from_approved_memory_and_wiki_is_proposed_not_published():
    candidate = build_skill_candidate_from_memory(
        tenant_id="tenant-a",
        repo_id="repo-a",
        name="pytest repair",
        version="0.1.0",
        summary="Run focused pytest after patching CI failures.",
        source_memory_refs=[{"ref": "mem-approved", "approval_state": "approved", "summary": "bounded"}],
        source_wiki_refs=[{"ref": "wiki-approved", "approval_state": "approved", "claim": "bounded"}],
        toolset="terminal",
        worker_role="worker",
        validation_refs=[],
        approval_refs=[],
    )

    assert candidate["candidate_state"] == "proposed"
    assert candidate["can_publish"] is False
    assert candidate["approval_state"] == "candidate"
    assert candidate["source_memory_refs"] == ["mem-approved"]
    assert candidate["source_wiki_refs"] == ["wiki-approved"]
    rendered = stable_json(candidate)
    assert "raw_session" not in rendered
    assert "SECRET_TOKEN" not in rendered

    try:
        build_skill_candidate_from_memory(
            tenant_id="tenant-a",
            repo_id="repo-a",
            name="bad",
            version="0.1.0",
            summary="bad",
            source_memory_refs=[{"ref": "mem-draft", "approval_state": "draft"}],
        )
    except ValueError as exc:
        assert "approved memory/wiki refs" in str(exc)
    else:
        raise AssertionError("unapproved evidence should be rejected")


def test_skill_candidate_from_approved_runtime_failure_requires_publication_gates(tmp_path):
    registry = SkillMemoryRegistry(_db(tmp_path))
    candidate = registry.save_candidate(
        build_skill_candidate_from_memory(
            tenant_id="tenant-a",
            repo_id="repo-a",
            name="worker timeout recovery",
            version="0.1.0",
            summary="If the assigned worker times out, preserve evidence refs and request fallback validation.",
            source_candidate_refs=[
                {
                    "candidate_id": "curadv-runtime-timeout",
                    "status": "approved",
                    "kind": "recovery_hint",
                }
            ],
            toolset="terminal",
            worker_role="worker",
            validation_refs=["pytest://tests/hermes_cli/test_goal_allocator.py"],
        )
    )

    blocked = publish_skill_candidate(
        registry,
        candidate,
        judge_ref="",
        operator_approval_ref="",
    )

    assert candidate["candidate_state"] == "proposed"
    assert candidate["can_publish"] is False
    assert candidate["source_candidate_refs"] == ["curadv-runtime-timeout"]
    assert blocked["status"] == "blocked"
    assert "missing_judge_ref" in blocked["gate"]["errors"]
    assert "missing_operator_approval_ref" in blocked["gate"]["errors"]
    assert registry.get(candidate["skill_id"], tenant_id="tenant-a") is None


def test_skill_evolution_publish_packet_feedback_and_harmful_repair_loop(tmp_path):
    registry = SkillMemoryRegistry(_db(tmp_path))
    candidate = registry.save_candidate(
        build_skill_candidate_from_memory(
            tenant_id="tenant-a",
            repo_id="repo-a",
            name="runtime failure recovery",
            version="1.0.0",
            summary="Use bounded failure evidence, validate worker output, and avoid accepting empty completions.",
            source_memory_refs=[{"ref": "mem-approved-runtime", "approval_state": "approved"}],
            source_wiki_refs=[{"ref": "wiki-approved-runtime", "approval_state": "approved"}],
            source_candidate_refs=[{"candidate_id": "curadv-empty-output", "status": "approved"}],
            toolset="terminal",
            worker_role="worker",
            validation_refs=["pytest://tests/test_curator_runtime.py"],
            approval_refs=["approval://prior-design-review"],
        )
    )

    gate = validate_skill_candidate_publication(
        candidate,
        judge_ref="judge://learning_judge/approved",
        operator_approval_ref="approval://operator/skill-runtime-failure",
    )
    published = publish_skill_candidate(
        registry,
        candidate,
        judge_ref="judge://learning_judge/approved",
        operator_approval_ref="approval://operator/skill-runtime-failure",
        published_by="operator-1",
    )

    assert gate["eligible_for_publication"] is True
    assert published["status"] == "published"
    skill = published["skill"]
    assert skill["approval_state"] == "approved"
    assert skill["safety_state"] == "safe"
    assert skill["authority"] == "advisory_only_no_override"
    assert "approval://operator/skill-runtime-failure" in skill["approval_refs"]
    assert "curadv-empty-output" in skill["source_candidate_refs"]
    assert registry.get_candidate(candidate["candidate_id"], tenant_id="tenant-a")["candidate_state"] == "published"

    query = build_skill_retrieval_query(
        raw_query="worker empty completion runtime failure",
        tenant_id="tenant-a",
        repo_id="repo-a",
        task_id="task-skill-evolve",
        toolset="terminal",
        worker_role="worker",
        feature_state={"skills_enabled": True},
    )
    packet = build_bounded_skill_packet(query=query, skills=registry, worker_role="worker")
    assert packet["status"] == "ok"
    assert packet["skills"][0]["skill_id"] == skill["skill_id"]
    assert "content" not in packet["skills"][0]

    feedback = record_skill_feedback(
        registry,
        build_skill_feedback(
            tenant_id="tenant-a",
            repo_id="repo-a",
            task_id="task-skill-evolve",
            session_id="session-skill-evolve",
            skill_id=skill["skill_id"],
            skill_version=skill["version"],
            worker_role="worker",
            impact="harmful",
            evidence_refs=["worker://failed-validation"],
            validation_refs=["pytest://failed"],
            reason="The skill was too broad and caused validation failure.",
        ),
    )
    updated = apply_skill_feedback(registry, feedback)
    repair_candidates = [
        item
        for item in registry.list_candidates(tenant_id="tenant-a")
        if item.get("source_feedback_refs") == [feedback["feedback_id"]]
    ]

    assert updated["retrieval_demoted"] is True
    assert retrieve_skills(registry, query)["skills"] == []
    assert repair_candidates
    assert repair_candidates[0]["candidate_kind"] in {"repair", "retire"}
    rendered = stable_json({"skill": skill, "packet": packet, "feedback": feedback, "repair": repair_candidates[0]})
    assert "SECRET_TOKEN" not in rendered
    assert "raw_session" not in rendered


def test_harmful_feedback_demotes_retrieval_and_creates_repair_candidate(tmp_path):
    registry = SkillMemoryRegistry(_db(tmp_path))
    registry.save(_skill(skill_id="harmful-skill", helpful_count=0, harmful_count=0, usage_count=1))
    query = build_skill_retrieval_query(
        raw_query="ci repair pytest",
        tenant_id="tenant-a",
        repo_id="repo-a",
        toolset="terminal",
        worker_role="worker",
        feature_state={"skills_enabled": True},
    )
    assert retrieve_skills(registry, query)["skills"][0]["skill_id"] == "harmful-skill"

    feedback = record_skill_feedback(
        registry,
        build_skill_feedback(
            tenant_id="tenant-a",
            repo_id="repo-a",
            task_id="task-2",
            session_id="session-2",
            skill_id="harmful-skill",
            skill_version="1.0.0",
            worker_role="worker",
            impact="harmful",
            evidence_refs=["cmd://failed-validation"],
            validation_refs=["pytest://failed"],
            reason="Skill caused validation failure.",
        ),
    )
    updated = apply_skill_feedback(registry, feedback)

    assert updated["harmful_count"] == 1
    assert updated["retrieval_demoted"] is True
    assert retrieve_skills(registry, query)["skills"] == []
    candidates = registry.list_candidates(tenant_id="tenant-a")
    assert candidates[0]["candidate_kind"] in {"repair", "retire"}
    assert candidates[0]["source_feedback_refs"] == [feedback["feedback_id"]]


def test_skillclaw_local_bundle_roundtrip_validation_and_shared_sync_disabled(tmp_path):
    adapter = SkillClawAdapter(tmp_path / "skillclaw")
    bundle = adapter.write_bundle(
        skill=_skill(skill_id="bundle-skill"),
        files={"SKILL.md": "# Skill\nUse bounded pytest guidance.\n"},
        validation_refs=["pytest://tests/hermes_cli/test_skill_memory.py"],
    )
    loaded = adapter.read_bundle(bundle["bundle_id"])
    validation = adapter.ingest_validation_result(
        bundle["bundle_id"],
        status="passed",
        validation_refs=["pytest://tests/hermes_cli/test_skill_memory.py"],
    )
    staged = adapter.stage_candidate(
        loaded,
        tenant_id="tenant-a",
        global_candidate=True,
    )

    assert loaded["content_sha256"] == bundle["content_sha256"]
    assert loaded["bundle_tree_sha256"] == bundle["bundle_tree_sha256"]
    assert validation["status"] == "passed"
    assert staged["stage"] == "global_candidate"
    assert adapter.sync_shared()["status"] == "disabled"


def test_e2e_fixture_covers_packet_validation_feedback_and_candidate_evolution(tmp_path):
    fixture = build_skill_e2e_fixture(
        registry=SkillMemoryRegistry(_db(tmp_path)),
        tenant_id="tenant-a",
        repo_id="repo-a",
        task_id="task-e2e",
        session_id="session-e2e",
        raw_query="fix pytest failure",
    )

    rendered = stable_json(fixture)
    assert fixture["retrieval"]["status"] == "ok"
    assert fixture["worker_packet"]["skill_packet_id"] == fixture["skill_packet"]["packet_id"]
    assert fixture["feedback"]["impact"] == "helpful"
    assert fixture["candidate"]["candidate_state"] == "proposed"
    assert "bounded procedure" not in rendered
    assert "SECRET_TOKEN" not in rendered


def test_runtime_packets_receive_only_skill_refs_not_raw_skill_content():
    packet = {
        "id": "delegate-1",
        "objective": "fix tests",
        "skill_content": "raw secret should be removed SECRET_TOKEN=leak",
    }
    skill_packet = {
        "packet_id": "skill-packet-1",
        "skills": [
            {
                "skill_id": "skill-a",
                "version": "1.0.0",
                "content": "raw body",
                "summary": "bounded",
                "content_sha256": "abc",
                "bundle_tree_sha256": "def",
            }
        ],
    }

    attached = attach_skill_refs_to_runtime_packet(packet, skill_packet)

    assert attached["skill_packet_id"] == "skill-packet-1"
    assert attached["skill_refs"] == [
        {
            "skill_id": "skill-a",
            "version": "1.0.0",
            "content_sha256": "abc",
            "bundle_tree_sha256": "def",
        }
    ]
    rendered = stable_json(attached)
    assert "raw body" not in rendered
    assert "SECRET_TOKEN" not in rendered


def test_skills_cli_runtime_feedback_and_candidates_return_stable_json(tmp_path):
    hermes_home = tmp_path / "home"
    hermes_home.mkdir()
    registry = SkillMemoryRegistry(SessionDB(db_path=hermes_home / "state.db"))
    skill = registry.save(_skill(skill_id="cli-skill"))
    candidate = registry.save_candidate(
        build_skill_candidate_from_memory(
            tenant_id="tenant-a",
            repo_id="repo-a",
            name="cli published skill",
            version="1.0.0",
            summary="CLI publication skill.",
            source_memory_refs=[{"ref": "mem-cli", "approval_state": "approved"}],
            validation_refs=["pytest://cli"],
        )
    )

    env = {**os.environ, "PYTHONPATH": str(Path.cwd()), "HERMES_HOME": str(hermes_home)}
    search = subprocess.run(
        [
            sys.executable,
            "-m",
            "hermes_cli.main",
            "skills",
            "runtime",
            "search",
            "--tenant-id",
            "tenant-a",
            "--repo-id",
            "repo-a",
            "--query",
            "ci repair pytest",
            "--worker-role",
            "worker",
            "--toolset",
            "terminal",
            "--json",
        ],
        check=True,
        env=env,
        text=True,
        capture_output=True,
    )
    feedback = subprocess.run(
        [
            sys.executable,
            "-m",
            "hermes_cli.main",
            "skills",
            "feedback",
            "--tenant-id",
            "tenant-a",
            "--repo-id",
            "repo-a",
            "--task-id",
            "task-cli",
            "--skill-id",
            skill["skill_id"],
            "--skill-version",
            skill["version"],
            "--impact",
            "unknown",
            "--json",
        ],
        check=True,
        env=env,
        text=True,
        capture_output=True,
    )
    candidates = subprocess.run(
        [
            sys.executable,
            "-m",
            "hermes_cli.main",
            "skills",
            "candidates",
            "--tenant-id",
            "tenant-a",
            "--json",
        ],
        check=True,
        env=env,
        text=True,
        capture_output=True,
    )
    publish = subprocess.run(
        [
            sys.executable,
            "-m",
            "hermes_cli.main",
            "skills",
            "evolve-publish",
            "--tenant-id",
            "tenant-a",
            "--candidate-id",
            candidate["candidate_id"],
            "--judge-ref",
            "judge://cli-approved",
            "--operator-approval-ref",
            "approval://cli-operator",
            "--json",
        ],
        check=True,
        env=env,
        text=True,
        capture_output=True,
    )

    search_json = json.loads(search.stdout)
    feedback_json = json.loads(feedback.stdout)
    candidates_json = json.loads(candidates.stdout)
    publish_json = json.loads(publish.stdout)
    assert search_json["skills"][0]["skill_id"] == "cli-skill"
    assert feedback_json["status"] == "recorded"
    assert candidates_json["status"] == "ok"
    assert publish_json["status"] == "published"
    assert publish_json["skill"]["approval_state"] == "approved"
    assert "authority" not in search_json or search_json["baseline_memory_passthrough"] is True
