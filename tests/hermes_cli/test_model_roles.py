import json
import sys
from unittest.mock import patch

import pytest


def test_model_role_helper_updates_curator_and_goal_judge(_isolate_hermes_home):
    from hermes_cli.config import load_config, save_config
    from hermes_cli.model_roles import get_model_role, update_model_role

    cfg = load_config()
    update_model_role(cfg, "curator", provider="codex", model="codex", timeout=300)
    update_model_role(cfg, "goal_judge", provider="codex", model="codex", timeout=240)
    save_config(cfg)

    reloaded = load_config()
    curator = get_model_role(reloaded, "curator")
    goal_judge = get_model_role(reloaded, "goal_judge")

    assert curator["path"] == "supervisor.curator"
    assert curator["config"]["provider"] == "codex"
    assert curator["config"]["timeout_seconds"] == 300
    assert goal_judge["path"] == "auxiliary.goal_judge"
    assert goal_judge["config"]["provider"] == "codex"
    assert goal_judge["config"]["timeout"] == 240


def test_config_role_cli_sets_learning_judge(_isolate_hermes_home, capsys):
    from hermes_cli import main as hermes_main
    from hermes_cli.config import load_config

    with patch.object(
        sys,
        "argv",
        [
            "hermes",
            "config",
            "role",
            "set",
            "learning_judge",
            "--provider",
            "codex",
            "--model",
            "codex",
            "--timeout",
            "180",
            "--json",
        ],
    ):
        hermes_main.main()

    output = json.loads(capsys.readouterr().out)
    cfg = load_config()

    assert output["ok"] is True
    assert output["role"]["path"] == "supervisor.learning_judge"
    assert cfg["supervisor"]["learning_judge"]["provider"] == "codex"
    assert cfg["supervisor"]["learning_judge"]["timeout_seconds"] == 180


def test_config_roles_cli_lists_three_operational_roles(_isolate_hermes_home, capsys):
    from hermes_cli import main as hermes_main

    with patch.object(sys, "argv", ["hermes", "config", "roles", "--json"]):
        hermes_main.main()

    output = json.loads(capsys.readouterr().out)
    assert {role["role"] for role in output["roles"]} >= {
        "curator",
        "learning_judge",
        "goal_judge",
        "discussion_capture",
        "claim_extractor",
        "wiki_compiler",
        "dreaming",
        "citation_validator",
    }


def test_sidecar_roles_resolve_through_model_tiers(_isolate_hermes_home):
    from hermes_cli.config import load_config
    from hermes_cli.model_roles import get_model_role, list_model_tiers

    cfg = load_config()
    tiers = list_model_tiers(cfg)
    capture = get_model_role(cfg, "discussion_capture")
    extractor = get_model_role(cfg, "claim_extractor")
    compiler = get_model_role(cfg, "wiki_compiler")
    dreaming = get_model_role(cfg, "dreaming")

    assert {"programmatic", "cheap_reasoning", "strong_reasoning", "code_critical"} <= set(tiers)
    assert {"low_cost_reasoning", "balanced_reasoning"} <= set(tiers)
    assert capture["tier"] == "cheap_reasoning"
    assert capture["config"]["provider"] == tiers["cheap_reasoning"]["provider"]
    assert extractor["config"]["model"] == "gpt-oss-120b"
    assert compiler["tier"] == "strong_reasoning"
    assert dreaming["tier"] == "strong_reasoning"


def test_role_specific_provider_override_beats_tier(_isolate_hermes_home):
    from hermes_cli.config import load_config
    from hermes_cli.model_roles import get_model_role, update_model_role

    cfg = load_config()
    update_model_role(
        cfg,
        "claim_extractor",
        tier="low_cost_reasoning",
        provider="minimax",
        model="MiniMax-M2",
    )

    role = get_model_role(cfg, "claim_extractor")
    assert role["tier"] == "cheap_reasoning"
    assert role["config"]["provider"] == "minimax"
    assert role["config"]["model"] == "MiniMax-M2"


def test_config_role_cli_sets_sidecar_tier(_isolate_hermes_home, capsys):
    from hermes_cli import main as hermes_main
    from hermes_cli.config import load_config
    from hermes_cli.model_roles import get_model_role

    with patch.object(
        sys,
        "argv",
        [
            "hermes",
            "config",
            "role",
            "set",
            "wiki_compiler",
            "--tier",
            "low_cost_reasoning",
            "--json",
        ],
    ):
        hermes_main.main()

    output = json.loads(capsys.readouterr().out)
    role = get_model_role(load_config(), "wiki_compiler")

    assert output["ok"] is True
    assert output["role"]["tier"] == "cheap_reasoning"
    assert role["config"]["provider"] == "cerebras"


def test_config_tier_cli_updates_low_cost_provider(_isolate_hermes_home, capsys):
    from hermes_cli import main as hermes_main
    from hermes_cli.config import load_config
    from hermes_cli.model_roles import get_model_role, get_model_tier

    with patch.object(
        sys,
        "argv",
        [
            "hermes",
            "config",
            "tier",
            "set",
            "low_cost_reasoning",
            "--provider",
            "minimax",
            "--model",
            "MiniMax-M2",
            "--base-url",
            "https://api.minimax.io/v1",
            "--json",
        ],
    ):
        hermes_main.main()

    output = json.loads(capsys.readouterr().out)
    cfg = load_config()
    tier = get_model_tier(cfg, "low_cost_reasoning")
    role = get_model_role(cfg, "discussion_capture")

    assert output["ok"] is True
    assert tier["provider"] == "minimax"
    assert tier["model"] == "MiniMax-M2"
    assert role["config"]["provider"] == "minimax"


def test_model_role_doctor_reports_service_context_parity_without_secrets(_isolate_hermes_home, tmp_path):
    from hermes_cli.config import load_config
    from hermes_cli.model_roles import doctor_model_roles, update_model_role

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("codex", "claude"):
        path = bin_dir / name
        path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        path.chmod(0o755)

    cfg = load_config()
    update_model_role(cfg, "goal_judge", provider="codex", model="codex", timeout=180)
    update_model_role(cfg, "curator", provider="claude", model="sonnet", timeout=180)
    update_model_role(cfg, "learning_judge", provider="deepseek", model="deepseek-reasoner", timeout=180)
    env = {
        "PATH": str(bin_dir),
        "HERMES_SSH_PATH": str(bin_dir),
        "HERMES_GATEWAY_PATH": str(bin_dir),
        "HERMES_SIDECAR_PATH": str(bin_dir),
        "DEEPSEEK_API_KEY": "sk-testsecret1234567890",
    }

    output = doctor_model_roles(cfg, roles=["curator", "learning_judge", "goal_judge"], env=env)
    dumped = json.dumps(output)

    assert output["kind"] == "model_role_doctor"
    assert output["status"] == "ready"
    assert output["secrets_printed"] is False
    assert {item["role"] for item in output["diagnostics"]} == {"curator", "learning_judge", "goal_judge"}
    assert all(item["service_environment_parity"] is True for item in output["diagnostics"])
    assert "sk-testsecret" not in dumped
    assert "DEEPSEEK_API_KEY" in dumped


def test_model_role_doctor_degrades_when_service_executable_missing(_isolate_hermes_home, tmp_path):
    from hermes_cli.config import load_config
    from hermes_cli.model_roles import doctor_model_roles, update_model_role

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    codex_path = bin_dir / "codex"
    codex_path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    codex_path.chmod(0o755)

    cfg = load_config()
    update_model_role(cfg, "goal_judge", provider="codex", model="codex", timeout=180)
    output = doctor_model_roles(
        cfg,
        roles=["goal_judge"],
        env={
            "PATH": str(bin_dir),
            "HERMES_SSH_PATH": str(bin_dir),
            "HERMES_GATEWAY_PATH": str(tmp_path / "missing"),
            "HERMES_SIDECAR_PATH": str(bin_dir),
        },
    )

    role = output["diagnostics"][0]
    gateway = next(item for item in role["contexts"] if item["context"] == "gateway_service")

    assert output["status"] == "degraded"
    assert role["status"] == "degraded"
    assert "missing_executable" in role["degraded_reasons"]
    assert gateway["status"] == "degraded"


def test_config_role_doctor_cli_json_surface(_isolate_hermes_home, capsys, monkeypatch, tmp_path):
    from hermes_cli import main as hermes_main
    from hermes_cli.config import load_config, save_config
    from hermes_cli.model_roles import update_model_role

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    codex_path = bin_dir / "codex"
    codex_path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    codex_path.chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir))
    monkeypatch.setenv("HERMES_SSH_PATH", str(bin_dir))
    monkeypatch.setenv("HERMES_GATEWAY_PATH", str(bin_dir))
    monkeypatch.setenv("HERMES_SIDECAR_PATH", str(bin_dir))

    cfg = load_config()
    update_model_role(cfg, "goal_judge", provider="codex", model="codex", timeout=180)
    save_config(cfg)

    with patch.object(sys, "argv", ["hermes", "config", "role", "doctor", "--roles", "goal_judge", "--json"]):
        hermes_main.main()

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "ready"
    assert output["diagnostics"][0]["role"] == "goal_judge"
    assert output["diagnostics"][0]["contexts"][0]["path_entry_count"] >= 1


def test_model_role_doctor_backend_surface(_isolate_hermes_home):
    try:
        from starlette.testclient import TestClient
    except ImportError:
        pytest.skip("fastapi/starlette not installed")
    from hermes_cli.web_server import app, _SESSION_HEADER_NAME, _SESSION_TOKEN

    client = TestClient(app)
    client.headers[_SESSION_HEADER_NAME] = _SESSION_TOKEN
    response = client.get("/api/model/roles/doctor?roles=curator,learning_judge,goal_judge")

    assert response.status_code == 200
    payload = response.json()
    assert payload["kind"] == "model_role_doctor"
    assert {item["role"] for item in payload["diagnostics"]} == {"curator", "learning_judge", "goal_judge"}
    assert "api_key" not in json.dumps(payload).lower()
