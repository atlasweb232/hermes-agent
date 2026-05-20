import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from hermes_cli.memory_dreaming import (
    DreamingConfig,
    DreamingProposal,
    build_dreaming_input_packet,
    approve_dreaming_proposal,
    build_dreaming_dashboard_dto,
    get_dreaming_proposal,
    judge_dreaming_proposal,
    list_dreaming_proposals,
    parse_dreaming_proposal_output,
    reject_dreaming_proposal,
    resolve_dreaming_role,
    run_dreaming,
    validate_dreaming_proposal_details,
    validate_dreaming_proposal,
    PHASE18_PROPOSAL_TYPES,
)
from hermes_cli.memory_wiki import compile_memory_wiki
from hermes_state import SessionDB


def _make_db(tmp_path: Path) -> SessionDB:
    return SessionDB(db_path=tmp_path / "state.db")


def _seed_wiki_claim(db: SessionDB) -> str:
    db.upsert_meta_candidate(
        candidate_id="metacand_wiki",
        kind="playbook",
        claim="For Claude Code routing failures, preserve direct CLI fallback evidence",
        evidence_json={
            "record_id": "memrec_wiki",
            "evidence_uri": "artifact://claude-routing",
            "tool": "claude-code",
            "successful_action": "use direct claude --model sonnet -p after wrapper failure",
        },
        score=0.91,
        status="approved",
        tenant_id="atlas",
        repo_id="hermes-agent",
    )
    result = compile_memory_wiki(db, tenant_id="atlas", repo_id="hermes-agent")
    return result.claims[0].id


def _proposal_json(**overrides):
    payload = {
        "proposal_type": "playbook",
        "summary": "Create a bounded Claude routing recovery checklist",
        "rationale": "The wiki claim contains approved evidence for a repeated routing failure.",
        "evidence_refs": ["wikiclaim_1"],
        "scope": {"tenant_id": "atlas", "repo_id": "hermes-agent", "cross_tenant_shareable": False},
        "risk": "low",
        "trigger": "manual",
        "requested_action": "Draft proposal-only checklist for operator review.",
        "runtime_effect": False,
    }
    payload.update(overrides)
    return json.dumps(payload)


def _phase18_proposal_json(**overrides):
    payload = {
        "proposal_type": "skill_candidate",
        "summary": "Create a bounded skill for repeated release triage",
        "rationale": "Approved redacted evidence shows the same triage steps recurring.",
        "evidence_refs": ["packet_1"],
        "scope": {"tenant_id": "atlas", "repo_id": "hermes-agent", "visibility": "local"},
        "risk": "low",
        "trigger": "manual",
        "requested_action": "Create a proposal-only skill candidate for review.",
        "runtime_effect": False,
        "affected_feature_ids": ["US15"],
        "conversion_target": "skill_candidate",
        "expected_benefit": "Reduce repeated manual release triage.",
        "forbidden_direct_actions": ["publish_skill", "edit_repo"],
        "suggested_validation": ["Run skill validation fixture before publish."],
        "role_metadata": {"role": "local_dreaming", "tenant_id": "atlas", "repo_id": "hermes-agent"},
        "evidence_packets": [{"packet_id": "packet_1", "source_ref": "wikiclaim_1"}],
        "judge_state": {"status": "pending"},
        "operator_state": {"status": "pending"},
    }
    payload.update(overrides)
    return json.dumps(payload)


def test_parse_dreaming_proposal_output_accepts_strict_schema():
    proposal = parse_dreaming_proposal_output(_proposal_json())

    assert proposal.proposal_type == "playbook"
    assert proposal.trigger == "manual"
    assert proposal.runtime_effect is False
    assert proposal.id.startswith("dream_")


def test_phase18_proposal_schema_covers_required_types_and_fields():
    required = {
        "skill_candidate",
        "skill_repair",
        "test_gap",
        "ci_cd_hardening",
        "memory_wiki_update",
        "routing_improvement",
        "allocator_policy_candidate",
        "observability_gap",
        "tenant_onboarding_improvement",
        "toolset_recommendation",
        "cost_optimization",
        "training_corpus_candidate",
        "architecture_review_item",
    }
    assert required <= PHASE18_PROPOSAL_TYPES

    for proposal_type in required:
        proposal = parse_dreaming_proposal_output(
            _phase18_proposal_json(proposal_type=proposal_type, conversion_target=proposal_type)
        )
        data = proposal.to_dict()
        for field in (
            "proposal_type",
            "affected_feature_ids",
            "conversion_target",
            "expected_benefit",
            "forbidden_direct_actions",
            "suggested_validation",
            "role_metadata",
            "evidence_packets",
            "judge_state",
            "operator_state",
        ):
            assert field in data
        assert proposal.runtime_effect is False


@pytest.mark.parametrize(
    "payload,error",
    [
        ("not-json", "JSON object"),
        ({"proposal_type": "playbook"}, "missing proposal fields"),
        (_proposal_json(extra="nope"), "unexpected proposal fields"),
        (_proposal_json(proposal_type="memory"), "invalid proposal_type"),
        (_proposal_json(risk="urgent"), "invalid risk"),
        (_proposal_json(evidence_refs="wikiclaim_1"), "evidence_refs must be a list"),
        (_proposal_json(runtime_effect="false"), "runtime_effect must be boolean"),
    ],
)
def test_parse_dreaming_proposal_output_rejects_invalid_schema(payload, error):
    raw = payload if isinstance(payload, str) else json.dumps(payload)

    with pytest.raises(Exception) as exc:
        parse_dreaming_proposal_output(raw)

    assert error in str(exc.value)


def test_run_dreaming_generates_proposal_from_wiki_claim_with_manual_trigger(tmp_path):
    db = _make_db(tmp_path)
    try:
        claim_id = _seed_wiki_claim(db)

        result = run_dreaming(
            db,
            tenant_id="atlas",
            repo_id="hermes-agent",
            config={"supervisor": {"dreaming": {"enabled": True, "allow_llm": False}}},
            trigger="manual",
        )

        assert result.status == "completed"
        assert result.proposals_created == 1
        proposal = result.proposals[0]
        assert proposal.trigger == "manual"
        assert proposal.evidence_refs == [claim_id]
        assert proposal.status == "proposed"
        assert list_dreaming_proposals(db, tenant_id="atlas", repo_id="hermes-agent")[0].id == proposal.id
    finally:
        db.close()


def test_dreaming_proposals_are_not_retrieved_by_memory_injection_or_wiki_export(tmp_path):
    db = _make_db(tmp_path)
    try:
        _seed_wiki_claim(db)
        run_dreaming(
            db,
            tenant_id="atlas",
            repo_id="hermes-agent",
            config={"supervisor": {"dreaming": {"enabled": True, "allow_llm": False}}},
        )

        rows = db.list_meta_candidates(status="proposed", tenant_id="atlas", repo_id="hermes-agent")
        assert all(not str(row["id"]).startswith("dream_") for row in rows)

        from hermes_cli.memory_wiki import export_training_corpus
        from hermes_cli.supervisor_memory import retrieve_learning_context

        exported = export_training_corpus(db, tenant_id="atlas", repo_id="hermes-agent")
        assert all(record.source_wiki_claim_id.startswith("wikiclaim_") for record in exported.records)
        injected = retrieve_learning_context(
            db,
            query="bounded Claude routing recovery checklist",
            tenant_id="atlas",
            repo_id="hermes-agent",
            config={"supervisor": {"learning": {"injection": {"enabled": True}}}},
        )
        assert "dream_" not in json.dumps(injected)
    finally:
        db.close()


def test_dreaming_validator_rejects_unsafe_or_direct_effect_proposals():
    cfg = DreamingConfig(allow_cross_tenant=False, allow_policy_proposals=False)
    proposal = DreamingProposal(
        id="dream_bad",
        proposal_type="policy",
        summary="Export training and enforce rm -rf cleanup with token=sk-thisisunsafe1234567890",
        rationale="Write the wiki directly and queue a goal.",
        evidence_refs=["wikiclaim_1"],
        scope={"tenant_id": "atlas", "repo_id": "hermes-agent", "cross_tenant_shareable": True},
        risk="high",
        trigger="manual",
        requested_action="Apply config and inject into prompt.",
        runtime_effect=True,
    )

    errors = validate_dreaming_proposal(
        proposal,
        config=cfg,
        known_evidence_refs={"wikiclaim_1"},
    )

    assert "runtime_effect_not_allowed" in errors
    assert "policy_proposals_disabled" in errors
    assert "cross_tenant_sharing_disabled" in errors
    assert "secret_pattern_detected" in errors
    assert "destructive_command_detected" in errors
    assert "forbidden_direct_runtime_effect" in errors


def test_dreaming_validator_rejects_unknown_or_missing_evidence_refs():
    proposal = parse_dreaming_proposal_output(_proposal_json(evidence_refs=["missing"]))
    assert "unknown_evidence_refs" in validate_dreaming_proposal(
        proposal,
        config=DreamingConfig(),
        known_evidence_refs={"wikiclaim_1"},
    )
    proposal.evidence_refs = []
    assert "missing_evidence_refs" in validate_dreaming_proposal(proposal, config=DreamingConfig())


def test_local_dreaming_input_is_tenant_repo_scoped_and_cannot_publish_globally():
    role = resolve_dreaming_role(mode="local", tenant_id="atlas", repo_id="hermes-agent")
    records = [
        {
            "id": "local_ok",
            "tenant_id": "atlas",
            "repo_id": "hermes-agent",
            "content": "approved local repair summary",
            "approved": True,
            "redacted": True,
            "shareable": False,
        },
        {
            "id": "wrong_tenant",
            "tenant_id": "other",
            "repo_id": "hermes-agent",
            "content": "must not cross tenant",
            "approved": True,
            "redacted": True,
        },
    ]

    packet = build_dreaming_input_packet(role, records)

    assert [item.packet_id for item in packet.evidence_packets] == ["local_ok"]
    assert packet.role_metadata["tenant_id"] == "atlas"
    assert packet.role_metadata["repo_id"] == "hermes-agent"
    assert packet.role_metadata["can_publish_global"] is False

    proposal = parse_dreaming_proposal_output(
        _phase18_proposal_json(
            evidence_refs=["local_ok"],
            role_metadata=packet.role_metadata,
            scope={"tenant_id": "atlas", "repo_id": "hermes-agent", "visibility": "global"},
            conversion_target="global_memory_wiki",
            requested_action="Publish globally after review.",
        )
    )
    details = validate_dreaming_proposal_details(proposal, known_evidence_refs={"local_ok"})
    assert "local_cannot_publish_global" in details.error_codes


def test_global_dreaming_input_uses_only_redacted_approved_shareable_global_evidence():
    role = resolve_dreaming_role(mode="global")
    records = [
        {
            "id": "global_ok",
            "scope": "global",
            "content": "redacted approved shareable global repair pattern",
            "approved": True,
            "redacted": True,
            "shareable": True,
        },
        {"id": "private", "scope": "tenant", "content": "tenant private", "approved": True, "redacted": True, "shareable": True},
        {"id": "raw", "scope": "global", "content": "raw transcript", "approved": True, "redacted": False, "shareable": True},
        {"id": "unapproved", "scope": "global", "content": "draft", "approved": False, "redacted": True, "shareable": True},
        {"id": "not_shareable", "scope": "global", "content": "not shareable", "approved": True, "redacted": True, "shareable": False},
    ]

    packet = build_dreaming_input_packet(role, records)

    assert [item.packet_id for item in packet.evidence_packets] == ["global_ok"]
    assert packet.role_metadata["role"] == "global_dreaming"
    assert packet.role_metadata["input_policy"] == "redacted_approved_shareable_global_only"


@pytest.mark.parametrize(
    "proposal_type,conversion_target",
    [
        ("skill_candidate", "skill_candidate"),
        ("skill_repair", "skill_candidate"),
        ("ci_cd_hardening", "ci_cd_task"),
        ("test_gap", "test_backlog_item"),
        ("routing_improvement", "routing_advisory"),
        ("cost_optimization", "cost_review_item"),
        ("training_corpus_candidate", "training_corpus_candidate"),
        ("architecture_review_item", "architecture_review_item"),
    ],
)
def test_phase18_validators_accept_safe_domain_proposals(proposal_type, conversion_target):
    proposal = parse_dreaming_proposal_output(
        _phase18_proposal_json(proposal_type=proposal_type, conversion_target=conversion_target)
    )

    details = validate_dreaming_proposal_details(proposal, known_evidence_refs={"packet_1"})

    assert details.accepted is True
    assert details.error_codes == []
    assert details.proposal_type == proposal_type


def test_phase18_validators_reject_direct_mutation_and_unsafe_evidence_content():
    proposal = parse_dreaming_proposal_output(
        _phase18_proposal_json(
            proposal_type="ci_cd_hardening",
            conversion_target="ci_cd_task",
            requested_action="Edit repos, deploy code, change config, and export training data directly.",
            evidence_packets=[
                {
                    "packet_id": "packet_1",
                    "source_ref": "wikiclaim_1",
                    "content_summary": "raw transcript includes token=sk-thisisunsafe1234567890",
                }
            ],
        )
    )

    details = validate_dreaming_proposal_details(proposal, known_evidence_refs={"packet_1"})

    assert details.accepted is False
    assert "forbidden_direct_runtime_effect" in details.error_codes
    assert "secret_pattern_detected" in details.error_codes
    assert "raw_transcript_or_unbounded_log_detected" in details.error_codes


def test_dreaming_dashboard_dto_exposes_review_fields():
    proposal = parse_dreaming_proposal_output(_phase18_proposal_json())
    dto = build_dreaming_dashboard_dto(proposal)

    assert dto["id"] == proposal.id
    assert dto["proposal_type"] == "skill_candidate"
    assert dto["evidence_refs"] == ["packet_1"]
    assert dto["expected_benefit"]
    assert dto["judge_state"]["status"] == "pending"
    assert dto["operator_state"]["status"] == "pending"


def test_dreaming_judge_operator_conversion_requires_both_gates(tmp_path):
    db = _make_db(tmp_path)
    try:
        _seed_wiki_claim(db)
        result = run_dreaming(
            db,
            tenant_id="atlas",
            repo_id="hermes-agent",
            config={"supervisor": {"dreaming": {"enabled": True, "allow_llm": False}}},
        )
        proposal_id = result.proposals[0].id

        with pytest.raises(ValueError):
            approve_dreaming_proposal(db, proposal_id=proposal_id, convert_candidate=True)

        judged = judge_dreaming_proposal(
            db,
            proposal_id=proposal_id,
            decision="approve",
            confidence=0.9,
            rationale="low-risk proposal",
        )
        assert judged.status == "judged"

        approved = approve_dreaming_proposal(
            db,
            proposal_id=proposal_id,
            operator="rakib",
            convert_candidate=True,
        )
        assert approved.status == "converted"
        assert approved.converted_candidate_id is not None
        candidate = db.get_meta_candidate(approved.converted_candidate_id)
        assert candidate["kind"] == "dreaming_playbook"
        assert candidate["status"] == "proposed"
    finally:
        db.close()


def test_dreaming_reject_marks_proposal_rejected(tmp_path):
    db = _make_db(tmp_path)
    try:
        _seed_wiki_claim(db)
        result = run_dreaming(
            db,
            tenant_id="atlas",
            repo_id="hermes-agent",
            config={"supervisor": {"dreaming": {"enabled": True, "allow_llm": False}}},
        )
        rejected = reject_dreaming_proposal(db, proposal_id=result.proposals[0].id, reason="too broad")
        assert rejected.status == "rejected"
        assert get_dreaming_proposal(db, result.proposals[0].id).operator_decision["reason"] == "too broad"
    finally:
        db.close()


def test_dreaming_cli_run_status_and_conversion_json_smoke(tmp_path, monkeypatch, capsys):
    home = tmp_path / ".hermes"
    monkeypatch.setenv("HERMES_HOME", str(home))
    import hermes_state

    monkeypatch.setattr(hermes_state, "DEFAULT_DB_PATH", home / "state.db")
    db = SessionDB()
    try:
        _seed_wiki_claim(db)
    finally:
        db.close()

    from hermes_cli import main as hermes_main

    run_argv = [
        "hermes",
        "memory",
        "dream",
        "run",
        "--tenant-id",
        "atlas",
        "--repo-id",
        "hermes-agent",
        "--force",
        "--json",
    ]
    with patch.object(sys, "argv", run_argv):
        hermes_main.main()
    run_data = json.loads(capsys.readouterr().out)
    proposal_id = run_data["proposals"][0]["id"]

    with patch.object(sys, "argv", ["hermes", "memory", "dream", "status", "--json"]):
        hermes_main.main()
    status_data = json.loads(capsys.readouterr().out)
    assert status_data[0]["id"] == proposal_id

    with patch.object(
        sys,
        "argv",
        ["hermes", "memory", "dream", "judge", proposal_id, "--decision", "approve", "--json"],
    ):
        hermes_main.main()
    assert json.loads(capsys.readouterr().out)["status"] == "judged"

    with patch.object(
        sys,
        "argv",
        ["hermes", "memory", "dream", "approve", proposal_id, "--convert-candidate", "--json"],
    ):
        hermes_main.main()
    assert json.loads(capsys.readouterr().out)["status"] == "converted"


def test_learning_sidecar_skips_dreaming_by_default(tmp_path):
    from hermes_cli.supervisor_memory import (
        CandidateHousekeepingResult,
        LearningMonitorResult,
        LearningPolicyResult,
        LearningRollupResult,
        run_learning_sidecar,
    )

    calls = {"dreaming": 0}

    def fake_dreaming(*args, **kwargs):
        calls["dreaming"] += 1
        return {"status": "should_not_run"}

    result = run_learning_sidecar(
        lambda: _make_db(tmp_path),
        config={"supervisor": {"dreaming": {"enabled": False}}},
        once=True,
        rollup_fn=lambda *a, **k: LearningRollupResult("r", "completed", 0, 0, 0, ""),
        monitor_fn=lambda *a, **k: LearningMonitorResult("healthy", 0, 0, 0, 0, 0, 0),
        reconcile_fn=lambda *a, **k: LearningPolicyResult("p", "completed"),
        housekeeping_fn=lambda *a, **k: CandidateHousekeepingResult("completed", 0, 0, 0, False),
        dreaming_fn=fake_dreaming,
    )

    assert calls["dreaming"] == 0
    assert result.last_tick.dreaming["status"] == "skipped"
    assert result.last_tick.dreaming["reason"] == "disabled"


def test_learning_sidecar_runs_dreaming_when_enabled_and_due_without_blocking(tmp_path):
    from hermes_cli.supervisor_memory import (
        CandidateHousekeepingResult,
        LearningMonitorResult,
        LearningPolicyResult,
        LearningRollupResult,
        run_learning_sidecar,
    )

    class FakeDream:
        def to_dict(self):
            return {"status": "completed", "trigger": "sidecar_interval", "proposals_created": 1}

    def fake_dreaming(*args, **kwargs):
        assert kwargs["trigger"] == "sidecar_interval"
        assert kwargs["interval_due_at"] is not None
        return FakeDream()

    result = run_learning_sidecar(
        lambda: _make_db(tmp_path),
        config={"supervisor": {"dreaming": {"enabled": True, "interval_seconds": 3600}}},
        once=True,
        rollup_fn=lambda *a, **k: LearningRollupResult("r", "completed", 0, 0, 0, ""),
        monitor_fn=lambda *a, **k: LearningMonitorResult("healthy", 0, 0, 0, 0, 0, 0),
        reconcile_fn=lambda *a, **k: LearningPolicyResult("p", "completed"),
        housekeeping_fn=lambda *a, **k: CandidateHousekeepingResult("completed", 0, 0, 0, False),
        dreaming_fn=fake_dreaming,
    )

    assert result.status == "completed"
    assert result.last_tick.rollup["status"] == "completed"
    assert result.last_tick.dreaming["status"] == "completed"


def test_learning_sidecar_reports_dreaming_error_but_keeps_other_blocks(tmp_path):
    from hermes_cli.supervisor_memory import (
        CandidateHousekeepingResult,
        LearningMonitorResult,
        LearningPolicyResult,
        LearningRollupResult,
        run_learning_sidecar,
    )

    def failing_dreaming(*args, **kwargs):
        raise RuntimeError("dream failed")

    result = run_learning_sidecar(
        lambda: _make_db(tmp_path),
        config={"supervisor": {"dreaming": {"enabled": True}}},
        once=True,
        rollup_fn=lambda *a, **k: LearningRollupResult("r", "completed", 0, 0, 0, ""),
        monitor_fn=lambda *a, **k: LearningMonitorResult("healthy", 0, 0, 0, 0, 0, 0),
        reconcile_fn=lambda *a, **k: LearningPolicyResult("p", "completed"),
        housekeeping_fn=lambda *a, **k: CandidateHousekeepingResult("completed", 0, 0, 0, False),
        dreaming_fn=failing_dreaming,
    )

    assert result.status == "completed_with_errors"
    assert result.last_tick.rollup["status"] == "completed"
    assert result.last_tick.dreaming["status"] == "error"
    assert "dreaming: dream failed" in result.errors
