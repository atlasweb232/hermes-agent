"""Tests for the bounded DGM-H experiment lane."""

from __future__ import annotations

import json
import sys
from unittest.mock import patch

from hermes_cli.dgm_h import (
    create_dgm_variant,
    evolve_dgm_variants,
    get_tool_profile_tools,
    record_dgm_evaluation,
    select_dgm_parents,
)
from hermes_state import SessionDB


def test_tool_profile_lists_exa_browser_use_and_tinyfish(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / ".hermes"))

    result = get_tool_profile_tools("research_browser_eval")
    names = {tool["name"] for tool in result.tools}

    assert names == {"exa.search", "browser_use.run", "tinyfish.run"}
    assert all("allowed_profiles" in tool for tool in result.tools)


def test_create_and_evaluate_variant_creates_meta_candidate(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    monkeypatch.setenv("HERMES_HOME", str(home))
    db = SessionDB(db_path=home / "state.db")
    try:
        variant = create_dgm_variant(
            db,
            kind="validation_recipe",
            body="Use Tinyfish to smoke-test OAuth callback pages",
            tenant_id="atlas",
            repo_id="atlas-email-flutter",
            tool_profile="browser_eval",
        )
        evaluation = record_dgm_evaluation(
            db,
            variant_id=variant.variant_id,
            score=0.91,
            task_set="oauth-browser",
            metrics={"passed": 2, "failed": 0},
            artifact_uri="artifact://eval/oauth-browser.json",
            create_candidate=True,
        )

        stored = db.get_dgm_variant(variant.variant_id)
        assert stored["status"] == "evaluated"
        assert stored["score"] == 0.91
        assert evaluation.meta_candidate_id == f"metacand_{variant.variant_id}"
        candidate = db.get_meta_candidate(evaluation.meta_candidate_id)
        assert candidate["status"] == "proposed"
        assert candidate["evidence_json"]["variant_id"] == variant.variant_id
    finally:
        db.close()


def test_evolve_selects_parent_and_creates_child_with_dry_evaluation(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    monkeypatch.setenv("HERMES_HOME", str(home))
    db = SessionDB(db_path=home / "state.db")
    try:
        low = create_dgm_variant(
            db,
            kind="validation_recipe",
            body="Low scoring parent",
            tenant_id="atlas",
            repo_id="atlas-email-flutter",
        )
        high = create_dgm_variant(
            db,
            kind="validation_recipe",
            body="High scoring parent",
            tenant_id="atlas",
            repo_id="atlas-email-flutter",
        )
        record_dgm_evaluation(db, variant_id=low.variant_id, score=0.2)
        record_dgm_evaluation(db, variant_id=high.variant_id, score=0.9)

        parents = select_dgm_parents(
            db,
            tenant_id="atlas",
            repo_id="atlas-email-flutter",
            limit=1,
        )
        assert parents[0]["id"] == high.variant_id

        result = evolve_dgm_variants(
            db,
            objective="improve OAuth browser validation",
            tenant_id="atlas",
            repo_id="atlas-email-flutter",
            kind="validation_recipe",
            children=1,
            tool_profile="browser_eval",
            dry_score=0.6,
        )

        assert result.parent_ids == [high.variant_id]
        assert len(result.child_ids) == 1
        child = db.get_dgm_variant(result.child_ids[0])
        assert child["parent_id"] == high.variant_id
        assert child["metadata_json"]["evolution_role"] == "child"
        assert child["metadata_json"]["objective"] == "improve OAuth browser validation"
        evaluations = db.list_dgm_evaluations(variant_id=child["id"])
        assert evaluations[0]["status"] == "dry_evaluated"
        assert evaluations[0]["metrics_json"]["dry_run"] is True
    finally:
        db.close()


def test_evolve_creates_seed_when_archive_empty(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    monkeypatch.setenv("HERMES_HOME", str(home))
    db = SessionDB(db_path=home / "state.db")
    try:
        result = evolve_dgm_variants(
            db,
            objective="seed browser research validation",
            tenant_id="atlas",
            repo_id="atlas-email-flutter",
            children=1,
            dry_score=0.5,
        )

        assert len(result.parent_ids) == 1
        assert len(result.child_ids) == 1
        seed = db.get_dgm_variant(result.parent_ids[0])
        assert seed["metadata_json"]["evolution_role"] == "seed"
        child = db.get_dgm_variant(result.child_ids[0])
        assert child["parent_id"] == seed["id"]
    finally:
        db.close()


def test_cli_dgm_create_and_evaluate_smoke(tmp_path, monkeypatch, capsys):
    home = tmp_path / ".hermes"
    monkeypatch.setenv("HERMES_HOME", str(home))

    from hermes_cli import main as hermes_main

    create_argv = [
        "hermes",
        "dgm",
        "create",
        "--tenant-id",
        "atlas",
        "--repo-id",
        "atlas-email-flutter",
        "--kind",
        "routing_hint",
        "--body",
        "Route OAuth browser failures to browser validation worker",
        "--tool-profile",
        "research_browser_eval",
        "--json",
    ]
    with patch.object(sys, "argv", create_argv):
        hermes_main.main()
    created = json.loads(capsys.readouterr().out)
    assert created["status"] == "proposed"
    assert created["tool_profile"] == "research_browser_eval"

    eval_argv = [
        "hermes",
        "dgm",
        "evaluate",
        created["variant_id"],
        "--score",
        "0.77",
        "--metrics-json",
        '{"passed": 1}',
        "--create-candidate",
        "--json",
    ]
    with patch.object(sys, "argv", eval_argv):
        hermes_main.main()
    evaluated = json.loads(capsys.readouterr().out)
    assert evaluated["variant_id"] == created["variant_id"]
    assert evaluated["score"] == 0.77
    assert evaluated["meta_candidate_id"] == f"metacand_{created['variant_id']}"


def test_cli_dgm_evolve_smoke(tmp_path, monkeypatch, capsys):
    home = tmp_path / ".hermes"
    monkeypatch.setenv("HERMES_HOME", str(home))

    from hermes_cli import main as hermes_main

    argv = [
        "hermes",
        "dgm",
        "evolve",
        "--tenant-id",
        "atlas",
        "--repo-id",
        "atlas-email-flutter",
        "--objective",
        "improve OAuth browser validation",
        "--children",
        "2",
        "--tool-profile",
        "research_browser_eval",
        "--dry-score",
        "0.61",
        "--json",
    ]
    with patch.object(sys, "argv", argv):
        hermes_main.main()

    data = json.loads(capsys.readouterr().out)
    assert data["status"] == "completed"
    assert data["objective"] == "improve OAuth browser validation"
    assert len(data["child_ids"]) == 2
    assert len(data["evaluations"]) == 2
