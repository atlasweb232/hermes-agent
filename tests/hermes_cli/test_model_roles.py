import json
import sys
from unittest.mock import patch


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
    assert {role["role"] for role in output["roles"]} == {
        "curator",
        "learning_judge",
        "goal_judge",
    }
