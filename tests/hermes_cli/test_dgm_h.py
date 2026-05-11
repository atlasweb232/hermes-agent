"""Tests for the bounded DGM-H experiment lane."""

from __future__ import annotations

import json
import sys
from unittest.mock import patch

from hermes_cli.dgm_h import (
    create_dgm_variant,
    get_tool_profile_tools,
    record_dgm_evaluation,
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
    db = SessionDB()
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
